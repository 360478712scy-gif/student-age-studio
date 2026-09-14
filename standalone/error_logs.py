"""Bounded, local diagnostics. Never let a failed log hide the original error."""
from datetime import datetime, timezone
import os
import json
from pathlib import Path
import platform
import re
import secrets
import threading
import traceback

from game_locator import settings_path
from platform_support import lock_file, unlock_file

APP_VERSION = '1.3.7-beta.4'

def display_version(value):
    return {'1.3.7-beta.2': '1.3.7.1', '1.3.7-beta.3': '1.3.7.2', '1.3.7-beta.4': '1.3.7.3'}.get(str(value).removeprefix('v'), value)

KEEP = 20
_lock = threading.RLock()
_filename = re.compile(r'error-\d{8}T\d{12}Z-[0-9a-f]{12}\.log\Z')


def redact(text, private=()):
    text = str(text)
    for value in private:
        if value:
            text = text.replace(str(value), '[已隐藏]')
    # Session tokens also occur in media URLs and browser stack traces.
    text = re.sub(r'(https?://[^\s?#\"\'<>]+)[?#][^\s\"\'<>]*', r'\1[参数已隐藏]', text)
    text = re.sub(r'(?i)((?:token|authorization|password|api[_-]?key)\s*[=:]\s*)[^\s,;]+', r'\1[已隐藏]', text)
    return text


class ErrorLogs:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('STUDIO_ERROR_LOG_ROOT') or settings_path().parent / 'ErrorLogs').expanduser().resolve()

    def _files(self):
        return sorted(p for p in self.root.iterdir() if _filename.fullmatch(p.name) and p.is_file() and not p.is_symlink())

    def settings(self):
        try:
            value = json.loads((self.root / 'settings.json').read_text(encoding='utf-8'))
            return {'autoCleanup': value.get('autoCleanup') is not False}
        except (OSError, ValueError, AttributeError):
            return {'autoCleanup': True}

    def configure(self, payload):
        value = payload.get('autoCleanup')
        if type(value) is not bool:
            raise ValueError('请选择是否自动清理错误日志。')
        from server import atomic_write, json_bytes
        with _lock:
            self.root.mkdir(parents=True, exist_ok=True)
            with (self.root / '.writer.lock').open('a+b') as guard:
                lock_file(guard)
                try:
                    atomic_write(self.root / 'settings.json', json_bytes({'autoCleanup':value}))
                    if value: self._prune()
                finally: unlock_file(guard)
        return self.status()

    def _prune(self):
        for path in self._files()[:-KEEP]:
            path.unlink()

    def status(self):
        # Do not create files just because the settings panel was opened.
        try:
            count = len(self._files())
        except OSError:
            count = 0
        return {'path': str(self.root), 'count': count, 'limit': KEEP, **self.settings()}

    def write(self, error=None, *, operation='内部操作', private=(), detail=None):
        try:
            now = datetime.now(timezone.utc)
            name = 'error-' + now.strftime('%Y%m%dT%H%M%S%fZ-') + secrets.token_hex(6) + '.log'
            diagnostic = (''.join(traceback.format_exception(type(error), error, error.__traceback__))
                          if error is not None else str(detail or '未知错误'))
            text = '\n'.join([
                '拾光工坊 · 学生时代模组编辑器 · 错误日志', '软件版本：' + APP_VERSION,
                '时间（UTC）：' + now.isoformat(), '系统：' + platform.platform(),
                'Python：' + platform.python_version(), '操作：' + str(operation), '',
                '错误详情 / 堆栈：', diagnostic,
                '\n日志不包含请求正文、完整模组数据或本地会话令牌。',
            ])
            text = redact(text, private)
            with _lock:
                self.root.mkdir(parents=True, exist_ok=True)
                # Multiple open app versions share this directory and quota.
                with (self.root / '.writer.lock').open('a+b') as guard:
                    lock_file(guard)
                    try:
                        with (self.root / name).open('x', encoding='utf-8') as output:
                            output.write(text)
                        if self.settings()['autoCleanup']: self._prune()
                    finally:
                        unlock_file(guard)
            return name
        except Exception:
            return None

    def response(self, error, message, code, operation, private=()):
        name = self.write(error, operation=operation, private=private)
        suffix = (' 错误日志已生成，可在“工坊设置 → 错误日志”查看。' if name else
                  ' 错误日志未能写入，请检查软件数据目录的写入权限或剩余空间。')
        return {'error': message + suffix, 'code': code, 'errorLog': name}
