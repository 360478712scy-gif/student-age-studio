"""Extract referenced installed audio for local browser previews; game bundles remain read-only."""
from storage_paths import game_cache, auxiliary_cache
from pathlib import Path, PurePosixPath
from platform_support import replace_file
import argparse
import gc
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
for directory in (HERE / 'vendor', HERE.parent / 'tools/asset-reader'):
    if directory.exists() and sys.platform != "win32": sys.path.insert(0, str(directory))
import UnityPy

def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    replace_file(temporary, path)

def extract(game):
    game = Path(game).resolve(); output = game_cache(game)
    cache = output / 'audio-cache'; cache.mkdir(parents=True, exist_ok=True)
    manifest = output / 'audio-map.json'
    previous = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    if previous.get('scope') != 'portable-audio-v2': previous = {}
    mapping = previous.get('audioMap', {}); metadata = previous.get('audioMetadata', {})
    done = previous.get('audioBundles', {}); failures = []; exported = 0
    catalog_path = output / 'game-catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'), strict=False) if catalog_path.exists() else {}
    rows = catalog.get('tables', {}).get('AudioCfg', {})
    wanted = {str(row.get('url', '')).replace('\\', '/').lower() for row in rows.values()}
    sources = []
    for root in (game / 'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64', game / 'DLC/StandaloneWindows64'):
        sources.extend(path for path in root.rglob('*.bundle') if 'audios_assets_' in path.name)
    def persist():
        write_json(manifest, {'scope':'portable-audio-v2', 'audioMap': mapping, 'audioMetadata': metadata, 'audioBundles': done, 'audioFailures': failures})
    for index, path in enumerate(sources):
        key = str(path.relative_to(game)); stamp = f'{path.stat().st_size}:{path.stat().st_mtime_ns}'
        if done.get(key) == stamp: continue
        print(json.dumps({'bundle': index + 1, 'total': len(sources), 'name': path.name, 'exported': exported, 'fraction': index/max(1,len(sources))}), flush=True)
        environment = None
        try:
            environment = UnityPy.load(str(path)); failed_before = len(failures)
            candidates=[(name,pointer) for name,pointer in environment.container.items() if '/audios/' in name.lower().replace('\\','/') and (not wanted or str(PurePosixPath(name.lower().replace('\\','/').split('/audios/',1)[1]).with_suffix('')) in wanted)]
            def progress(item):
                print(json.dumps({'bundle':index+1,'total':len(sources),'item':item,'items':len(candidates),'exported':exported,'fraction':(index+item/max(1,len(candidates)))/max(1,len(sources))}),flush=True)
            progress(0)
            for item, (name, pointer) in enumerate(candidates,1):
                lowered = name.lower().replace('\\', '/')
                if '/audios/' not in lowered: continue
                resource = str(PurePosixPath(lowered.split('/audios/', 1)[1]).with_suffix(''))
                if wanted and resource not in wanted: continue
                reader = pointer.deref() if hasattr(pointer, 'deref') else pointer
                if reader.type.name != 'AudioClip':
                    progress(item);continue
                try:
                    clip = reader.parse_as_object(); samples = clip.samples
                    if not samples: raise ValueError('Empty audio')
                    filename, raw = next(iter(samples.items()))
                    if not raw or len(raw) > 256 * 1024 * 1024: raise ValueError('Audio size')
                    digest = hashlib.sha256(resource.encode()).hexdigest()[:24]
                    suffix = Path(filename).suffix.lower()
                    if suffix not in {'.wav', '.ogg', '.m4a', '.mp3'}: raise ValueError('Audio format')
                    with tempfile.TemporaryDirectory(dir=cache, prefix='.extract-') as temporary:
                        source = Path(temporary) / ('source' + suffix); source.write_bytes(raw)
                        converted = Path(temporary) / 'preview.m4a'
                        # AAC makes original OGG/FSB playable in the macOS WebKit app as well as Chrome.
                        if shutil.which('afconvert') and suffix == '.wav':
                            result = subprocess.run(['afconvert', '-f', 'm4af', '-d', 'aac', '-b', '128000', str(source), str(converted)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
                            if result.returncode == 0 and converted.is_file(): source = converted; suffix = '.m4a'
                        destination = cache / (digest + suffix); replace_file(source, destination)
                    portable = 'audio-cache/' + destination.name
                    for alias in (resource, 'Audios/' + resource, name): mapping[alias] = portable
                    metadata[resource] = {'duration': round(float(clip.m_Length), 3), 'channels': int(clip.m_Channels), 'frequency': int(clip.m_Frequency), 'size': destination.stat().st_size}
                    exported += 1
                    if exported % 12 == 0: persist()
                except Exception as error: failures.append({'resource': resource, 'error': type(error).__name__, 'detail': str(error)[:400]})
                finally: progress(item)
            if len(failures) == failed_before: done[key] = stamp
            persist()
        except Exception as error: failures.append({'bundle': key, 'error': type(error).__name__, 'detail': str(error)[:400]})
        finally: environment = None; gc.collect()
    persist()
    return {'exported': exported, 'resourceKeys': len(mapping), 'failures': len(failures)}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--game', required=True)
    print(json.dumps(extract(parser.parse_args().game)), flush=True)
