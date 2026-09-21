"""Read installed Unity bundles into a local preview cache; never modify a bundle."""
from storage_paths import game_cache, auxiliary_cache
from pathlib import Path, PurePosixPath
from platform_support import replace_file
import argparse
import gc
import hashlib
import json
import os
import struct
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
for directory in (HERE / 'vendor', HERE.parent / 'tools/asset-reader'):
    if directory.exists() and sys.platform != "win32":
        sys.path.insert(0, str(directory))
import UnityPy
from UnityPy.helpers import CompressionHelper

DEFAULT_GAME = Path.home() / 'Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/StudentAge'
# Increment when coverage changes: old bundle timestamps alone must not skip new kinds.
EXTRACTION_SCOPE = 'workshop-all-textures-atlases-v5-native-portraits'
TEXTURE_GROUPS = {
    'bg', 'cg', 'cg2', 'role_full', 'role_head', 'role_half', 'role_comic',
    'ending', 'item', 'book', 'icon', 'kzone', 'kzone_head', 'kzone_dlc',
    'kzone_big', 'action', 'social', 'memory', 'comic', 'scene', 'map',
}
# BgCfg 7001 references this original texture outside the normal background group.
# Keep this exception exact instead of exporting unrelated temporary textures.
EXTRA_TEXTURES = {'tmp/img_quanjiafu2'}


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    replace_file(temporary, path)


def resource_name(name, kind):
    lowered = str(name).lower().replace('\\', '/')
    marker = '/' + kind.lower() + '/'
    if marker not in lowered:
        return None
    relative = lowered.split(marker, 1)[1]
    return str(PurePosixPath(relative).with_suffix(''))


