"""Complete, independent mod snapshots; separate from save transaction recovery."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import threading
import time
import uuid
from contextlib import contextmanager

from game_locator import settings_path
from platform_support import lock_file, unlock_file
from mod_copy import excluded_entry, stable_copy

MARKER = '.student-age-backup.json'
FORMAT = 'student-age-studio-backup-v1'
_LOCK = threading.RLock()


class ModBackups:
    def __init__(self, store, api, root=None):
        self.store, self.api = store, api
        self.root = Path(root or os.environ.get('STUDIO_BACKUP_ROOT') or settings_path().parent / 'ModBackups').expanduser().resolve()

    @contextmanager
    def locked(self):
        with _LOCK:
            self.root.mkdir(parents=True, exist_ok=True)
            with (self.root / '.backup.lock').open('a+b') as stream:
                lock_file(stream)
                try:
                    yield
                finally:
                    unlock_file(stream)

    def excluded(self, path):
        path = Path(path).resolve()
        return self.api.inside(path, self.root) or any((p / MARKER).is_file() for p in (path, *path.parents))

    def settings(self):
        config = self.api.read_json(self.root / 'settings.json', {})
        if not isinstance(config, dict):
            raise self.api.ApiError('备份设置无法读取，请检查备份文件夹。')
        return {'path': str(self.root), 'autoCleanup': config.get('autoCleanup', True) is not False, 'limit': 5}

    def entries(self, folder):
        result = []
        if not folder.is_dir():
            return result
        for path in folder.iterdir():
            if path.name.startswith('.') or path.is_symlink() or not path.is_dir():
                continue
            try:
                data = self.api.read_json(path / MARKER, {})
                if data.get('format') == FORMAT and data.get('complete') is True and data.get('id') == path.name and isinstance(data.get('createdNs'), int):
                    result.append((path, data))
            except (OSError, ValueError, AttributeError, self.api.ApiError):
                continue
        return sorted(result, key=lambda row: (row[1]['createdNs'], row[0].name), reverse=True)

    def folder(self, project):
        key = hashlib.sha256(str(project.path).encode()).hexdigest()[:24]
        # Reuse the group after a title change, so the retention limit stays per mod.
        existing = sorted(p.name for p in self.root.glob('*--' + key) if p.is_dir() and not p.is_symlink())
        legacy = self.api.safe_path(self.root, key)
        if legacy.is_dir():
            return legacy
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', project.name)[:60].strip(' .') or '模组'
        return self.api.safe_path(self.root, existing[0] if existing else name + '--' + key)

    def status(self, project_id=None):
        with self.locked():
            state = self.settings()
            if project_id:
                project = self.store.project(project_id)
                state['projectPath'] = str(self.folder(project))
                state['backups'] = [dict(data, path=str(path), modPath=str(path / 'mod')) for path, data in self.entries(self.folder(project))]
            return state

    def prune(self, folder):
        removed = 0
        for path, _ in self.entries(folder)[5:]:
            # Only our completed snapshots are eligible, never arbitrary folders.
            shutil.rmtree(path)
            removed += 1
        return removed

    def configure(self, payload):
        enabled = payload.get('autoCleanup')
        if not isinstance(enabled, bool):
            raise self.api.ApiError('请选择是否自动清理旧备份。')
        with self.locked():
            # Read first: do not silently overwrite malformed existing settings.
            self.settings()
            self.api.atomic_write(self.root / 'settings.json', self.api.json_bytes({'autoCleanup': enabled}))
            removed = 0
            if enabled:
                for folder in self.root.iterdir():
                    if re.fullmatch(r'(?:.+--)?[0-9a-f]{24}', folder.name) and folder.is_dir() and not folder.is_symlink():
                        removed += self.prune(folder)
            return dict(self.settings(), removed=removed)

    def copy_mod(self, source, target):
        def copy_dir(directory, destination, ancestors=()):
            resolved = directory.resolve()
            if resolved in ancestors or not self.api.inside(resolved, source):
                raise self.api.ApiError('模组中包含循环或指向模组外部的文件链接，无法制作独立备份。')
            destination.mkdir()
            for child in directory.iterdir():
                relative = child.relative_to(source).as_posix()
                if excluded_entry(child, source) or self.api.inside(child, self.root):
                    continue
                if not self.api.inside(child, source):
                    raise self.api.ApiError('模组文件指向外部位置，无法备份：' + relative)
                output = destination / child.name
                if child.is_dir():
                    copy_dir(child, output, (*ancestors, resolved))
                elif child.is_file():
                    stable_copy(child, output)
                else:
                    raise self.api.ApiError('无法读取需要备份的模组文件：' + relative)
        copy_dir(source, target)

    def create(self, payload):
        kind, request_id = payload.get('kind', 'manual'), payload.get('requestId')
        if kind not in {'automatic', 'manual'} or not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', request_id):
            raise self.api.ApiError('备份请求无效，请重试。')
        with self.store.lock, self.locked():
            project = self.store.project(payload.get('projectId'), writable=True)
            folder = self.folder(project)
            for path, data in self.entries(folder):
                if data.get('requestId') == request_id:
                    return dict(data, path=str(path), modPath=str(path / 'mod'))
            config = self.settings()
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime('%Y-%m-%d_%H-%M-%S') + '-' + ('自动' if kind == 'automatic' else '手动') + '-' + uuid.uuid4().hex[:12]
            pending, target = folder / ('.pending-' + stamp), folder / stamp
            data = {'format': FORMAT, 'id': stamp, 'complete': True, 'kind': kind, 'requestId': request_id,
                    'createdNs': time.time_ns(), 'createdAt': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'projectId': project.id, 'name': project.name, 'source': str(project.path)}
            try:
                pending.mkdir()
                lock_path = self.api.safe_path(project.path, 'StudentAgeStudio/.save.lock')
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                with lock_path.open('a+b') as stream:
                    try:
                        lock_file(stream, blocking=False)
                    except (BlockingIOError, PermissionError):
                        raise self.api.ApiError('另一工作台正在保存这个模组。可创建独立副本后继续编辑。', 409, 'project_busy')
                    try:
                        self.copy_mod(project.path, pending / 'mod')
                    finally:
                        unlock_file(stream)
                self.api.atomic_write(pending / MARKER, self.api.json_bytes(data))
                (pending / '备份说明.txt').write_text('模组：' + project.name + '\n时间：' + data['createdAt'] + '\n类型：' + ('开始编辑时自动备份' if kind == 'automatic' else '手动备份') + '\n\nmod 文件夹内是完整模组。需要恢复时，关闭工作台，把 mod 文件夹复制到本地 Mods 目录并重新命名，再打开工作台。\n', encoding='utf-8')
                pending.rename(target)
            except Exception:
                if pending.exists():
                    shutil.rmtree(pending)
                raise
            warning = None
            if config['autoCleanup']:
                try:
                    self.prune(folder)
                except OSError:
                    warning = '备份已完成，但旧备份未能全部清理，请检查备份文件夹权限。'
            return dict(data, path=str(target), modPath=str(target / 'mod'), warning=warning)
