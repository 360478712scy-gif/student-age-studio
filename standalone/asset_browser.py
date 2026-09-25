"""Readable browse folders for asset libraries.

Extracted game art is cached under hash file names, so opening the cache folder itself is useless for
finding a picture. A browse folder holds the library's current files under their display names, as
hard links into the cache (no extra disk space); a copy is used only where a link is not possible
(another volume, or a file system without hard links). The folder is owned by the editor and rebuilt
on every request; nothing outside it is ever modified.
"""
import os
import re
import shutil
from pathlib import Path

from storage_paths import cache_root

ROOT_NAME = '素材浏览'
MARKER = '.studio-asset-browser'
LIMIT = 5000
README = '说明.txt'
NOTE = ('这里是编辑器生成的素材浏览文件夹，每次点击“打开缓存位置”都会重新生成。\n'
        '文件与编辑器缓存共享同一份数据：需要修改图片时，请先复制到其他位置再改。\n')
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _safe(text, fallback):
    name = _UNSAFE.sub('_', str(text or '')).strip(' .')
    return (name or fallback)[:80]


def folder(title):
    root = cache_root() / ROOT_NAME
    target = root / _safe(title, '素材')
    return root, target


def build(title, entries):
    """entries: iterable of (display name, source path). Returns (folder, written, skipped)."""
    root, target = folder(title)
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).touch(exist_ok=True)
    # Only folders inside the editor-owned browse root are cleared and rebuilt.
    if target.exists() and target.resolve().parent == root.resolve() and (root / MARKER).is_file():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    (target / README).write_text(NOTE, encoding='utf-8')
    used, written, skipped = set(), 0, 0
    for name, source in entries:
        if written >= LIMIT:
            skipped += 1
            continue
        source = Path(source) if source else None
        if not source or not source.is_file():
            skipped += 1
            continue
        stem = _safe(name, source.stem)
        candidate, n = stem, 2
        while (candidate + source.suffix).casefold() in used:
            candidate = f'{stem} ({n})'
            n += 1
        used.add((candidate + source.suffix).casefold())
        destination = target / (candidate + source.suffix.lower())
        try:
            os.link(source, destination)
        except OSError:
            try:
                shutil.copy2(source, destination)
            except OSError:
                skipped += 1
                continue
        written += 1
    return target, written, skipped


_MAP_SCREEN = re.compile(r'^(?:map/|[a-z0-9_]+/(?:img_map|bg_dnd_map|icon_map))', re.I)
_LANGUAGE_COPIES = ('sprites_en/', 'sprites_zh-hant/')


def map_library(store):
    """Original map art: every MapCfg location with its scene backgrounds (and their high-school
    versions), plus the map screen sprites. Only names and asset keys; images load through /api/assets."""
    catalog = store.catalog()
    asset_map = catalog.get('assetMap', {}) if isinstance(catalog.get('assetMap'), dict) else {}
    backgrounds = store.catalog_rows('BgCfg')
    locations = []
    for key, row in sorted(store.catalog_rows('MapCfg').items(), key=lambda pair: int(pair[0]) if str(pair[0]).isdigit() else 0):
        images, seen = [], set()
        for field in ('bg', 'bg2'):
            ident = str(row.get(field) or '')
            bg = backgrounds.get(ident)
            if not bg:
                continue
            for label, variant in ((bg.get('name') or ident, bg), ('高中 · ' + str(bg.get('name') or ident), backgrounds.get(str(bg.get('gaozhongUrl') or '')))):
                url = variant and variant.get('url')
                if isinstance(url, str) and url and url not in seen:
                    seen.add(url)
                    images.append({'name': label, 'path': url, 'backgroundId': int(variant['id']) if str(variant.get('id', '')).isdigit() else None})
        locations.append({'id': int(key) if str(key).isdigit() else key, 'name': row.get('name') or '', 'shortName': row.get('shortName') or '', 'images': images})
    screens = sorted(key for key in asset_map
                     if _MAP_SCREEN.match(key) and not key.startswith(_LANGUAGE_COPIES) and '/' in key
                     and not key.split('/', 1)[0].lower() in ('atlas', 'assets', 'textures'))
    return {'locations': locations, 'screens': [{'name': key.split('/')[-1], 'path': key} for key in screens]}


def reveal_map(store, project):
    from platform_support import open_directory
    library = map_library(store)
    entries = []
    for location in library['locations']:
        for image in location['images']:
            try:
                entries.append((f"{location['name']} · {image['name']}", store.project_asset(project, image['path'])))
            except Exception:
                entries.append((image['name'], None))
    for screen in library['screens']:
        try:
            entries.append(('地图画面 · ' + screen['path'].replace('/', '_'), store.project_asset(project, screen['path'])))
        except Exception:
            entries.append((screen['name'], None))
    target, written, skipped = build('地图 · 原版', entries)
    open_directory(target)
    return {'path': str(target), 'count': written, 'skipped': skipped}