def bundle_members(path):
    """Read only UnityFS's small directory, without decompressing its asset payload."""
    def cstring(stream):
        chars = bytearray()
        while len(chars) < 4096:
            char = stream.read(1)
            if not char:
                raise ValueError('Incomplete bundle header')
            if char == b'\0':
                return chars.decode('utf-8')
            chars.extend(char)
        raise ValueError('Invalid bundle name')

    from io import BytesIO
    with path.open('rb') as stream:
        if cstring(stream) != 'UnityFS':
            return []
        version, = struct.unpack('>I', stream.read(4))
        cstring(stream)
        engine = cstring(stream)
        size, compressed, uncompressed, flags = struct.unpack('>QIII', stream.read(20))
        # This game's bundles use format 8; format 6 also aligns on newer Unity.
        if version >= 7 or tuple(int(p) for p in engine.split('.')[:2]) >= (2019, 4):
            stream.seek((stream.tell() + 15) // 16 * 16)
        if compressed > 32 * 1024 * 1024 or uncompressed > 64 * 1024 * 1024:
            raise ValueError('Unreasonable bundle directory')
        if flags & 0x80:
            stream.seek(size - compressed)
        block = stream.read(compressed)
        compression = flags & 0x3f
        if compression in (2, 3):
            block = CompressionHelper.decompress_lz4(block, uncompressed)
        elif compression == 1:
            block = CompressionHelper.decompress_lzma(block)
        elif compression != 0:
            raise ValueError('Unsupported directory compression')
        reader = BytesIO(block)
        reader.seek(16)
        count, = struct.unpack('>I', reader.read(4))
        reader.seek(count * 10, 1)
        count, = struct.unpack('>I', reader.read(4))
        names = []
        for _ in range(count):
            reader.seek(20, 1)
            names.append(cstring(reader).lower())
        return names


def connect_dependencies(environment, member_index):
    """Resolve sprite PPtrs by CAB name across Addressables bundles on demand."""
    original = environment.find_file
    loaded = set()

    def find_file(name, is_dependency=True):
        simple = str(name).replace('\\', '/').rsplit('/', 1)[-1].lower()
        found = environment.get_cab(simple)
        if found:
            return found
        path = member_index.get(simple)
        if path and path not in loaded:
            loaded.add(path)
            environment.load_file(str(path))
            found = environment.get_cab(simple)
            if found:
                return found
        return original(name, is_dependency=is_dependency)

    environment.find_file = find_file


def cached_file(output, mapping, aliases):
    """Reuse only our own existing cache, never paths outside StudentAgeStudio/assets."""
    cache = (output / 'assets').resolve()
    for key in aliases:
        relative = mapping.get(key)
        if not isinstance(relative, str):
            continue
        candidate = (output / relative).resolve()
        if candidate.parent == cache and candidate.is_file():
            return 'assets/' + candidate.name
    return None


_portrait_dimensions_lock = threading.RLock()
_portrait_unpack_guard = threading.Lock()
_portrait_unpacking = threading.Event()
_portrait_unpack_thread = None
# Tests replace this with an in-process runner; production measures in a worker process.
_portrait_unpack_runner = None
# Reading one big role bundle can take a long time on a cold cache. A request only
# reads what earlier passes measured; one background pass does the measuring so a slow
# drive can delay a size but can never freeze the editor.
PORTRAIT_DIMENSION_BUDGET = 2.0
PORTRAIT_UNPACK_BUDGET = 300.0
# A bundle that fails to measure is retried: a couple of immediate attempts cover a
# transient "antivirus holds the file", then a growing delay keeps the disk quiet. It is
# never disabled for the session, so the size still arrives once the cause disappears.
PORTRAIT_RETRY_FREE = 2
PORTRAIT_RETRY_BASE = 30.0
PORTRAIT_RETRY_MAX = 300.0
NATIVE_PORTRAIT_PREFIXES = ('role_full/', 'role_half/', 'role_head/', 'role_comic/', 'role_comic_head/', 'role_photo/')
PORTRAIT_MANIFEST_NAME = 'portrait-dimensions-v5.json'
_portrait_seed = None
_portrait_retry = {}
# A pass is only progress when the manifest moved. A bundle that cannot be read
# (antivirus, permissions) or a cache directory that cannot be written measures
# nothing, and the request path must not start one process per request for it.
_portrait_pass_failures = 0
_portrait_pass_not_before = 0.0


def _portrait_pass_delay(failures):
    """The same curve as the per-bundle retry: two immediate passes, then 30/60/…/300s."""
    if failures <= PORTRAIT_RETRY_FREE:
        return 0.0
    return min(PORTRAIT_RETRY_MAX, PORTRAIT_RETRY_BASE * (2 ** (failures - PORTRAIT_RETRY_FREE - 1)))


def _portrait_manifest_stamp(game):
    """(mtime_ns, size) of the measurement manifest, or None while it is absent."""
    try:
        stat = (game_cache(Path(game)) / PORTRAIT_MANIFEST_NAME).stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def portrait_dimensions(game, catalog, paths, budget=PORTRAIT_DIMENSION_BUDGET):
    """Portrait sizes measured so far; a request never waits for a bundle to be unpacked.

    A bundle that still needs measuring is handled by one shared background pass, so a
    slow, huge or offline game folder can delay a size but can never freeze the editor.
    """
    deadline = time.monotonic() + max(0.0, budget)
    # While a pass unpacks bundles the request stays read-only instead of queueing
    # behind it: a slow measurement must never turn into a slow editor.
    held = False
    if not _portrait_unpacking.is_set():
        held = _portrait_dimensions_lock.acquire(timeout=min(0.5, max(0.0, budget)))
    try:
        result, needs_unpack = _portrait_dimensions(game, catalog, paths, deadline, persist=held)
    finally:
        if held:
            _portrait_dimensions_lock.release()
    if needs_unpack and time.monotonic() >= _portrait_pass_not_before:
        _unpack_portraits_in_background(game, catalog, paths)
    return result


def _unpack_portraits_in_background(game, catalog, paths):
    global _portrait_unpack_thread
    with _portrait_unpack_guard:
        if _portrait_unpacking.is_set():
            return
        _portrait_unpacking.set()
        runner = _portrait_unpack_runner or _spawn_portrait_measure
        before = _portrait_manifest_stamp(game)
        try:
            started = runner(game, catalog, paths)
        except Exception:
            _portrait_unpacking.clear()
            raise
        _portrait_unpack_thread = threading.Thread(target=_watch_portrait_measure, args=(started, game, before),
                                                   daemon=True, name='portrait-measure')
        thread = _portrait_unpack_thread
    thread.start()


def _spawn_portrait_measure(game, catalog, paths):
    """Measure in a separate process.

    Opening a role bundle is seconds of reading and decompression, and on Windows a
    virus scanner makes it far longer. Doing that here would hold this process's GIL
    for the whole time, so every other request would feel slow until it finished.
    """
    import subprocess
    from platform_support import process_options, worker_command
    options = process_options()
    if sys.platform == 'win32':
        options['creationflags'] |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
    wanted = json.dumps([str(path) for path in paths][:128], ensure_ascii=False)
    command = worker_command(Path(__file__), game) + ['--portrait-measure', '--paths', wanted]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)


