"""Stable runtime ABI 1 bootstrap. Kept in the installed client, never downloaded over itself."""
import ast
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sys
import tempfile

RUNTIME_ABI = 1
RESTART_EXIT = 42


def version_key(value):
    text=str(value).strip().removeprefix('v')
    if text.startswith('beta-'):text=text[5:]+'-beta.0'
    match=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)(?:\.(\d+))?)?',text)
    if not match:raise ValueError('无法识别的版本号：'+text)
    major,minor,patch,pre,n=match.groups()
    return (int(major),int(minor),int(patch),{'alpha':0,'beta':1,'rc':2,None:3}[pre],int(n or 0))


@contextmanager
def state_lock(root):
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.state.lock').open('a+b') as handle:
        if os.name=='nt':
            import msvcrt
            handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX)
        try:yield
        finally:
            if os.name=='nt':handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)


def updates_root():
    # Independent of an overlay's storage_paths module and of the selected asset cache.
    if os.environ.get('STUDIO_USER_DATA_ROOT'):
        return Path(os.environ['STUDIO_USER_DATA_ROOT']).expanduser().resolve()/'Updates'
    base = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local')) if os.name == 'nt' else Path.home()/'Library/Application Support'
    return base/'StudentAgeStudio/Updates'


def write_json(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.update-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):os.unlink(name)


def read_state(root=None):
    try:
        value = json.loads(((root or updates_root())/'active.json').read_text('utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):return {}


def version_dir(root, identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}', identifier):
        raise ValueError('无效的更新版本目录。')
    parent = (root/'versions').resolve();target = parent/identifier
    if target.is_symlink() or not target.resolve().is_relative_to(parent):raise ValueError('更新路径超出版本目录。')
    return target


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:return False
    if os.name == 'nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False
        code=ctypes.c_ulong();kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code));kernel.CloseHandle(ctypes.c_void_p(handle))
        return code.value==259
    try:os.kill(pid,0);return True
    except OSError:return False


def select_web(base, root=None):
    if os.environ.get('STUDIO_UPDATE_MANAGED')!='1':return Path(base).resolve()
    with state_lock(root or updates_root()):return _select_web(base,root)


def _select_web(base, root=None):
    base=Path(base).resolve();root=root or updates_root();state=read_state(root)
    os.environ.pop('STUDIO_ACTIVE_UPDATE',None)
    # Source previews do not execute downloaded code.
    if os.environ.get('STUDIO_UPDATE_MANAGED')!='1':return base
    if state.get('pending') and state.get('attempted') and not process_alive(state.get('pid')):
        state={'active':state.get('previous'),'notice':'上次更新未能完成启动，已恢复上一版本。'}
        write_json(root/'active.json',state)
    identifier=state.get('active')
    if not identifier:return base
    try:
        folder=version_dir(root,identifier)
        manifest=json.loads((folder/'update.json').read_text('utf-8'))
        version_file=base/'error_logs.py'
        if version_file.is_file():
            installed=next(ast.literal_eval(n.value) for n in ast.parse(version_file.read_text('utf-8')).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='APP_VERSION' for t in n.targets))
            if version_key(installed)>=version_key(manifest.get('version')):
                write_json(root/'active.json',{'notice':'已使用较新的内置版本。'});return base
        if manifest.get('runtimeAbi')!=RUNTIME_ABI or not (folder/'standalone/server.py').is_file():raise ValueError('不兼容的更新')
        if state.get('pending'):
            state.update(attempted=True,pid=os.getpid());write_json(root/'active.json',state)
        os.environ['STUDIO_ACTIVE_UPDATE']=identifier
        return folder/'standalone'
    except (OSError,ValueError):
        write_json(root/'active.json',{'notice':'更新文件不可用，已使用内置版本。'})
        return base


def mark_healthy(root=None):
    if os.environ.get('STUDIO_UPDATE_MANAGED')!='1':return
    with state_lock(root or updates_root()):return _mark_healthy(root)


def _mark_healthy(root=None):
    if os.environ.get('STUDIO_UPDATE_MANAGED')!='1':return
    root=root or updates_root();state=read_state(root)
    if state.get('active')==os.environ.get('STUDIO_ACTIVE_UPDATE') and state.get('pending'):
        state.update(pending=False,attempted=False);state.pop('pid',None);write_json(root/'active.json',state)


def rollback_failed_start(root=None):
    with state_lock(root or updates_root()):return _rollback_failed_start(root)


def _rollback_failed_start(root=None):
    root=root or updates_root();state=read_state(root)
    if os.environ.get('STUDIO_UPDATE_MANAGED')=='1' and state.get('pending') and state.get('active')==os.environ.get('STUDIO_ACTIVE_UPDATE'):
        write_json(root/'active.json',{'active':state.get('previous'),'notice':'新版本启动失败，已恢复上一版本。'})
        return True
    return False


def main():
    import runpy
    base=Path(__file__).resolve().parent
    os.environ['STUDIO_BASE_WEB']=str(base)
    web=select_web(base);sys.path.insert(0,str(web))
    sys.argv=[str(web/'server.py'),*sys.argv[1:]]
    try:runpy.run_path(sys.argv[0],run_name='__main__')
    except Exception:
        if rollback_failed_start():raise SystemExit(RESTART_EXIT)
        raise


if __name__=='__main__':main()
