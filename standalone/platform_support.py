"""Small OS boundary for local locking, workers, and revealing exported files."""
import os
import errno
import stat as statmod
import subprocess
import sys
import threading
import time
from pathlib import Path
if os.name == 'nt':
    import msvcrt
else:
    import fcntl

_metadata_api = None
# Windows CreateFileW+GetFileInformationByHandleEx per call is ~10x a stat
# under Defender. Coalesce duplicate checks within one UI request: same
# (dev, ino, size, mtime) hit reuses the ChangeTime for a short TTL.
# Output tuple format is unchanged, so cache validation stays identical.
_fp_cache = {}
_fp_lock = threading.Lock()
_FP_TTL_NS = 750_000_000


def file_fingerprint(path):
    path = Path(path)
    stat, entry = path.stat(), path.lstat()
    # Directories only need mtime granularity for folder-watch checks.
    # Skipping the NTFS ChangeTime handle here saves one kernel open per dir.
    if statmod.S_ISDIR(entry.st_mode):
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns,
                stat.st_mtime_ns, entry.st_ino, entry.st_mode)
    if sys.platform == 'win32':
        key = (stat.st_dev, stat.st_ino)
        now = time.monotonic_ns()
        with _fp_lock:
            hit = _fp_cache.get(key)
            if (hit is not None and hit[0] == stat.st_size
                    and hit[1] == stat.st_mtime_ns and now - hit[3] < _FP_TTL_NS):
                return (stat.st_dev, stat.st_ino, stat.st_size,
                        stat.st_mtime_ns, hit[2], entry.st_ino, entry.st_mode)
        # Python 3.12's Windows st_ctime is the creation time. Use NTFS's
        # ChangeTime so same-size edits that restore mtime still invalidate.
        # https://learn.microsoft.com/windows/win32/api/winbase/ns-winbase-file_basic_info
        import ctypes
        from ctypes import wintypes
        global _metadata_api
        if _metadata_api is None:
            class BasicInfo(ctypes.Structure):
                _fields_ = [('created', ctypes.c_longlong), ('accessed', ctypes.c_longlong),
                            ('written', ctypes.c_longlong), ('changed', ctypes.c_longlong), ('attributes', wintypes.DWORD)]
            library = ctypes.WinDLL('kernel32', use_last_error=True)
            library.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            library.CreateFileW.restype = wintypes.HANDLE
            library.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            library.GetFileInformationByHandleEx.restype = wintypes.BOOL
            library.CloseHandle.argtypes = [wintypes.HANDLE]
            _metadata_api = library, BasicInfo
        library, BasicInfo = _metadata_api
        handle = library.CreateFileW(str(path), 0x80, 7, None, 3, 0, None)
        # Unusual file systems can decline basic metadata: safely bypass caching.
        changed = time.monotonic_ns()
        if handle not in (None, ctypes.c_void_p(-1).value):
            try:
                info = BasicInfo()
                if library.GetFileInformationByHandleEx(handle, 0, ctypes.byref(info), ctypes.sizeof(info)) and info.changed:
                    changed = info.changed
            finally:
                library.CloseHandle(handle)
        with _fp_lock:
            _fp_cache[key] = (stat.st_size, stat.st_mtime_ns, changed, now)
            if len(_fp_cache) > 8192:
                _fp_cache.clear()
    else:
        changed = stat.st_ctime_ns
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, changed, entry.st_ino, entry.st_mode)


def lock_file(stream, blocking=True):
    if os.name != 'nt':
        return fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b'\0'); stream.flush()
    while True:
        stream.seek(0)
        try:
            return msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK): raise
            if not blocking:
                raise BlockingIOError('Another editor holds this file') from error
            time.sleep(.05)


def unlock_file(stream):
    if os.name == 'nt':
        stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def worker_command(script, game):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--extract', Path(script).stem, '--game', str(game)]
    return [sys.executable, str(script), '--game', str(game)]


def process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def reveal_file(path):
    if os.name == 'nt':
        subprocess.Popen(['explorer.exe', '/select,', str(Path(path).resolve())], **process_options())
    elif sys.platform == 'darwin':
        subprocess.run(['open', '-R', str(path)], check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(['xdg-open', str(Path(path).parent)])


def replace_file(source, destination):
    """Windows readers/antivirus may briefly hold a file without delete sharing."""
    deadline = time.monotonic() + 5
    while True:
        try:
            return os.replace(source, destination)
        except OSError as error:
            if os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32, 33) or time.monotonic() >= deadline:
                raise
            time.sleep(.025)


def open_directory(path):
    path = str(Path(path).resolve())
    if os.name == 'nt':
        subprocess.Popen(['explorer.exe', path], **process_options())
    elif sys.platform == 'darwin':
        subprocess.run(['open', path], check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(['xdg-open', path])
