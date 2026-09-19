"""Unified, read-only asset discovery with explicit transactional copying on selection.

The backend module is injected to share its validation and transaction primitives
without importing the server a second time when it runs as __main__.
"""
from __future__ import annotations
from storage_paths import game_cache, auxiliary_cache

from search_text import matches as search_matches
import base64
import copy
import hashlib
import io
import json
import os
import re
import secrets
import time
import threading
import urllib.parse
import warnings
from collections import OrderedDict
from contextlib import nullcontext, contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from asset_labels import asset_name, asset_name_index
from platform_support import file_fingerprint

# Bytes of converted media written per transaction during batch imports (memory bound, not a total limit).
IMPORT_SLICE = 192 * 1024 * 1024
from headshots import head_paths, crop_head, preview_image, has_affection, scene_location

KINDS = {'portrait': 'PersonCfg', 'background': 'BgCfg', 'cg': 'CGCfg', 'audio': 'AudioCfg', 'social': 'KZoneContentCfg', 'avatar':'KZoneAvatarCfg', 'item':'ItemCfg'}
# BMP/TGA are accepted and converted to PNG on import so the warmup previews
# and the importer agree on the same set; game-facing bytes stay PNG/JPEG/WebP.
IMAGES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tga'}
AUDIO = {'.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac'}
# Background pixel-hash queue: keep pending work and defer new entries until
# the next listing when capacity is available; repeated refreshes cannot evict
# and starve the oldest unfinished image.
_HASH_PENDING_CAP = 2000
# NTFS may defer directory timestamps across rapid creates. File fingerprints
# remain authoritative for content, but cannot replace enumerating Windows names.
_DIRECTORY_NAMES_REUSABLE = os.name != 'nt'


def strings(value):
    return [v for v in (value if isinstance(value, list) else [value]) if isinstance(v, str) and v.strip()]


