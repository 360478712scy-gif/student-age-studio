"""Copy mod content independently of bundled third-party editor runtimes."""
from pathlib import Path
import os
import errno
import shutil
import time


def excluded_entry(path, source):
    path, source = Path(path), Path(source)
    relative = path.relative_to(source).as_posix()
    if path.name in {'.git', '__pycache__', '.save.lock'} or relative == 'StudentAgeStudio/Backups':
        return True
    # Identify the actual tool directory, not an arbitrary user folder named _internal.
    tool = path.parent
    if '编辑器' in tool.name and any(tool.glob('*星云*.exe')) and (tool / '_internal').is_dir():
        return path.name == '_internal' or (path.suffix.lower() == '.exe' and '星云' in path.name) or path.name.lower() in {'debug.log', 'error.log'}
    return False


def stable_copy(source, destination):
    """Never publish bytes from a file that changed during the read."""
    for attempt in range(3):
        before = source.stat()
        try:
            # Metadata copying can fail on shared folders even when content is readable.
            shutil.copyfile(source, destination)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
                try:
                    os.utime(destination, ns=(after.st_atime_ns, after.st_mtime_ns))
                except OSError:
                    pass
                return
        except OSError as error:
            if getattr(error, 'winerror', None) not in (32, 33) or attempt == 2:
                raise
        time.sleep(.08)
    raise OSError(errno.EBUSY, '复制期间文件持续变化，请等待另一编辑器保存完成后重试', str(source))
