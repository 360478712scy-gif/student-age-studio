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


def portrait_dimensions(game, catalog, paths):
    # Serialize this metadata manifest, never the editing/saving store.
    with _portrait_dimensions_lock:
        return _portrait_dimensions(game, catalog, paths)


def _known_portrait_dimensions(path, relative):
    """Reuse measured runtime dimensions only for the exact game resource bytes."""
    try:
        import hashlib
        seed = json.loads(Path(__file__).with_name('native-portrait-dimensions.json').read_text(encoding='utf-8'))
        if seed.get('version') != 2:
            return None
        entry = seed.get('bundles', {}).get(relative)
        if not entry or path.stat().st_size != entry['size']:
            return None
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest == entry['sha256']:
            return entry['sizes']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _portrait_resource_dimensions(env):
    # UISprite.SetTextureUrl -> ResInfo.GetSpriteAsync loads Texture2D and
    # Sprite.Create uses its default 100 PPU. The imported Sprite's PPU is NOT
    # used on this path. Atlas-only resources retain their Sprite dimensions.
    textures, sprites = {}, {}
    for name, pointer in env.container.items():
        resource = resource_name(name, 'textures')
        if not resource or not resource.startswith(('role_full/', 'role_half/', 'role_head/', 'role_comic/', 'role_comic_head/', 'role_photo/')):
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


def _portrait_dimensions(game, catalog, paths):
    """Read native portrait sizes, without decoding textures or enlarging thumbnails.

    Cache by bundle fingerprint. Older thumbnail caches can be upgraded on demand.
    Caller serializes this small metadata cache's writes.
    """
    game = Path(game)
    mapping = catalog.get('assetMap', {})
    wanted = {str(p): mapping.get(str(p), mapping.get(str(p).lower())) for p in paths
              if isinstance(p, str) and not p.lower().replace('\\', '/').startswith('mods/')}
    wanted = {p: v for p, v in wanted.items() if v}
    if not wanted:
        return {}
    home = game_cache(game)
    manifest = home / 'portrait-dimensions-v5.json'
    try:
        cache = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cache = {}
    resources = {}
    wanted_exports = set(wanted.values())
    for alias, exported in mapping.items():
        if exported in wanted_exports:
            resource = resource_name('/' + alias.lstrip('/'), 'textures')
            if resource and resource.startswith(('role_full/', 'role_half/', 'role_head/', 'role_comic/', 'role_comic_head/', 'role_photo/')):
                resources[resource] = exported
    if not resources:
        return {}
    # Addressables groups for full portraits and expression sheets use role bundles.
    sizes = {}
    changed = False
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
        stamp = f'{path.stat().st_size}:{path.stat().st_mtime_ns}'
        entry = cache.get(relative, {})
        if entry.get('stamp') != stamp:
            dimensions = _known_portrait_dimensions(path, relative)
            if dimensions is None:
                env = UnityPy.load(str(path))
                dimensions = _portrait_resource_dimensions(env)
            entry = {'stamp': stamp, 'sizes': dimensions}
            cache[relative] = entry
            changed = True
        sizes.update(entry.get('sizes', {}))
    if changed:
        home.mkdir(parents=True, exist_ok=True)
        write_json(manifest, cache)
    exported_sizes = {exported: sizes[resource] for resource, exported in resources.items() if resource in sizes}
    return {p: exported_sizes[v] for p, v in wanted.items() if v in exported_sizes}


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


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--game', default=str(DEFAULT_GAME))
    args = parser.parse_args()
    result = extract(args.game, lambda i, n, name, count: print(json.dumps(
        {'bundle': i + 1, 'total': n, 'name': name, 'exported': count}), flush=True))
    print(json.dumps(result), flush=True)