def stamp(path):
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def link(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


class AssetCatalog:
    def __init__(self, store, backend, settings_path=None):
        self.store, self.api = store, backend
        self.settings_path = Path(settings_path or backend.settings_path().with_name('asset-folders.json'))
        self.cache = OrderedDict()
        # Bounded LRU: evicted entries recompute byte-identical results.
        self.validation = OrderedDict()
        self._validation_cap = 5000
        self._validation_guard = threading.RLock()
        self.image_hashes = {}
        self.hash_index = None
        self._hash_guard = threading.RLock()
        self._hash_pending = OrderedDict()
        self._hash_running = False
        self._hash_active = None
        self._hash_total = self._hash_done = self._hash_generation = 0
        self.hash_index_path = auxiliary_cache(self.settings_path.parent, 'AssetCache/pixel-hashes-v1.json')
        self.request_resources = None

    def error(self, text, status=400, code='invalid_request'):
        raise self.api.ApiError(text, status, code)

    def kind(self, value):
        value = 'portrait' if value == 'person' else value
        if value not in KINDS: self.error('素材类型无效。')
        return value

    def _settings(self):
        value = self.api.read_json(self.settings_path, {'version': 1, 'folders': {}})
        if not isinstance(value, dict) or not isinstance(value.get('folders', {}), dict):
            self.error('素材文件夹设置损坏，请恢复设置文件后再试。', 422)
        return value

    def folders(self):
        settings = self._settings()
        result = {}
        for kind in KINDS:
            path = settings.get('folders', {}).get(kind, '')
            path = path if isinstance(path, str) else ''
            exists = bool(path) and Path(path).is_dir() and not link(Path(path))
            result[kind] = {'path': path, 'exists': exists,
                            'message': '打开素材目录时自动检索此文件夹和子文件夹。' if exists else '文件夹已移动或不可用。' if path else '尚未设置文件夹。'}
        return {'revision': hashlib.sha256(self.api.json_bytes(settings)).hexdigest(), 'folders': result}

    def set_folder(self, payload):
        with self.store.lock:
            kind = self.kind(payload.get('kind'))
            current = self.folders()
            if payload.get('settingsRevision') != current['revision']:
                self.error('素材文件夹设置已经变化，请刷新后再试。', 409, 'conflict')
            value = payload.get('path')
            if not isinstance(value, str) or len(value) > 4096 or '\x00' in value:
                self.error('请选择有效的素材文件夹。')
            value = os.path.expandvars(value.strip().strip('"\''))
            if value:
                path = Path(value).expanduser()
                if link(path): self.error('请选择实际文件夹，不能使用符号链接或目录联接。', 403)
                path = path.resolve()
                if not path.is_dir(): self.error('这个素材文件夹不存在，请重新选择。', 404)
                try: next(path.iterdir(), None)
                except OSError: self.error('无法读取这个素材文件夹，请检查访问权限。', 403)
                value = str(path)
            settings = self._settings()
            settings.setdefault('folders', {})[kind] = value
            self.api.atomic_write(self.settings_path, self.api.json_bytes(settings))
            self.cache.clear()
            return self.folders()

    def _context(self, query, writable=False):
        project = self.store.project(query.get('projectId'), writable=writable)
        revision = self.store.revision(project)
        if query.get('revision') != revision:
            self.error('当前模组已经变化，请重新载入素材目录。', 409, 'conflict')
        source = query.get('source', 'original')
        if source not in {'original', 'mod', 'custom'}: self.error('素材来源无效。')
        source_project = self.store.project(query.get('sourceProjectId')) if source == 'mod' and query.get('sourceProjectId') not in (None, '', 'all') else project
        source_revision = self.store.revision(source_project)
        if query.get('sourceRevision') and query['sourceRevision'] != source_revision:
            self.error('来源模组已经变化，请刷新素材目录。', 409, 'conflict')
        kind = self.kind(query.get('kind', 'background'))
        try:
            grade, cloth = int(query.get('grade', 1)), int(query.get('cloth', 0))
            if grade not in (1, 2, 3) or not 0 <= cloth <= 9: raise ValueError()
        except (TypeError, ValueError): self.error('人物预览学段或服装无效。')
        if kind != 'portrait': grade, cloth = 1, 0
        return project, revision, source, source_project, source_revision, kind, grade, cloth

    def _rows(self, project, name, warnings_list):
        try:
            rows = self.api.read_json(self.api.safe_path(project.path, 'Cfgs/zh-cn/' + name + '.json'), {})
            if isinstance(rows, dict):
                for key, row in rows.items():
                    if (self.api.valid_id(key) or key == '0') and isinstance(row, dict) and row.get('id') != int(key):
                        row['id'] = int(key); warnings_list.append(name + ' 的素材编号已在读取副本中按表键修复，原文件保持不变。')
            self.api.validate_map(rows, name, allow_zero=True)
            return rows
        except self.api.ApiError as error:
            warnings_list.append(error.message)
            return {}

    def _check_path(self, path, root):
        path, root = Path(path), Path(root)
        if link(root) or not self.api.inside(path, root): self.error('素材路径已变化或超出了所选文件夹。', 403)
        try: relative = path.relative_to(root)
        except ValueError: self.error('素材路径超出了所选文件夹。', 403)
        current = root
        for part in relative.parts:
            current = current / part
            if link(current): self.error('素材包含符号链接或目录联接，已跳过。', 403)
        if not path.is_file(): self.error('素材已移动或删除，请刷新列表。', 404)
        return path

    def _validate_file(self, path, kind, root):
        self._check_path(path, root)
        fingerprint = stamp(path)
        key = (str(path), fingerprint, "audio" if kind == "audio" else "image")
        with self._validation_guard:
            if key in self.validation:
                self.validation.move_to_end(key)
                return self.validation[key]
        if fingerprint[1] <= 0 or fingerprint[1] > (48 if kind == 'audio' else 24) * 1024 * 1024:
            self.error('素材为空或超过大小限制（图片 24 MB、音频 48 MB）。', 413)
        if kind == 'audio':
            suffix = path.suffix.lower()
            if suffix not in AUDIO: self.error('不支持的声音格式。')
            with path.open('rb') as stream: head = stream.read(16)
            valid = {'.wav': len(head) >= 12 and head[:4] in (b'RIFF', b'RF64') and head[8:12] == b'WAVE',
                     '.ogg': head.startswith(b'OggS'), '.flac': head.startswith(b'fLaC'),
                     '.mp3': head.startswith(b'ID3') or len(head) >= 4 and head[0] == 255 and head[1] & 224 == 224 and head[1] & 6 != 0,
                     '.aac': len(head) >= 4 and head[0] == 255 and head[1] & 246 == 240,
                     '.m4a': len(head) >= 12 and head[4:8] == b'ftyp'}
            if not valid.get(suffix): self.error('文件内容与声音格式不符。', 422)
            info = {'size': fingerprint[1]}
            if suffix == '.wav':
                import wave
                try:
                    with wave.open(str(path), 'rb') as audio:
                        frames, rate = audio.getnframes(), audio.getframerate()
                        if frames <= 0 or rate <= 0: raise ValueError()
                        expected = frames * audio.getnchannels() * audio.getsampwidth()
                        # Chunked read: same total-length verdict as one-shot
                        # readframes(frames) but without a full-PCM transient.
                        total, remaining = 0, frames
                        while remaining > 0:
                            chunk = audio.readframes(min(4096, remaining))
                            if not chunk: break
                            total += len(chunk)
                            remaining -= min(4096, remaining)
                        if total != expected: raise ValueError()
                        info['duration'] = frames / rate
                except (wave.Error, EOFError, ValueError): self.error('WAV 音频不完整或无法解码。', 422)
        else:
            if path.suffix.lower() not in IMAGES: self.error('请选择 PNG、JPEG、WebP、BMP 或 TGA 图片。')
            if self.api.Image is None: self.error('缺少图片解码组件。', 503)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', self.api.Image.DecompressionBombWarning)
                    # Single disk read; two decodes over identical bytes so the
                    # accept/reject set matches the old double-open sequence
                    # while halving Defender-scanned reads on Windows.
                    data = path.read_bytes()
                    with self.api.Image.open(io.BytesIO(data)) as image:
                        if image.format not in {'PNG', 'JPEG', 'WEBP', 'BMP', 'TGA'}:
                            self.error('图片实际格式必须为 PNG、JPEG、WebP、BMP 或 TGA。', 422)
                        info = {'width': image.width, 'height': image.height, 'size': fingerprint[1]}
                        image.verify()
                    with self.api.Image.open(io.BytesIO(data)) as image: image.load()
            except self.api.ApiError: raise
            except Exception: self.error('图片损坏或无法解码。', 422)
        if stamp(path) != fingerprint: self.error('读取时素材发生变化，请刷新列表。', 409, 'conflict')
        info['_fingerprint'] = fingerprint
        self._remember_validation(key, info)
        return info

    def _remember_validation(self, key, info):
        # Single choke point for the validation cache so background warmup and
        # foreground checks share the same LRU bound.
        with self._validation_guard:
            self.validation[key] = info
            self.validation.move_to_end(key)
            while len(self.validation) > self._validation_cap:
                self.validation.popitem(last=False)

    def _resource(self, project, resource, kind, validate=False):
        path = self.store.project_asset(project, resource)
        root = project.path if self.api.inside(path, project.path) else game_cache(self.store.game)
        self._check_path(path, root)
        if kind == 'audio' and path.suffix.lower() not in AUDIO or kind != 'audio' and path.suffix.lower() not in IMAGES:
            self.error('资源类型与素材目录不符。', 422)
        info = self._validate_file(path, kind, root) if validate else {'_fingerprint': stamp(path)}
        return {'_path': path, '_root': root, **info}

    def _people(self, project, source, warnings_list):
        base = self.store.catalog_rows('PersonCfg')
        local = self._rows(project, 'PersonCfg', warnings_list) if source != 'original' else {}
        hidden = self.api.read_json(project.path/'StudentAgeStudio/goal-images.json', {}) if source != 'original' else {}
        return {key: {**base.get(key, {}), **row} for key, row in {**base, **local}.items() if key not in hidden}

    def _association(self, row, persons, source):
        # CGCfg has no character field. Its authored Chinese title is evidence;
        # resource names and numerical CG IDs are deliberately never guessed.
        name = row.get('name', '')
        prefix = re.split(r'[:：]', name, maxsplit=1)[0].strip() if isinstance(name, str) and re.search(r'[:：]', name) else ''
        found = [(key, person.get('name')) for key, person in persons.items() if prefix and person.get('name') == prefix]
        if source == 'original' and prefix == '你' and '0' in persons: found = [('0', persons['0'].get('name', '主角'))]
        return {'personIds': [int(key) for key, _ in found], 'personNames': [name for _, name in found],
                'personAssociation': 'config-title' if found else 'unmarked'}

    def _portrait_variants(self, project, ident, row, faces):
        variants = {}
        for grade, field, icon in ((1, 'url', 'icon_xx'), (2, 'url2', 'icon')):
            for cloth, resource in enumerate(row.get(field) if isinstance(row.get(field), list) else strings(row.get(field))):
                if cloth <= 9 and isinstance(resource, str) and resource.strip(): variants[(grade, cloth, 0)] = {'resource': resource, 'faceName': '默认表情'}
            for key, face in faces.items():
                if not str(key).isdigit() or int(key) // 1000 != ident: continue
                cloth, expression = (int(key) % 1000) // 100, int(key) % 100
                if isinstance(face.get(icon), str) and face[icon].strip():
                    names = strings(face.get('name'))
                    variants[(grade, cloth, expression)] = {'resource': face[icon], 'faceName': names[0] if names else '表情 ' + str(expression)}
        output = []
        for (grade, cloth, face), variant in sorted(variants.items()):
            try:
                resolved = self._resource(project, variant['resource'], 'portrait')
                output.append({**variant, 'grade': grade, 'cloth': cloth, 'face': face, **resolved})
            except self.api.ApiError: pass
        return output

    def _configured(self, project, source, kind, grade, cloth, warnings_list):
        original = self.store.catalog_rows(KINDS[kind])
        local = self._rows(project, KINDS[kind], warnings_list) if source != 'original' else {}
        rows = original if source == 'original' else local
        if kind == 'item':
            books = self.store.catalog_rows('BookCfg') if source == 'original' else self._rows(project, 'BookCfg', warnings_list)
            rows = {**rows, **{key: dict(row, type=3) for key, row in books.items()}}
        persons = self._people(project, source, warnings_list) if kind in {'portrait','social','cg'} else {}
        result = []
        if kind == 'portrait':
            local_faces = self._rows(project, 'ModFaceCfg', warnings_list) if source != 'original' else {}
            faces = {**self.store.catalog_rows('ModFaceCfg'), **local_faces}
            ids = set(rows)
            if source != 'original': ids.update(str(int(key) // 1000) for key in local_faces if str(key).isdigit())
            requested_cloth = cloth
            for key in sorted(ids, key=lambda v: int(v)):
                cloth = requested_cloth
                row = persons.get(key, {})
                ident = int(key)
                variants = self._portrait_variants(project, ident, row, faces)
                preview = next((v for v in variants if v['grade'] == min(grade, 2) and v['cloth'] == cloth and v['face'] == 0), None)
                preview = preview or next((v for v in variants if v['grade'] == min(grade, 2) and v['face'] == 0), None) or next(iter(variants), None)
                native_role = None
                if source == 'original':
                    native_grade = min(grade, 2)
                    models = row.get('l2d' if native_grade == 1 else 'l2d2') or []
                    if not any(isinstance(model, str) and model.strip() for model in models) and not preview:
                        native_grade = 3 - native_grade
                        models = row.get('l2d' if native_grade == 1 else 'l2d2') or []
                    if isinstance(models, list) and (cloth >= len(models) or not models[cloth]):
                        cloth = next((i for i, model in enumerate(models) if isinstance(model, str) and model.strip()), cloth)
                    if isinstance(models, list) and cloth < len(models) and isinstance(models[cloth], str) and models[cloth].strip():
                        native_role = ident
                        if preview and (preview['grade'] != min(grade, 2) or preview['cloth'] != cloth): preview = None
                    try:
                        cached = self._resource(project, f'portrait-cache/{ident}-{native_grade-1}-{cloth}-0.png', kind)
                        preview = {'grade': native_grade, 'cloth': cloth, 'face': 0, **cached}
                    except self.api.ApiError: pass
                if not preview and native_role is None:
                    continue
                item = {'assetId': 'portrait:' + key, 'sourceId': ident, 'kind': kind, 'name': asset_name(row, kind),
                        'gender': row.get('gender', 0), 'hasAffection': has_affection(row), 'variantCount': len(variants), 'available': bool(preview),
                        'canImport': source == 'original' or bool(variants), 'personIds': [ident], 'personNames': [asset_name(row, kind)],
                        'previewGrade': preview.get('grade', min(grade, 2)) if preview else (native_grade if native_role is not None else min(grade, 2)),
                        'previewCloth': preview.get('cloth', cloth) if preview else cloth,
                        '_row': row, '_variants': variants, '_sourceProject': project, '_nativeRole': native_role,
                        **(preview or {})}
                if not preview: item['message'] = '此人物尚无可读取的静态立绘，可先使用原版人物。' if source == 'original' else '此人物仅有无法读取的模型或素材，暂时不能复制。'
                result.append(item)
        elif kind == 'social':
            # A photo belongs to the actual post author, independent of CG IDs.
            photos = {}
            for key, row in rows.items():
                if not self.api.valid_id(key): continue
                role = row.get('role', 0)
                if not isinstance(role, int): continue
                person = persons.get(str(role), {})
                name = person.get('name') or ('白雨' if role == 0 else f'空间人物 {role}')
                for index, resource in enumerate(strings(row.get('imgs'))):
                    if resource in photos:
                        item = photos[resource]
                        if role not in item['personIds']:
                            item['personIds'].append(role); item['personNames'].append(name)
                            item['name'] = '、'.join(item['personNames']) + ' · 配图'
                        continue
                    media = {}
                    try: media = self._resource(project, resource, kind)
                    except self.api.ApiError: pass
                    item = {'assetId': f'social:{key}:{index}', 'sourceId': int(key), 'kind': kind,
                            'name': f'{name} · 配图 {index + 1}', 'resource': resource,
                            'available': bool(media), 'canImport': source == 'original' or bool(media),
                            'personIds': [role], 'personNames': [name], '_row': row,
                            '_variants': [], '_sourceProject': project, **media}
                    if not media: item['message'] = '配图尚未导出或文件已缺失。'
                    photos[resource] = item
            result = list(photos.values())
        else:
            names = {**original, **local}
            name_index = asset_name_index(names)
            associations = {}
            if kind == 'cg' and source != 'original':
                metadata = self.api.read_json(self.api.safe_path(project.path, 'StudentAgeStudio/editor-state.json'), {})
                if not isinstance(metadata, dict) or not isinstance(metadata.get('assetAssociations', {}), dict): self.error('素材关联记录格式损坏。', 422)
                associations = metadata.get('assetAssociations', {}).get('cg', {})
                if not isinstance(associations, dict): self.error('CG 人物关联记录格式损坏。', 422)
            for key, row in rows.items():
                if not self.api.valid_id(key): continue
                resources = strings(row.get('urls') if kind == 'cg' else row.get('icon') if kind in {'avatar','item'} else row.get('url'))
                variants = []
                for index, resource in enumerate(resources):
                    try: variants.append({'resource': resource, 'index': index, **self._resource(project, resource, kind)})
                    except self.api.ApiError: pass
                name = (row.get('name') or Path(resources[0].replace('\\','/')).stem if resources else '头像 '+key) if kind in {'avatar','item'} else asset_name(row, kind, name_index=name_index)
                item = {'assetId': kind + ':' + key, 'sourceId': int(key), 'kind': kind, 'name': name,
                        'variantCount': len(resources), 'available': bool(variants), 'canImport': source == 'original' or bool(variants),
                        'personIds': [], 'personNames': [], '_row': row, '_variants': variants, '_sourceProject': project,
                        **(variants[0] if variants else {})}
                if kind == 'cg':
                    item.update(self._association(row, persons, source))
                    if source != 'original':
                        saved = associations.get(key, {})
                        if isinstance(saved, dict) and isinstance(saved.get('personNames'), list):
                            selected_names = [value for value in saved['personNames'] if isinstance(value, str)]
                            selected = [(ident, person.get('name')) for ident, person in persons.items() if str(ident) in map(str, saved.get('personIds', [])) or person.get('name') in selected_names]
                            item.update(personIds=[int(ident) for ident, _ in selected], personNames=list(dict.fromkeys([name for _, name in selected] + selected_names)), personAssociation='saved')
                if kind in {'audio','item'}: item['type'] = row.get('type', 1)
                if kind == 'audio': item['audioGroups'] = row.get('group', [])
                if kind == 'background': item['location'] = scene_location(name)
                if not variants: item['message'] = '素材图片尚未导出或文件已缺失。'
                result.append(item)
        for item in result:
            item['origin'] = 'game' if source == 'original' else 'mod'
            row = item.get('_row', {})
            item['searchNames'] = list(dict.fromkeys([str(row.get('name') or ''), str(row.get('title') or ''),
                *[value for field in ('url', 'url2', 'urls', 'imgs', 'content', 'icon', 'icon_xx', 'l2d', 'l2d2') for value in strings(row.get(field))]]))
        return result

    def _scan(self, project, kind, folder, warnings_list):
        result = []
        if not folder.get('path'): return result
        root = Path(folder['path'])
        if not root.is_dir() or link(root):
            warnings_list.append('素材文件夹已移动、不可读或已成为链接。'); return result
        persons = self._people(project, 'custom', warnings_list)
        by_name = {}
        for ident, row in persons.items():
            if isinstance(row.get('name'), str): by_name.setdefault(row['name'], []).append(int(ident))
        visited, skipped = 0, 0
        def walk_error(error): warnings_list.append('部分子文件夹不可读取：' + str(error.filename or ''))
        for directory, folders, files in os.walk(root, followlinks=False, onerror=walk_error):
            base = Path(directory)
            folders[:] = [name for name in sorted(folders) if not name.startswith('.') and not link(base / name)]
            for name in sorted(files):
                path = base / name
                if path.suffix.lower() not in (AUDIO if kind == 'audio' else IMAGES): continue
                visited += 1
                relative = path.relative_to(root)
                try:
                    info = self._validate_file(path, kind, root)
                except (self.api.ApiError, OSError): skipped += 1; continue
                names = list(dict.fromkeys(part for part in relative.parts[:-1] if part in by_name)) if kind == 'cg' else []
                ident = hashlib.sha256((kind + '\0' + str(root) + '\0' + relative.as_posix() + '\0' + str(info['_fingerprint'])).encode()).hexdigest()[:32]
                item = {'assetId': 'file:' + ident, 'kind': kind, 'name': path.stem, 'origin': 'folder', 'fileName': path.name,
                        'relativePath': relative.as_posix(), 'available': True, 'canImport': True,
                        'personIds': list(dict.fromkeys(ident for name in names for ident in by_name[name])), 'personNames': names,
                        'personAssociation': 'folder-name' if names else 'unmarked', '_path': path, '_root': root, **info}
                if kind == 'audio':
                    parts = {part.casefold() for part in relative.parts[:-1]}
                    explicit = bool(parts & {'bgm', '背景音乐', '音乐', 'sfx', '音效'})
                    item.update(type=2 if parts & {'sfx', '音效'} else 1, audioTypeInferred=explicit)
                if kind == 'background': item['location'] = scene_location(relative.as_posix())
                if kind == 'portrait': item['hasAffection'] = False
                result.append(item)
        if skipped: warnings_list.append(f'跳过了 {skipped} 个损坏、过大、不可读取或包含链接的文件。')
        return result

    def _pixel_hash(self, path, version):
        try:
            with self.api.Image.open(path) as image:
                # Bound concurrent decoding even for unusually large mod images.
                if image.width * image.height > 16777216: return 'file:' + str(path), False
                rgba = image.convert('RGBA')
                key = str(rgba.size) + ':' + hashlib.sha256(rgba.tobytes()).hexdigest()
        except (OSError, ValueError, self.api.Image.DecompressionBombError):
            return 'file:' + str(path), False
        if file_fingerprint(path) != version:
            self.error('图片在读取期间发生变化，请刷新素材目录。', 409, 'conflict')
        return key, True

    def hash_progress(self):
        with self._hash_guard:
            return {'running': self._hash_running, 'done': self._hash_done, 'total': self._hash_total,
                    'percent': int(100*self._hash_done/max(1,self._hash_total))}

    def _hash_worker(self):
        # One decoder, no store.lock. Foreground editing and saving keep priority.
        while True:
            with self._hash_guard:
                if not self._hash_pending:
                    self._hash_running = False
                    self._hash_generation += 1
                    if len(self.image_hashes) > 20000:
                        # Insertion-order trim: drop oldest quarter
                        # to avoid recompute stampedes; values recompute identically.
                        for old in list(self.image_hashes)[:5000]:
                            self.image_hashes.pop(old, None)
                    try: self.api.atomic_write(self.hash_index_path, self.api.json_bytes(self.hash_index), fsync=False)
                    except TypeError:
                        try: self.api.atomic_write(self.hash_index_path, self.api.json_bytes(self.hash_index))
                        except OSError: pass
                    except OSError: pass
                    return
                (path, version), _ = self._hash_pending.popitem(last=False)
                self._hash_active = (path,version)
            try:
                key, valid = self._pixel_hash(path, version)
            except Exception:
                key, valid = 'file:'+str(path), False
            with self._hash_guard:
                self.image_hashes[(str(path), version)] = key
                if valid: self.hash_index[str(path)] = {'stamp':list(version), 'hash':key}
                self._hash_done += 1
                self._hash_active = None
                # Windows: fewer fsyncs, same final index content.
                _interval = 64 if os.name == 'nt' else 16
                if self._hash_done % _interval == 0:
                    try: self.api.atomic_write(self.hash_index_path, self.api.json_bytes(self.hash_index), fsync=False)
                    except TypeError:
                        try: self.api.atomic_write(self.hash_index_path, self.api.json_bytes(self.hash_index))
                        except OSError: pass
                    except OSError: pass
            # Retain the existing yield interval; avoid adding fixed latency
            # to every image before foreground responsiveness is measured.
            time.sleep(.01)

    def _deduplicate_backgrounds(self, items, versions=None):
        # versions maps known _path -> fingerprint so repeated passes over the
        # same files (entries + list filtering) fingerprint each file once.
        hashes = {}
        with self._hash_guard:
            if self.hash_index is None:
                try: self.hash_index = self.api.read_json(self.hash_index_path, {})
                except self.api.ApiError: self.hash_index = {}
                if not isinstance(self.hash_index, dict): self.hash_index = {}
            for path in dict.fromkeys(item['_path'] for item in items if item.get('_path')):
                if versions is not None and path in versions:
                    version = versions[path]
                else:
                    version = file_fingerprint(path)
                key = self.image_hashes.get((str(path), version))
                saved = self.hash_index.get(str(path), {})
                if key is None and isinstance(saved, dict) and saved.get('stamp') == list(version) and isinstance(saved.get('hash'), str): key = saved['hash']
                if key is not None: hashes[path] = key
                elif (path,version) not in self._hash_pending and (path,version) != self._hash_active:
                    if len(self._hash_pending) >= _HASH_PENDING_CAP: continue
                    self._hash_pending[(path,version)] = None
                    self._hash_total += 1
            if self._hash_pending and not self._hash_running:
                self._hash_running = True
                self._hash_done = 0
                self._hash_total = len(self._hash_pending)
                threading.Thread(target=self._hash_worker,daemon=True).start()
        unique = {}
        for original in items:
            item = dict(original)
            item['searchNames'] = list(item.get('searchNames', []))
            item['locations'] = list(item.get('locations', [item.get('location', '其他')]))
            key = hashes.get(item.get('_path'))
            if key is None:
                resources = strings(item.get('resource') or item.get('_row', {}).get('url'))
                key = ('resource:' + str(item.get('_sourceProject').id) + ':' + '|'.join(resources)) if resources else item['assetId']
            if key in unique:
                existing = unique[key]
                existing.setdefault('searchNames', []).append(item['name'])
                existing['searchNames'].extend(item.get('searchNames', []))
                existing.setdefault('locations', [existing.get('location', '其他')]).append(item.get('location', '其他'))
                existing['duplicateCount'] = existing.get('duplicateCount', 0) + 1
            else:
                unique[key] = item
        return list(unique.values())

    def _folder_watch(self, folder):
        result=[]
        if not folder or not folder.get('path'): return result
        root=Path(folder['path'])
        if not root.is_dir() or link(root): return [(str(root), None)]
        # Directory identities reveal additions/removals. Reuse their names
        # while still checking every media file's real change fingerprint:
        # rewriting a file's contents does not bump its directory stamp, so
        # file versions are never trusted from the directory entry alone.
        cache = getattr(self, '_directory_watch_cache', None)
        if cache is None: self._directory_watch_cache = cache = OrderedDict()
        pending = [root]
        while pending:
            base = pending.pop()
            try: stamp = file_fingerprint(base)
            except OSError:
                result.append((str(base), None)); continue
            result.append((str(base), stamp))
            saved = cache.get(str(base))
            if _DIRECTORY_NAMES_REUSABLE and saved and saved[0] == stamp:
                dirs, files = saved[1:]
                cache.move_to_end(str(base))
            else:
                dirs, files = [], []
                try:
                    with os.scandir(base) as entries:
                        for entry in entries:
                            if entry.is_symlink(): continue
                            path = base / entry.name
                            if entry.is_dir(follow_symlinks=False):
                                if not entry.name.startswith('.'): dirs.append(path)
                            elif path.suffix.lower() in IMAGES|AUDIO: files.append(path)
                except OSError:
                    result.append((str(base), None)); continue
                cache[str(base)] = (stamp, dirs, files)
                while len(cache)>4096: cache.popitem(last=False)
            pending.extend(path for path in dirs if not link(path))
            for path in files:
                if link(path): continue
                try: result.append((str(path), file_fingerprint(path)))
                except FileNotFoundError:
                    cache.pop(str(base), None)
                except OSError: result.append((str(path), None))
        return sorted(result)

    def _preview_inputs(self, project, kind):
        # Read-only previews depend on media definitions, not every dialogue,
        # event and unrelated table. Saves/imports still use live full revisions.
        names = [KINDS[kind]]
        if kind in {'portrait', 'social', 'cg'}: names += ['PersonCfg', 'ModFaceCfg']
        if kind == 'item': names += ['BookCfg']
        paths = [project.path/'Cfgs/zh-cn'/(name+'.json') for name in dict.fromkeys(names)]
        paths += [project.path/'manifest.json', project.path/'StudentAgeStudio/original-edits.json',
                  game_cache(self.store.game)/'game-catalog.json', self.settings_path]
        if kind in {'portrait', 'social', 'cg'}: paths.append(project.path/'StudentAgeStudio/goal-images.json')
        if kind == 'cg': paths.append(project.path/'StudentAgeStudio/editor-state.json')
        result = []
        for path in paths:
            try: value = file_fingerprint(path)
            except FileNotFoundError: value = None
            result.append((path, value))
        return tuple(result)

    def _entries(self, query, refresh_media=True):
        project, revision, source, source_project, source_revision, kind, grade, cloth = self._context(query)
        all_mods = source == 'mod' and query.get('sourceProjectId') in (None, '', 'all')
        sources = sorted(self.store.projects(), key=lambda p: (p.id != project.id, p.name)) if all_mods else []
        source_stamps = [(p.id, self.store.revision(p)) for p in sources]
        folders = self.folders() if source == 'custom' else None
        self.store.catalog()
        key_data = [project.id, revision, source, source_project.id, source_revision, kind, grade, cloth,
                    self.store._catalog_stamp, folders['revision'] if folders else None, source_stamps, query.get('variantMode'), query.get('variantPerson'), query.get('library')]
        if query.get('variantMode') in ('portrait','expression'):
            key_data.append([(p.parent.name,file_fingerprint(p)) for p in sorted((game_cache(self.store.game) / 'native-models-v1').glob('*/model.json'))])
        cache_key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()[:32]
        # Obsolete revisions can no longer be selected/imported; retaining up
        # to 96 full catalogues after text saves multiplies session memory.
        for key, old in list(self.cache.items()):
            if old['projectId'] == project.id and old['revision'] != revision:
                self.cache.pop(key, None)
        folder_watch = self._folder_watch(folders['folders'][kind]) if folders else []
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            # Files already proven unchanged by the fresh folder watch above
            # are not fingerprinted again; only mod-side files outside any
            # watched folder still get their per-open check.
            try:
                watched = {row[0] for row in folder_watch} if cached.get('_folderWatch', []) == folder_watch else None
                unchanged = watched is not None and all(
                    str(path) in watched or file_fingerprint(path) == version
                    for path, version in cached.get('_files', []))
            except OSError: unchanged = False
            if unchanged:
                if '_rawItems' in cached and cached.get('_hashGeneration') != self._hash_generation:
                    generation = self._hash_generation
                    cached['items'] = self._deduplicate_backgrounds(cached['_rawItems'])
                    cached['_hashGeneration'] = generation
                    cached['_itemById'] = {item['assetId']: item for item in cached['items']}
                self.cache.move_to_end(cache_key)
                return cached
            if not refresh_media:
                self.error('素材文件已经变化，请刷新目录后重新选择。', 409, 'conflict')
        warnings_list = []
        if all_mods:
            items = []
            for selected, (_, source_stamp) in zip(sources, source_stamps):
                for item in self._configured(selected, 'mod', kind, grade, cloth, warnings_list):
                    item.update(rawAssetId=item['assetId'], sourceProjectId=selected.id, sourceProjectName=selected.name, sourceRevision=source_stamp, _sourceRevision=source_stamp)
                    item['assetId'] = selected.id + '|' + item['assetId']
                    items.append(item)
        else:
            items = [] if source == 'custom' and kind == 'social' else self._configured(source_project, source, kind, grade, cloth, warnings_list)
        if source == 'custom':
            for row in items: row['origin'] = 'imported'
            items += self._scan(project, kind, folders['folders'][kind], warnings_list)
        if kind == 'portrait' and query.get('variantMode') in ('portrait', 'expression'):
            from character_media import expand
            items = expand(self, items, query['variantMode'], query.get('variantPerson', ''))
        files = {entry['_path'] for item in items for entry in [item, *item.get('_variants', [])] if entry.get('_path')}
        # The fresh folder watch above already fingerprinted these files; reuse
        # its versions instead of a second syscall pass over the library.
        folder_versions = dict(folder_watch)
        file_versions = []
        for path in files:
            key = str(path)
            if key in folder_versions and folder_versions[key] is not None:
                file_versions.append((path, folder_versions[key]))
            else:
                file_versions.append((path, file_fingerprint(path)))
        versions = dict(file_versions)
        for item in items:
            paths = sorted({entry['_path'] for entry in [item, *item.get('_variants', [])] if entry.get('_path')})
            item['mediaRevision'] = hashlib.sha256(json.dumps([(str(path),versions[path]) for path in paths]).encode()).hexdigest()[:24]
        if source == 'custom' and query.get('library') == '1': items = [item for item in items if item['origin'] == 'folder']
        raw_items = items; hash_generation = self._hash_generation
        if kind == 'background' and query.get('library') != '1': items = self._deduplicate_backgrounds(items, versions)
        result = {'allMods': all_mods, 'catalogKey': cache_key, 'source': source, 'kind': kind, 'projectId': project.id, 'revision': revision,
                  'sourceProject': source_project.public() if source == 'mod' and not all_mods else None, 'sourceRevision': source_revision,
                  'items': items, 'warnings': list(dict.fromkeys(warnings_list)), '_project': project, '_files': file_versions, '_folderWatch':folder_watch}
        if kind == 'background' and query.get('library') != '1': result.update(_rawItems=raw_items, _hashGeneration=hash_generation)
        if folders: result['folder'] = {**folders['folders'][kind], 'settingsRevision': folders['revision']}
        result['_itemById'] = {item['assetId']: item for item in items}
        result['_mediaStamps'] = versions
        result['_previewInputs'] = {p.id: self._preview_inputs(p, kind) for p in [project, source_project, *sources]}
        self.cache[cache_key] = result
        while len(self.cache) > 96: self.cache.popitem(last=False)
        if any(self.store.revision(p) != version for p, (_, version) in zip(sources, source_stamps)):
            self.cache.pop(cache_key, None); self.error('来源模组在读取时发生变化，请刷新目录。', 409, 'conflict')
        if revision != self.store.revision(project) or source_revision != self.store.revision(source_project):
            self.cache.pop(cache_key, None); self.error('读取时模组配置发生变化，请刷新目录。', 409, 'conflict')
        return result

    def list(self, query):
        with self.store.lock, self.store.catalog_scope():
            result = self._entries(query)
            items = result['items']
            if query.get('socialOnly') == '1':
                people_table=self.store.table(query.get('projectId'),'PersonCfg')
                people_rows=people_table['rows']
                eligible={str(k) for k,r in people_rows.items() if int(k)>0 and r.get('init') and r['init'][0] in (2,3,4)}
                items=[item for item in items if str(item.get('sourceId')) in eligible and (item.get('sourceProjectId') in (None,'',query.get('projectId')) or query.get('source')=='original')]
                # Selecting an existing social role must not require a readable portrait.
                source_ids=set(self.store.catalog_rows('PersonCfg')) if query.get('source')=='original' else set(map(str,people_table.get('localIds',[])))
                present={str(item.get('sourceId')) for item in items}
                if query.get('sourceProjectId') in (None,'','all',query.get('projectId')):
                    for ident in sorted(eligible & source_ids - present,key=int):
                        person=people_rows[ident];label=asset_name(person,'portrait')
                        items.append({'assetId':'person-selection:'+ident,'sourceId':int(ident),'kind':'portrait','name':label,
                                      'personIds':[int(ident)],'personNames':[label],'available':False,'canImport':False,
                                      'hasAffection':has_affection(person),'_selectionOnly':True})
            if query.get('clothingCategory'): items = [item for item in items if item.get('clothingCategory') == query['clothingCategory']]
            people = {}
            for item in items:
                for index, name in enumerate(item.get('personNames', [])):
                    ident = item.get('personIds', [])[index] if not result.get('allMods') and index < len(item.get('personIds', [])) else None
                    key = 'id:' + str(ident) if ident is not None else 'name:' + name
                    entry = people.setdefault(key, {**({'id': ident} if ident is not None else {}), 'name': name, 'count': 0}); entry['count'] += 1
            filters = sorted(people.values(), key=lambda row: (row['name'], row.get('id', -1)))
            locations = sorted({place for item in items for place in item.get('locations', [item.get('location', '其他')])}) if result['kind'] == 'background' else []
            if query.get('location') and result['kind'] == 'background':
                items = [item for item in items if query['location'] in item.get('locations', [item.get('location', '其他')])]
            if query.get('affection') in ('yes', 'no') and result['kind'] == 'portrait':
                items = [item for item in items if bool(item.get('hasAffection')) == (query['affection'] == 'yes')]
            q = str(query.get('q', '')).strip().casefold()
            if q: items = [item for item in items if search_matches(q,item['name'],item.get('relativePath', ''),*item.get('personNames', []),*item.get('searchNames', []),item.get('sourceProjectName', ''))]
            if str(query.get('personId', '')):
                person = str(query['personId'])
                items = [item for item in items if (not item.get('personIds') if person == 'unmarked' else person in map(str, item.get('personIds', [])))]
            if query.get('personName'): items = [item for item in items if query['personName'] in item.get('personNames', [])]
            if query.get('audioGroup') == '8' and result['kind'] == 'audio':
                items = [item for item in items if 8 in item.get('audioGroups', [])]
            if query.get('type') and result['kind'] in {'audio','item'}:
                items = [item for item in items if str(item.get('type')) == str(query['type']) or item.get('origin') == 'folder' and not item.get('audioTypeInferred')]
            # Filter first, then hide visually identical images without deleting files
            # or losing a duplicate's membership in a different category. An
            # unfiltered background set already deduplicated for the current
            # hash generation stays unique, so the second pass is skipped; any
            # filtered view or other kind keeps its exact old pass.
            unfiltered = result['kind'] == 'background' and not str(query.get('q', '')).strip() and all(
                query.get(key) in (None, '') for key in ('location', 'personId', 'personName', 'clothingCategory', 'audioGroup', 'type', 'socialOnly', 'affection'))
            if result['kind'] not in {'audio','portrait'} or query.get('variantMode') in {'portrait','expression'}:
                if unfiltered and result.get('_hashGeneration') == self._hash_generation:
                    pass
                else:
                    versions = {path: version for path, version in result.get('_files', [])} or None
                    items = self._deduplicate_backgrounds(items, versions)
            try: page, size = max(0, int(query.get('page', 0))), min(100, max(1, int(query.get('pageSize', 60))))
            except (TypeError, ValueError): self.error('素材页码无效。')
            total = len(items)
            page = min(page, max(0, (total - 1) // size))
            public = []
            for item in items[page * size:(page + 1) * size]:
                row = {key: value for key, value in item.items() if not key.startswith('_') and key not in {'resource', 'faceName', 'grade', 'cloth', 'face', 'index'}}
                if result['kind'] == 'item' and item.get('resource'):
                    row['imagePath'] = item['resource']
                row['previewUrl'] = '' if item.get('_selectionOnly') else '/api/asset-preview?' + urllib.parse.urlencode({'catalogKey': result['catalogKey'], 'assetId': item['assetId'], 'projectId': result['projectId'], 'revision': result['revision'], 'mediaRevision': item['mediaRevision']})
                public.append(row)
            return {key: value for key, value in result.items() if not key.startswith('_') and key != 'items'} | {'items': public, 'total': total, 'page': page, 'pageSize': size, 'personFilters': filters, 'locationFilters': locations, 'backgroundCache': self.hash_progress()}

    def preview(self, query):
        with self.store.lock:
            project = self.store.project(query.get('projectId'))
            catalog = self.cache.get(query.get('catalogKey'))
            if not catalog or catalog['projectId'] != project.id or catalog['revision'] != query.get('revision'):
                self.error('素材预览已过期，请重新打开素材目录。', 404)
            item = catalog['_itemById'].get(query.get('assetId'))
            if not item: self.error('找不到此素材。', 404)
            if query.get('mediaRevision') and query['mediaRevision'] != item['mediaRevision']:
                self.error('素材预览已更新，请刷新目录。', 409, 'conflict')
            source = item.get('_sourceProject')
            for selected in {p.id: p for p in [project, source] if p}.values():
                if self._preview_inputs(selected, catalog['kind']) != catalog['_previewInputs'].get(selected.id):
                    self.error('素材配置已变化，请刷新目录。', 409, 'conflict')
            if item.get('_path') in catalog['_mediaStamps'] and file_fingerprint(item['_path']) != catalog['_mediaStamps'][item['_path']]:
                self.error('素材文件已经变化，请刷新目录。', 409, 'conflict')
            if catalog['kind'] == 'portrait' and query.get('headshot') == '1':
                for resource in head_paths(item.get('_row', {}), item.get('previewGrade', 1)):
                    try: return self._resource(source or project, resource, 'portrait')['_path']
                    except self.api.ApiError: pass
            native_state = None
            if not item.get('_path') and item.get('_nativeRole') is not None:
                role, grade, cloth = item['_nativeRole'], item['previewGrade'] - 1, item['previewCloth']
                native_state = self.api.expression_status(self.store.game, role, grade, cloth, item.get('previewFace', 0), request=True)
                if native_state.get('status') == 'ready':
                    item.update(self._resource(project, f"portrait-cache/{role}-{grade}-{cloth}-{item.get('previewFace', 0)}.png", 'portrait'))
                elif native_state.get('status') == 'rendering':
                    self.error(native_state.get('message') or '正在读取此学段的人物立绘。', 425, 'preview_pending')
            if not item.get('_path') and not item.get('previewFace') and catalog['source'] == 'original' and not (item.get('_nativeRole') is not None and ':v:' in item['assetId']):
                if catalog['kind'] == 'portrait':
                    urls = item['_row'].get('url' if item['previewGrade'] == 1 else 'url2') or []
                    urls = urls if isinstance(urls, list) else [urls]
                    candidates = strings(urls[item['previewCloth']]) if item['previewCloth'] < len(urls) else []
                else:
                    candidates = [item['resource']] if catalog['kind'] == 'social' else strings(item['_row'].get('urls') if catalog['kind'] == 'cg' else item['_row'].get('icon') if catalog['kind'] in {'avatar','item'} else item['_row'].get('url'))
                for resource in candidates:
                    try:
                        item.update(self._resource(project, resource, catalog['kind'])); break
                    except self.api.ApiError: pass
                if not item.get('_path') and candidates and self.request_resources:
                    status = self.request_resources(catalog['kind'])
                    if status.get('status') == 'running': self.error(status.get('message') or '正在读取原版素材。', 425, 'preview_pending')
                    if status.get('status') == 'error': self.error(status.get('message') or '原版素材读取失败。', 503, 'preview_unavailable')
            if not item.get('_path') and native_state and native_state.get('status') == 'error':
                self.error(native_state.get('message') or '此学段的人物预览读取失败。', 503, 'preview_unavailable')
            if not item.get('_path'): self.error(item.get('message') or '此素材尚不能预览。', 404)
            self._check_path(item['_path'], item['_root'])
            if stamp(item['_path']) != item['_fingerprint']: self.error('素材文件已经变化，请刷新目录。', 409, 'conflict')
            if catalog['kind'] == 'portrait' and query.get('headshot') == '1':
                return crop_head(item['_path'], game_cache(self.store.game) / 'headshot-cache')
            if query.get('thumbnail') == '1' and catalog['kind'] in {'background', 'cg', 'item', 'avatar', 'social'}:
                thumbnail_path = item['_path']
            else:
                return item['_path']
        # Decode only after releasing the document lock so visible thumbnails
        # and ordinary editor requests can progress at the same time.
        return preview_image(thumbnail_path, auxiliary_cache(self.settings_path.parent, 'PreviewCache'))

    def _read_selected(self, item, kind):
        path = self._check_path(item['_path'], item['_root'])
        if stamp(path) != item['_fingerprint']: self.error('源素材已经变化，请刷新目录后重新选择。', 409, 'conflict')
        self._validate_file(path, kind, item['_root'])
        raw = path.read_bytes()
        if stamp(path) != item['_fingerprint']: self.error('读取时源素材发生变化，请重试。', 409, 'conflict')
        return raw

    def _copy_person(self, target, revision, item, payload):
        warnings_list = []
        persons = self._rows(target, 'PersonCfg', warnings_list)
        faces = self._rows(target, 'ModFaceCfg', warnings_list)
        if warnings_list: self.error(warnings_list[0], 422)
        occupied = {**self.store.catalog_rows('PersonCfg'), **{str(int(key) // 1000): {} for key in {**self.store.catalog_rows('ModFaceCfg'), **faces} if str(key).isdigit()}}
        ident = self.store.record_ids.allocate('PersonCfg', {**occupied, **persons})
        source = item['_row']
        person = {'id': ident, 'name': self.api.display_name(payload.get('name'), item['name']), 'gender': source.get('gender', 0),
                  'init': [0], 'birthday': copy.deepcopy(source.get('birthday', [])), 'nicknames': copy.deepcopy(source.get('nicknames', [])),
                  'url': [], 'url2': [], 'urlParm': copy.deepcopy(source.get('urlParm') or [0, 0, 1]),
                  'urlParm2': copy.deepcopy(source.get('urlParm2') or [0, 0, 1]), 'l2d': [], 'l2d2': [], 'l2dParm': [], 'l2dParm2': [],
                  'bubbleParm': copy.deepcopy(source.get('bubbleParm') or [900]), 'bubbleParm2': copy.deepcopy(source.get('bubbleParm2') or [900])}
        changes, copied, total = {}, {}, 0
        prefix = 'Textures/Role/studio_person_' + secrets.token_hex(8)
        for variant in item['_variants']:
            resource = str(variant['_path'])
            if resource not in copied:
                raw = self._read_selected(variant, 'portrait')
                if total >= IMPORT_SLICE:
                    # Flush finished texture files before reading more; the row is written last.
                    self.store.commit(target, changes, revision); revision = self.store.revision(target); changes, total = {}, 0
                converted, extension, _, _ = self.api.normalize_image(raw)
                total += len(converted)
                relative = prefix + '/' + str(len(copied)) + extension
                changes[relative] = converted
                copied[resource] = 'Mods\\' + target.package + '\\' + relative.replace('/', '\\')
            url = copied[resource]
            grade, cloth, face = variant['grade'], variant['cloth'], variant['face']
            field = 'url' if grade == 1 else 'url2'
            while len(person[field]) <= cloth: person[field].append('')
            if face == 0 or not person[field][cloth]: person[field][cloth] = url
            face_id = ident * 1000 + cloth * 100 + face
            face_row = faces.setdefault(str(face_id), {'id': face_id, 'name': variant['faceName'], 'icon': '', 'icon_xx': '', 'photobooth': None})
            face_row['icon_xx' if grade == 1 else 'icon'] = url
        if not copied: self.error('此人物没有可独立复制的静态立绘。', 422)
        persons[str(ident)] = person
        changes['Cfgs/zh-cn/PersonCfg.json'] = self.api.json_bytes(persons)
        changes['Cfgs/zh-cn/ModFaceCfg.json'] = self.api.json_bytes(faces)
        backup = self.store.commit(target, changes, revision)
        return {'id': ident, 'personId': ident, 'name': person['name'], 'gender': person['gender'], 'variantCount': len(item['_variants']),
                'backup': backup, 'revision': self.store.revision(target), 'warnings': ['已复制静态服装和表情。人物关系、剧情依赖及 Live2D 动画未迁移。']}

    def _copy_cg(self, target, revision, item, payload):
        warnings_list = []
        rows = self._rows(target, 'CGCfg', warnings_list)
        if warnings_list: self.error(warnings_list[0], 422)
        reserved = payload.get('reservedCgIds', [])
        if not isinstance(reserved, list) or len(reserved)>20000 or any(isinstance(value,bool) or not isinstance(value,int) or not self.api.valid_id(value) for value in reserved):
            self.error('CG 草稿编号列表无效。')
        occupied = {**rows, **{str(value):None for value in reserved}}
        ident = self.store.record_ids.allocate('CGCfg', occupied)
        changes, urls, total = {}, [], 0
        for index, variant in enumerate(item['_variants']):
            raw = self._read_selected(variant, 'cg')
            if total >= IMPORT_SLICE:
                self.store.commit(target, changes, revision); revision = self.store.revision(target); changes, total = {}, 0
            converted, extension, _, _ = self.api.normalize_image(raw)
            total += len(converted)
            relative = 'Textures/CG/studio_cg_' + secrets.token_hex(8) + extension
            changes[relative] = converted
            urls.append('Mods\\' + target.package + '\\' + relative.replace('/', '\\'))
        row = {'id': ident, 'name': self.api.display_name(payload.get('name'), item['name']), 'urls': urls, 'group': 3,
               'gender': item['_row'].get('gender', 0), 'comic': [], 'idx': 0, 'move': [], 'startTalks': []}
        rows[str(ident)] = row; changes['Cfgs/zh-cn/CGCfg.json'] = self.api.json_bytes(rows)
        self.add_association(changes, target, ident, item)
        backup = self.store.commit(target, changes, revision)
        return {'id': ident, 'name': row['name'], 'row': row, 'revision': self.store.revision(target), 'backup': backup}

    def add_association(self, changes, target, ident, item):
        supplied = item.get('personNames', [])
        if not isinstance(supplied, list) or len(supplied) > 32 or any(not isinstance(name, str) or len(name) > 100 for name in supplied): self.error('CG 相关人物标签无效。')
        names = list(dict.fromkeys(name.strip() for name in supplied if name.strip()))
        if not names: return
        persons = self._people(target, 'custom', [])
        selected = [int(key) for key, person in persons.items() if person.get('name') in names]
        relative = 'StudentAgeStudio/editor-state.json'
        state = self.api.read_json(self.api.safe_path(target.path, relative), {})
        if not isinstance(state, dict): self.error('模组编辑记录格式损坏。', 422)
        associations = state.setdefault('assetAssociations', {})
        if not isinstance(associations, dict) or not isinstance(associations.get('cg', {}), dict): self.error('素材关联记录格式损坏。', 422)
        associations.setdefault('cg', {})[str(ident)] = {'personIds': selected, 'personNames': names}
        changes[relative] = self.api.json_bytes(state)

    def delete_asset(self, payload):
        with self.store.lock, self.store.catalog_scope():
            target, revision, source, _, _, kind, _, _ = self._context(payload, writable=True)
            if source != 'custom': self.error('只能删除自定义素材。', 403)
            entries = self._entries(payload, refresh_media=False)
            item = next((row for row in entries['items'] if row['assetId'] == payload.get('assetId')), None)
            if not item: self.error('素材已变化，请刷新后重新选择。', 404)
            if payload.get('assetRevision') and payload['assetRevision'] != item.get('mediaRevision'):
                self.error('素材文件已变化，请刷新后重新选择。', 409)
            if item['origin'] == 'folder':
                # Keep a recoverable copy in an excluded folder on the same volume.
                path = self._check_path(item['_path'], item['_root'])
                path = Path(item['_path'])
                self._validate_file(path, kind, item['_root'])
                trash = Path(item['_root']) / '.StudentAgeStudioDeleted' / (str(time.time_ns()))
                trash.mkdir(parents=True, exist_ok=False)
                backup = trash / path.name
                path.rename(backup)
                result = {'backup': str(backup)}
            elif item['origin'] == 'imported':
                table = {'portrait':'PersonCfg', 'background':'BgCfg', 'cg':'CGCfg', 'audio':'AudioCfg','avatar':'KZoneAvatarCfg'}.get(kind)
                if not table: self.error('此素材请在对应编辑界面移除。')
                rows = self._rows(target, table, [])
                if str(item['sourceId']) not in rows: self.error('当前模组中没有这条素材。', 404)
                rows.pop(str(item['sourceId']))
                result = self.store.table_save({'projectId': target.id, 'revision': revision, 'name': table, 'scope': 'local', 'rows': rows})
            else: self.error('此素材不是当前模组的自定义内容。', 403)
            self.cache.clear()
            return {**result, 'ok': True, 'revision': self.store.revision(target)}

    @contextmanager
    def reserve_drafts(self, payload):
        reserved = payload.get('reservedIds', [])
        if not isinstance(reserved, list) or len(reserved) > 100000 or any(
                isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 2147483647 for v in reserved):
            self.error('草稿编号列表无效。')
        ids = self.store.record_ids
        previous = getattr(ids, 'draft_reserved', set())
        ids.draft_reserved = previous | set(reserved)
        try: yield
        finally: ids.draft_reserved = previous

    def import_snapshot(self, target, kind):
        names = ['PersonCfg', 'ModFaceCfg'] if kind == 'portrait' else [KINDS[kind]]
        return {name: self.api.read_json(target.path / 'Cfgs/zh-cn' / (name + '.json'), {}) for name in names}

    def import_delta(self, target, kind, before):
        delta = {}
        for name, after in self.import_snapshot(target, kind).items():
            old = before[name]
            changed = {k: row for k, row in after.items() if old.get(k) != row}
            if changed: delta[name] = {'before': {k: old.get(k) for k in changed}, 'after': changed}
        return delta

    def import_assets(self, payload):
        """Multi-selection import: folder media of one kind goes through the sliced batch writer; anything else imports one by one."""
        ids = payload.get('assetIds')
        if not isinstance(ids, list) or not ids or len(ids) > 2000 or any(not isinstance(v, str) for v in ids): self.error('请先勾选要导入的素材。')
        with self.store.lock, self.store.catalog_scope(), self.reserve_drafts(payload):
            target, revision, source, source_project, source_revision, kind, grade, cloth = self._context(payload, writable=True)
            catalog = self._entries(payload, refresh_media=False)
            wanted = [row for row in catalog['items'] if row['assetId'] in set(ids)]
            missing = set(ids) - {row['assetId'] for row in wanted}
            if missing: self.error('有 %d 项素材已不在目录中，请刷新后重新勾选。' % len(missing), 404)
            before = self.import_snapshot(target, kind)
            results, errors = [], []
            folder_items = [row for row in wanted if row.get('canImport') and (kind == 'avatar' or payload.get('library') is True and row['origin'] == 'folder' and kind in {'cg','background','audio'})]
            if folder_items:
                batch = self._import_rows(target, revision, kind, folder_items); revision = batch['revision']
                results.extend({'assetId': row['assetId'], **entry} for row, entry in zip(folder_items, batch['results']))
            for row in wanted:
                if row in folder_items: continue
                if not row.get('canImport'): errors.append({'assetId': row['assetId'], 'name': row['name'], 'error': row.get('message') or '此素材无法导入。'}); continue
                try:
                    single = self.import_asset({**payload, 'assetId': row['assetId'], 'assetRevision': row.get('mediaRevision'), 'revision': revision}, nested=True)
                    revision = single.get('revision', revision); results.append({'assetId': row['assetId'], 'id': single.get('id'), 'name': single.get('name', row['name']), 'imported': single.get('imported', True)})
                except self.api.ApiError as error:
                    errors.append({'assetId': row['assetId'], 'name': row['name'], 'error': error.message})
            imported = [r for r in results if r.get('imported')]
            self.cache.clear()
            return {'ok': True, 'kind': kind, 'imported': bool(imported), 'count': len(imported), 'skipped': len(results) - len(imported), 'errors': errors,
                    'results': results, 'revision': self.store.revision(target), 'projectId': target.id, 'previousRevision': payload.get('revision'),
                    'importDelta': self.import_delta(target, kind, before), 'warnings': [e['name'] + '：' + e['error'] for e in errors]}

    def import_asset(self, payload, nested=False):
        with (nullcontext() if nested else self.store.lock), (nullcontext() if nested else self.store.catalog_scope()), (nullcontext() if nested else self.reserve_drafts(payload)):
            target, revision, source, source_project, source_revision, kind, grade, cloth = self._context(payload, writable=True)
            catalog = self._entries(payload, refresh_media=False)
            item = next((row for row in catalog['items'] if row['assetId'] == payload.get('assetId')), None)
            if not item: self.error('所选素材已不在目录中，请刷新后重试。', 404)
            if source != 'original' and payload.get('assetRevision') and payload['assetRevision'] != item['mediaRevision']:
                self.error('素材图片或声音已更新，请刷新目录后重新选择。', 409, 'conflict')
            if source == 'original' or item['origin'] == 'imported' or source == 'mod' and source_project.id == target.id:
                return {'kind': kind, 'id': item['sourceId'], **({'personId': item['sourceId'], 'grade': item.get('previewGrade', grade), 'cloth': item.get('previewCloth', cloth)} if kind == 'portrait' else {}),
                        'name': item['name'], 'revision': revision, 'reference': source == 'original', 'imported': False, **({'url': item['resource']} if kind == 'social' else {})}
            if not item.get('canImport'): self.error(item.get('message') or '此素材无法导入。', 422)
            before = self.import_snapshot(target, kind)
            if kind == 'avatar' or payload.get('library') is True and item['origin'] == 'folder' and kind in {'cg','background','audio'}:
                batch = self._import_rows(target, revision, kind, [item]); result = {**batch, **batch['results'][0]}
            elif kind == 'portrait' and item['origin'] == 'mod': result = self._copy_person(target, revision, item, payload)
            elif kind == 'cg' and item['origin'] == 'mod': result = self._copy_cg(target, revision, item, payload)
            else:
                raw = self._read_selected(item, kind)
                data = {'projectId': target.id, 'revision': revision, 'kind': kind, 'name': self.api.display_name(payload.get('name'), item['name']),
                        'fileName': item.get('fileName', item['_path'].name), 'data': base64.b64encode(raw).decode('ascii')}
                if kind == 'social': result = self.store.import_field_image(data)
                elif kind == 'audio':
                    data['type'] = payload.get('type', item.get('type', 1)); result = self.store.audio_import(data)
                else:
                    if kind == 'portrait': data.update(grade=grade, cloth=0, faceId=0, gender=payload.get('gender', 2))
                    if kind == 'cg': data['_assetAssociation'] = {'personNames': item.get('personNames', [])}
                    result = self.store.import_image(data)
            if kind == 'portrait': result.update(grade=item.get('previewGrade', grade), cloth=item.get('previewCloth', 0))
            return {**result, 'kind': kind, 'name': result.get('name', item['name']), 'imported': True, 'reference': False, 'projectId': target.id, 'previousRevision': revision,
                    'importDelta': self.import_delta(target, kind, before)}

    def _import_rows(self, target, revision, kind, items):
        """One transaction for a folder, with stable IDs when importing it again."""
        table = KINDS[kind]
        warnings_list = []
        rows = self._rows(target, table, warnings_list)
        if warnings_list: self.error(warnings_list[0], 422)
        index_path = 'StudentAgeStudio/library-imports.json'
        index = self.api.read_json(self.api.safe_path(target.path, index_path), {})
        if not isinstance(index, dict): self.error('素材导入记录无法读取。', 422)
        changes, results, total, skipped, backup = {}, [], 0, 0, None
        # Large batches are written in slices: converted bytes never accumulate
        # beyond one slice in memory, and finished slices stay imported if a
        # later file fails. There is no fixed total limit.
        def flush():
            nonlocal changes, total, revision, backup
            if not changes: return
            changes['Cfgs/zh-cn/'+table+'.json'] = self.api.json_bytes(rows)
            changes[index_path] = self.api.json_bytes(index)
            backup = self.store.commit(target, changes, revision) or backup
            revision = self.store.revision(target)
            changes, total = {}, 0
        for item in items:
            if total >= IMPORT_SLICE: flush()
            raw = self._read_selected(item, kind)
            digest = hashlib.sha256(raw).hexdigest()
            key = hashlib.sha256((kind+'\0'+str(item['_path'].resolve())).encode()).hexdigest()
            prior = index.get(key, {})
            prior_id = str(prior.get('id', ''))
            if prior.get('sha256') == digest and prior_id in rows:
                try: present = self.store.project_asset(target, prior.get('url', '')).is_file()
                except self.api.ApiError: present = False
                if present:
                    skipped += 1;results.append({'id':int(prior_id),'name':item['name'],'imported':False});continue
            ident = int(prior_id) if prior_id in rows else self.store.record_ids.allocate(table, rows)
            name = self.api.display_name(item['name'], item['_path'].stem)
            if kind == 'audio':
                converted, extension = self.api.decode_audio({'fileName':item['_path'].name,'data':base64.b64encode(raw).decode('ascii')})
                directory = 'Audios'
            else:
                converted, extension, _, _ = self.api.normalize_image(raw)
                directory = {'background':'Textures/Bg','cg':'Textures/CG','avatar':'Textures/KZoneAvatar'}[kind]
            total += len(converted)
            relative = directory+'/library_'+key[:20]+extension
            url = 'Mods\\'+target.package+'\\'+relative.replace('/','\\')
            changes[relative] = converted
            if kind == 'cg': row = {'id':ident,'name':name,'urls':[url],'group':3,'gender':0,'comic':[],'idx':0,'move':[],'startTalks':[]}
            elif kind == 'background': row = {'id':ident,'name':name,'url':url,'audio':0,'cloth':[],'gaozhongCond':[],'gaozhongUrl':0}
            elif kind == 'avatar': row = {'id':ident,'name':name,'icon':url,'state':0,'type':0}
            else: row = {'id':ident,'name':name,'url':url,'type':item.get('type',1),'volumn':0,'group':[],'cond':[],'disable':0,'uiType':0}
            if prior_id in rows: row = {**rows[prior_id], **{k:v for k,v in row.items() if k in ('name','url','urls','icon')}}
            rows[str(ident)] = row
            index[key] = {'id':ident,'sha256':digest,'url':url,'source':str(item['_path']),'kind':kind}
            results.append({'id':ident,'name':name,'url':url,'row':row,'imported':True})
        imported = bool(changes) or backup is not None
        flush()
        self.cache.clear()
        return {'ok':True,'kind':kind,'imported':imported,'count':len(results)-skipped,'skipped':skipped,'results':results,'revision':self.store.revision(target),'backup':backup,'projectId':target.id}

    def import_folder(self, payload):
        with self.store.lock, self.store.catalog_scope(), self.reserve_drafts(payload):
            target, revision, _, _, _, kind, _, _ = self._context({**payload,'source':'custom'}, writable=True)
            if kind not in {'background','cg','audio','avatar'}: self.error('此类型不支持素材仓库批量导入。')
            settings = self.folders()
            if payload.get('settingsRevision') != settings['revision']: self.error('素材文件夹已变化，请重新打开仓库。',409,'conflict')
            folder = settings['folders'][kind]
            if not folder['exists']: self.error('请先选择可读取的素材库文件夹。',404)
            notices=[];items=self._scan(target,kind,folder,notices)
            before = self.import_snapshot(target, kind)
            result=self._import_rows(target,revision,kind,items)
            return {**result,'warnings':notices, 'previousRevision': revision,
                    'importDelta': self.import_delta(target, kind, before)}