def _watch_portrait_measure(process, game=None, before=None):
    try:
        process.wait(timeout=PORTRAIT_UNPACK_BUDGET)
    except Exception:
        try:
            process.kill(); process.wait()
        except Exception:
            pass
    finally:
        # Only success moves the cache forward. `needs_unpack` says a candidate bundle
        # has no entry for its revision yet, not that it can be read or that the cache
        # can be written, so a failing pass has to be rate limited here: otherwise every
        # request would start one more process that reads and unpacks the same bundle.
        global _portrait_pass_failures, _portrait_pass_not_before
        if game is not None and _portrait_manifest_stamp(game) != before:
            _portrait_pass_failures = 0
        else:
            _portrait_pass_failures += 1
            _portrait_pass_not_before = time.monotonic() + _portrait_pass_delay(_portrait_pass_failures)
        with _portrait_unpack_guard:
            _portrait_unpacking.clear()


def _portrait_seed_bundles():
    global _portrait_seed
    if _portrait_seed is None:
        try:
            seed = json.loads(Path(__file__).with_name('native-portrait-dimensions.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            seed = {}
        _portrait_seed = seed if isinstance(seed, dict) and seed.get('version') == 2 else {}
    return _portrait_seed.get('bundles', {})


def _known_portrait_dimensions(path, relative, deadline=None):
    """Reuse measured runtime dimensions only for the exact game resource bytes.

    The hash is the only part of a request that still touches game bytes, so it is
    read in blocks and abandoned at `deadline`: a slow or antivirus-scanned drive
    makes the request answer from what it has instead of waiting for the whole file.
    The background pass then verifies the same bundle without a request behind it.
    """
    try:
        import hashlib
        entry = _portrait_seed_bundles().get(relative)
        if not entry or path.stat().st_size != entry['size']:
            return None
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while True:
                block = stream.read(1 << 20)
                if not block:
                    break
                digest.update(block)
                if deadline is not None and time.monotonic() >= deadline:
                    return None
        if digest.hexdigest() == entry['sha256']:
            return entry['sizes']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _portrait_resources(mapping, wanted_exports):
    """Native texture resource -> exported file, for the paths the caller asked about."""
    resources = {}
    for alias, exported in mapping.items():
        if exported in wanted_exports:
            resource = resource_name('/' + str(alias).lstrip('/'), 'textures')
            if resource and resource.startswith(NATIVE_PORTRAIT_PREFIXES):
                resources[resource] = exported
    return resources


def native_portrait_paths(catalog, paths):
    """Requested paths whose size must come from the game texture, never from an export.

    Exported previews are scaled to a shared height, so their pixel size is not the
    runtime size the game lays out with. Callers must leave these paths unanswered
    until the game texture has actually been measured.
    """
    mapping = catalog.get('assetMap') if isinstance(catalog, dict) else None
    if not isinstance(mapping, dict):
        return set()
    wanted = {str(p): mapping.get(str(p), mapping.get(str(p).lower())) for p in paths
              if isinstance(p, str) and not p.lower().replace('\\', '/').startswith('mods/')}
    exports = set(_portrait_resources(mapping, set(v for v in wanted.values() if v)).values())
    return {p for p, exported in wanted.items() if exported in exports}


def _portrait_resource_dimensions(env, wanted=None):
    # UISprite.SetTextureUrl -> ResInfo.GetSpriteAsync loads Texture2D and
    # Sprite.Create uses its default 100 PPU. The imported Sprite's PPU is NOT
    # used on this path. Atlas-only resources retain their Sprite dimensions.
    textures, sprites = {}, {}
    for name, pointer in env.container.items():
        resource = resource_name(name, 'textures')
        if not resource or not resource.startswith(NATIVE_PORTRAIT_PREFIXES):
            continue
        if wanted is not None and resource not in wanted:
            continue
        obj = pointer.deref()
        if obj.type.name == 'Texture2D':
            data = obj.parse_as_object()
            textures[resource] = [data.m_Width, data.m_Height]
        elif obj.type.name == 'Sprite':
            data = obj.parse_as_object()
            ppu = float(data.m_PixelsToUnits)
            if ppu > 0:
                sprites[resource] = [data.m_Rect.width * 100 / ppu, data.m_Rect.height * 100 / ppu]
    return {**sprites, **textures}


def _portrait_retry_ready(stamp):
    record = _portrait_retry.get(stamp)
    if not isinstance(record, dict):
        return True
    failures = max(0, int(record.get('failures', 0)))
    if failures <= PORTRAIT_RETRY_FREE:
        return True
    delay = min(PORTRAIT_RETRY_MAX, PORTRAIT_RETRY_BASE * (2 ** (failures - PORTRAIT_RETRY_FREE - 1)))
    return time.monotonic() - float(record.get('at', 0) or 0) >= delay


def _portrait_retry_failed(stamp):
    record = _portrait_retry.setdefault(stamp, {'failures': 0})
    record['failures'] = int(record.get('failures', 0)) + 1
    record['at'] = time.monotonic()


def _portrait_retry_done(stamp):
    _portrait_retry.pop(stamp, None)


def _portrait_dimensions(game, catalog, paths, deadline, unpack=False, persist=True):
    """Read native portrait sizes, without decoding textures or enlarging thumbnails.

    Cache by bundle fingerprint. Older thumbnail caches can be upgraded on demand.
    Caller serializes this small metadata cache's writes. Loading a bundle is the slow
    part, so it only happens when `unpack` is set (the background pass); a request only
    reads what earlier passes measured, and reports `needs_unpack` so the caller can
    start that pass instead of waiting for it. `unpack` marks that background pass, which
    is the only place a game bundle is ever opened.
    """
    game = Path(game)
    catalog = catalog if isinstance(catalog, dict) else {}
    mapping = catalog.get('assetMap')
    if not isinstance(mapping, dict):
        mapping = {}
    wanted = {str(p): mapping.get(str(p), mapping.get(str(p).lower())) for p in paths
              if isinstance(p, str) and not p.lower().replace('\\', '/').startswith('mods/')}
    wanted = {p: v for p, v in wanted.items() if v}
    if not wanted:
        return {}, False
    home = game_cache(game)
    manifest = home / PORTRAIT_MANIFEST_NAME
    try:
        cache = json.loads(manifest.read_text(encoding='utf-8'))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    wanted_exports = set(wanted.values())
    resources = _portrait_resources(mapping, wanted_exports)
    if not resources:
        return {}, False
    # Addressables groups for full portraits and expression sheets use role bundles.
    sizes = {}
    needs_unpack = False
    for relative in catalog.get('bundles', {}):
        if 'textures_assets_' not in relative.lower():
            continue
        outputs = catalog.get('bundleOutputs', {}).get(relative)
        if isinstance(outputs, list) and not wanted_exports.intersection(outputs):
            continue
        if not isinstance(outputs, list) and 'role' not in Path(relative).name.lower() and not Path(relative).name.lower().startswith('dlc_textures_assets_'):
            continue
        path = game / relative
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        stamp = f'{stat.st_size}:{stat.st_mtime_ns}'
        entry = cache.get(relative) if isinstance(cache.get(relative), dict) else {}
        # A fingerprint match means this exact revision was measured in full, so a
        # portrait it does not list is genuinely absent from the bundle.
        measured = entry.get('sizes') if entry.get('stamp') == stamp and isinstance(entry.get('sizes'), dict) else {}
        if measured:
            sizes.update(measured)
        missing = set(resources) - set(sizes)
        if not missing:
            break
        if entry.get('stamp') == stamp:
            continue
        if time.monotonic() >= deadline:
            if not unpack:
                needs_unpack = True
            continue
        if not _portrait_retry_ready(stamp):
            # Failed recently: wait out the delay instead of hammering the disk. The
            # next pass retries, so a transient read failure heals by itself.
            if not unpack:
                needs_unpack = True
            continue
        dimensions = _known_portrait_dimensions(path, relative, deadline)
        if dimensions is not None:
            merged = dimensions
        elif unpack:
            try:
                # The whole bundle is measured once per revision: a portrait it does not
                # list is then genuinely absent, so the fingerprint alone answers later.
                merged = _portrait_resource_dimensions(UnityPy.load(str(path)))
            except Exception:
                # One unreadable bundle must not stop the pass; retry it after the delay.
                _portrait_retry_failed(stamp)
                continue
        else:
            # Measuring this bundle means unpacking it; never do that on a request.
            needs_unpack = True
            continue
        _portrait_retry_done(stamp)
        sizes.update(merged)
        cache[relative] = {'stamp': stamp, 'sizes': merged}
        # Persist per bundle: a later pass resumes after the bundles already measured.
        # A reader that does not own the manifest lock never writes it.
        if persist:
            try:
                home.mkdir(parents=True, exist_ok=True)
                write_json(manifest, cache)
            except OSError:
                pass
    exported_sizes = {exported: sizes[resource] for resource, exported in resources.items() if resource in sizes}
    return {p: exported_sizes[v] for p, v in wanted.items() if v in exported_sizes}, needs_unpack


def extract(game, progress=None):
    game = Path(game).resolve()
    output = game_cache(game)
    cache = output / 'assets'
    cache.mkdir(parents=True, exist_ok=True)
    manifest = output / 'asset-map.json'
    current = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    mapping = current.get('assetMap', {})
    done = current.get('bundles', {})
    scopes = current.get('bundleScopes', {})
    outputs = current.get('bundleOutputs', {})
    sources = []
    member_index = {}
    for folder in (game / 'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64', game / 'DLC/StandaloneWindows64'):
        for path in folder.rglob('*.bundle'):
            try:
                for member in bundle_members(path):
                    member_index[member] = path
            except (ValueError, OSError, struct.error):
                pass  # UnityPy will report an unreadable relevant source below.
            # Unity Addressables labels can include a directory, especially Atlas bundles.
            relative = str(path.relative_to(folder)).lower()
            if 'textures_assets_' in relative or 'atlas_assets_' in relative:
                sources.append(path)
    sources.sort(key=lambda p: ('textures_assets_' in str(p), str(p)))
    failures = []
    exported = 0
    reused = 0

    def persist():
        write_json(manifest, {**current, 'assetMap': mapping, 'bundles': done,
                             'bundleScopes': scopes, 'bundleOutputs': outputs, 'extractionScope': EXTRACTION_SCOPE,
                             'unityPyVersion': UnityPy.__version__, 'failures': failures})

    def save_picture(reader, resource, kind, aliases, stale=False):
        nonlocal exported, reused
        # Namespaced aliases prevent an atlas and texture with the same short name
        # from accidentally reusing each other's pixels.
        portable = None if stale else cached_file(output, mapping, [kind + '/' + resource])
        if portable:
            reused += 1
        else:
            picture = reader.parse_as_object().image
            picture.thumbnail((1600, 1200))
            cache_key = resource if kind == 'Textures' else kind.lower() + '/' + resource
            digest = hashlib.sha256(cache_key.encode()).hexdigest()[:24]
            suffix = '.jpg' if kind == 'Textures' and resource.split('/', 1)[0] in {'bg', 'cg', 'cg2'} else '.png'
            destination = cache / (digest + suffix)
            temporary = cache / (digest + '.tmp')
            if suffix == '.jpg':
                picture.convert('RGB').save(temporary, format='JPEG', quality=90)
            else:
                picture.save(temporary, format='PNG', compress_level=3)
            replace_file(temporary, destination)
            portable = 'assets/' + destination.name
            exported += 1
        active_outputs.add(portable)
        for alias in [resource, kind + '/' + resource, *aliases]:
            mapping[alias] = portable
        if kind == 'Textures' and resource.startswith('role_full/'):
            mapping[resource.split('/', 1)[1]] = portable
        # Checkpoint large portrait bundles so interruption preserves completed previews.
        if exported and exported % 40 == 0:
            persist()
            if progress: progress(index, len(sources), path.name, exported)

    for index, path in enumerate(sources):
        stamp = f'{path.stat().st_size}:{path.stat().st_mtime_ns}'
        key = str(path.relative_to(game))
        if done.get(key) == stamp and scopes.get(key) == EXTRACTION_SCOPE and key in outputs and all((output/p).is_file() for p in outputs[key]):
            continue
        if progress:
            progress(index, len(sources), path.name, exported)
        active_outputs = set()
        environment = None
        bundle_failures = len(failures)
        stale = key in done and done[key] != stamp
        try:
            environment = UnityPy.load(str(path))
            containers = list(environment.container.items())
            # A texture and its tight-packed sprite share a resource alias. Keep
            # the full texture canvas, including transparent margins, for portraits.
            texture_resources = {resource_name(name, 'textures') for name, pointer in containers
                                 if (pointer.deref() if hasattr(pointer, 'deref') else pointer).type.name == 'Texture2D'}
            connect_dependencies(environment, member_index)
            for name, pointer in containers:
                reader = pointer.deref() if hasattr(pointer, 'deref') else pointer
                if reader.type.name == 'SpriteAtlas':
                    atlas_name = resource_name(name, 'atlas')
                    if not atlas_name:
                        continue
                    atlas = reader.parse_as_object()
                    for sprite_pointer in atlas.m_PackedSprites:
                        try:
                            sprite_reader = sprite_pointer.deref()
                            sprite_name = sprite_reader.parse_as_object().m_Name
                            resource = atlas_name + '/' + sprite_name
                            save_picture(sprite_reader, resource, 'Atlas',
                                         ['assets/res/atlas/' + resource], stale)
                        except Exception as exc:
                            failures.append({'resource': atlas_name, 'error': type(exc).__name__, 'detail': str(exc)[:400]})
                    continue
                resource = resource_name(name, 'textures')
                if not resource:
                    continue
                if reader.type.name not in {'Sprite', 'Texture2D'}:
                    continue
                if reader.type.name == 'Sprite' and resource in texture_resources:
                    continue
                try:
                    portrait_upgrade = resource.startswith(('role_full/', 'role_comic/')) and scopes.get(key) != EXTRACTION_SCOPE
                    save_picture(reader, resource, 'Textures', [name], stale or portrait_upgrade)
                except Exception as exc:
                    failures.append({'resource': resource, 'error': type(exc).__name__, 'detail': str(exc)[:400]})
            if len(failures) == bundle_failures:
                done[key] = stamp
                scopes[key] = EXTRACTION_SCOPE
                outputs[key] = sorted(active_outputs)
            persist()
        except Exception as exc:
            failures.append({'bundle': key, 'error': type(exc).__name__, 'detail': str(exc)[:400]})
        finally:
            environment = None
            gc.collect()
    persist()
    return {'exported': exported, 'reused': reused, 'resourceKeys': len(mapping),
            'failures': len(failures), 'manifest': str(manifest)}


def measure_catalog(game):
    """The catalog views a measurement pass needs, read straight from the game cache.

    The worker process has no StudioStore, and only these three maps take part in
    resolving a portrait path to its bundle.
    """
    try:
        cache = json.loads((game_cache(Path(game)) / 'asset-map.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(cache, dict):
        return {}
    return {'assetMap': cache.get('assetMap') or {}, 'bundles': cache.get('bundles') or {},
            'bundleOutputs': cache.get('bundleOutputs') or {}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--game', default=str(DEFAULT_GAME))
    parser.add_argument('--portrait-measure', action='store_true')
    parser.add_argument('--paths', default='[]')
    args = parser.parse_args()
    if args.portrait_measure:
        try:
            paths = json.loads(args.paths)
        except ValueError:
            paths = []
        paths = paths if isinstance(paths, list) else []
        _portrait_dimensions(args.game, measure_catalog(args.game), paths,
                             time.monotonic() + PORTRAIT_UNPACK_BUDGET, unpack=True)
        print(json.dumps({'measured': len(paths)}), flush=True)
    else:
        result = extract(args.game, lambda i, n, name, count: print(json.dumps(
            {'bundle': i + 1, 'total': n, 'name': name, 'exported': count}), flush=True))
        print(json.dumps(result), flush=True)
