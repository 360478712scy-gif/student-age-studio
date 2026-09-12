"""Discover local StudentAge installations without executing games or altering their files."""
import copy
import ctypes
import json
import os
from pathlib import Path
from platform_support import replace_file
import re
import secrets
import sys
import threading
import time
import uuid

APP_ID = '1991040'


def user_path(path):
    value = str(path).strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in ('"', "'"): value = value[1:-1].strip()
    value = os.path.expandvars(value)
    value = re.sub(r'%([^%]+)%', lambda match: os.environ.get(match.group(1), match.group(0)), value)
    return Path(value).expanduser()


def windows_local_low():
    """Unity uses FOLDERID_LocalAppDataLow, which may be redirected off USERPROFILE."""
    if sys.platform != 'win32': return None
    pointer = ctypes.c_wchar_p()
    try:
        folder_id = ctypes.create_string_buffer(uuid.UUID('A520A1A4-1780-4FF6-BD18-167343C5AF16').bytes_le)
        shell = ctypes.windll.shell32.SHGetKnownFolderPath
        shell.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        shell.restype = ctypes.c_long
        if shell(folder_id, 0, None, ctypes.byref(pointer)) == 0 and pointer.value:
            return Path(pointer.value)
    except (AttributeError, OSError, ValueError):
        pass
    finally:
        if pointer:
            ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(pointer, ctypes.c_void_p))
    return None


def is_workshop_path(path, workshop=None):
    """Reject subscription storage before even listing or reading its contents."""
    try:
        original = Path(path).expanduser()
        for candidate in (original, original.resolve()):
            if any(part.casefold() == 'workshop' for part in candidate.parts): return True
            if workshop and candidate.is_relative_to(Path(workshop).expanduser().resolve()): return True
    except (OSError, RuntimeError, ValueError, TypeError):
        return True
    return False


def local_project_folder(path, workshop=None):
    try:
        path = Path(path)
        if is_workshop_path(path, workshop) or path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()): return False
        return path.is_dir() and ((path / 'manifest.json').is_file() or (path / 'Cfgs/zh-cn').is_dir())
    except (OSError, ValueError):
        return False


def local_mod_candidates(game=None):
    game = Path(game) if game else None
    drive = next((p for p in game.parents if p.name == 'drive_c'), None) if game else None
    roots = []
    if drive and sys.platform != 'win32':
        profiles = sorted((drive / 'users').glob('*/AppData/LocalLow/PakyiGame/StudentAge'))
        roots = [drive / 'users/crossover/AppData/LocalLow/PakyiGame/StudentAge/Mods']
        roots.extend(profile / 'Mods' for profile in profiles)
    else:
        known = windows_local_low()
        if known: roots.append(known / 'PakyiGame/StudentAge/Mods')
        if os.environ.get('LOCALAPPDATA'):
            roots.append(Path(os.environ['LOCALAPPDATA']).parent / 'LocalLow/PakyiGame/StudentAge/Mods')
        roots.append(Path(os.environ.get('USERPROFILE', str(Path.home()))) / 'AppData/LocalLow/PakyiGame/StudentAge/Mods')
    return list(dict.fromkeys(path.expanduser().resolve() for path in roots if not is_workshop_path(path)))


def preferred_mods_path(candidates):
    # Retain older environment-derived locations when they contain the user's projects.
    for root in candidates:
        try:
            if root.is_dir() and any(local_project_folder(p) for p in root.iterdir()): return root
        except OSError: pass
    return next((root for root in candidates if root.is_dir()), candidates[0])


def settings_path():
    from storage_paths import user_data_root
    return user_data_root() / 'game-location.json'


def read_vdf(path):
    try:
        content = Path(path).read_text(encoding='utf-8-sig', errors='replace')
        content = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*', lambda m: '' if m.group(0).startswith('//') else m.group(0), content)
        tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', content)
        root, stack, key = {}, [], None
        current = root
        for value, brace in tokens:
            if brace == '{':
                if key is None: return {}
                child = {}; current[key] = child; stack.append(current); current = child; key = None
            elif brace == '}':
                if not stack: return {}
                current = stack.pop(); key = None
            else:
                value = value.replace('\\\\', '\\').replace('\\"', '"')
                if key is None: key = value
                else: current[key] = value; key = None
        return root if not stack else {}
    except OSError:
        return {}


def valid_game(path):
    if not isinstance(path, (str, os.PathLike)) or not str(path).strip(): return None
    try:
        path = user_path(path).resolve()
        if is_workshop_path(path): return None
        if path.name.lower() == 'studentage.exe': path = path.parent
        return path if (path / 'StudentAge.exe').is_file() and (path / 'StudentAge_Data/Managed/Assembly-CSharp.dll').is_file() else None
    except (OSError, ValueError, RuntimeError):
        return None


def describe_game(path, source='扫描发现'):
    game = valid_game(path)
    if game is None: return None
    drive = next((p for p in game.parents if p.name == 'drive_c'), None)
    if drive and sys.platform != 'win32':
        label = 'CrossOver · ' + drive.parent.name
    else:
        label = game.parent.parent.parent.name if game.parent.name.lower() == 'common' else game.parent.name
    steamapps = next((p for p in game.parents if p.name.lower() == 'steamapps'), None)
    workshop = steamapps / 'workshop/content' / APP_ID if steamapps else game / 'Workshop'
    candidates = local_mod_candidates(game)
    return {'game': str(game), 'mods': str(preferred_mods_path(candidates)), 'modsCandidates': [str(p) for p in candidates],
            'extraMods': [], 'workshop': str(workshop), 'label': label or '学生时代', 'source': source}


def steam_roots():
    roots = []
    if os.name == 'nt':
        import winreg
        for hive, key, value in [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'), (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'), (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')]:
            try:
                with winreg.OpenKey(hive, key) as handle: roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError: pass
        for key in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
            if os.environ.get(key): roots.append(Path(os.environ[key]) / 'Steam')
    else:
        roots.append(Path.home() / 'Library/Application Support/Steam')
        bottles = Path.home() / 'Library/Application Support/CrossOver/Bottles'
        for drive in bottles.glob('*/drive_c'):
            roots.extend([drive / 'Program Files (x86)/Steam', drive / 'Program Files/Steam'])
    return roots


def quick_candidates(extra=()):
    seen = set()
    for item in extra:
        row = describe_game(item, '已保存或手动指定')
        if row and row['game'].casefold() not in seen:
            seen.add(row['game'].casefold()); yield row
    for steam in steam_roots():
        libraries = [steam]
        data = read_vdf(steam / 'steamapps/libraryfolders.vdf').get('libraryfolders', {})
        if isinstance(data, dict):
            for key, value in data.items():
                path = value.get('path') if isinstance(value, dict) else value if key.isdigit() else None
                if path: libraries.append(Path(path))
        for library in libraries:
            manifest = read_vdf(library / 'steamapps/appmanifest_1991040.acf').get('AppState', {})
            install = manifest.get('installdir', 'StudentAge') if isinstance(manifest, dict) else 'StudentAge'
            if '/' in install or '\\' in install or install in ('.', '..'): continue
            row = describe_game(library / 'steamapps/common' / install, 'Steam 游戏库')
            if row and row['game'].casefold() not in seen:
                seen.add(row['game'].casefold()); yield row


def search_roots():
    if os.name == 'nt':
        bits = ctypes.windll.kernel32.GetLogicalDrives()
        return [Path(chr(65 + n) + ':\\') for n in range(26) if bits & (1 << n) and ctypes.windll.kernel32.GetDriveTypeW(chr(65+n)+':\\') == 3]
    return [Path.home(), *[p for p in Path('/Volumes').glob('*') if p.is_dir()]]


class GameLocations:
    def __init__(self, path=None):
        self.path = Path(path) if path else settings_path()
        self.lock = threading.RLock(); self.cancel = threading.Event()
        self.results = []; self.active = None; self.status = 'idle'; self.checked = 0; self.message = ''
        try: settings = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError): settings = {}
        if not isinstance(settings, dict): settings = {}
        self.settings = settings
        saved = settings.get('game')
        if not isinstance(saved, str): saved = None
        self.results = list(quick_candidates([saved] if saved else []))
        self.results = [self._restore_mods(row) for row in self.results]
        saved_row = next((r for r in self.results if saved and r['game'] == str(Path(saved).resolve())), None)
        if saved_row or len(self.results) == 1: self.active = copy.deepcopy(saved_row or self.results[0])

    def state(self):
        with self.lock:
            return {'managed': True, 'active': copy.deepcopy(self.active), 'installations': copy.deepcopy(self.results), 'status': self.status, 'checked': self.checked, 'message': self.message}

    def _restore_mods(self, row):
        row = copy.deepcopy(row)
        games = self.settings.get('games', {})
        settings = games.get(row['game'], {}) if isinstance(games, dict) else {}
        if not settings and self.settings.get('game') == row['game']: settings = self.settings
        if isinstance(settings, dict):
            mods = settings.get('mods')
            if isinstance(mods, str) and mods.strip() and not is_workshop_path(mods, row['workshop']):
                row['mods'] = str(Path(mods).expanduser().resolve())
            extras = settings.get('extraMods', [])
            if isinstance(extras, list):
                row['extraMods'] = list(dict.fromkeys(str(Path(p).expanduser().resolve()) for p in extras
                    if isinstance(p, str) and p.strip() and not is_workshop_path(p, row['workshop'])))
        return row

    def _save(self, row):
        settings = copy.deepcopy(self.settings)
        games = settings.get('games')
        if not isinstance(games, dict): games = {}
        games[row['game']] = {'mods': row['mods'], 'extraMods': row.get('extraMods', [])}
        settings.update({'game': row['game'], 'games': games})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name('.location-' + secrets.token_hex(6) + '.tmp')
        try:
            temp.write_text(json.dumps(settings, ensure_ascii=False), encoding='utf-8'); replace_file(temp, self.path)
        finally: temp.unlink(missing_ok=True)
        self.settings = settings
        self.active = row
        self.results = [r for r in self.results if r['game'] != row['game']] + [copy.deepcopy(row)]

    def choose(self, path):
        row = describe_game(path, '手动选择')
        if row is None: raise ValueError('请选择包含 StudentAge.exe 和 StudentAge_Data 的游戏文件夹。')
        with self.lock:
            row = self._restore_mods(row)
            self._save(row)
        return row

    def choose_mods(self, path):
        if not self.active: raise ValueError('请先选择游戏目录。')
        if not isinstance(path, (str, os.PathLike)) or not str(path).strip(): raise ValueError('请选择自己的本地开发模组文件夹。')
        path = user_path(path)
        if is_workshop_path(path, self.active['workshop']): raise ValueError('订阅目录不能作为本地开发目录，请选择自己的本地开发模组。')
        if path.name.casefold() in ('manifest.json', 'modinfo.json'): path = path.parent
        path = path.resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
            next(path.iterdir(), None)
            probe = path / ('.studio-write-check-' + secrets.token_hex(8))
            try:
                with probe.open('xb') as stream: stream.write(b'')
            finally: probe.unlink(missing_ok=True)
        except OSError: raise ValueError('这个模组文件夹无法读写，请选择有写入权限的本地文件夹。')
        selected = str(path) if local_project_folder(path, self.active['workshop']) else None
        with self.lock:
            row = copy.deepcopy(self.active)
            if selected:
                row['extraMods'] = list(dict.fromkeys([*row.get('extraMods', []), selected]))
            else:
                row['mods'] = str(path)
            self._save(row)
        return row, selected

    def start(self, deep=False, roots=None):
        with self.lock:
            if self.status == 'running': return self.state()
            self.cancel.clear(); self.status='running'; self.checked=0; self.message='正在查找 Steam 游戏库…'
        threading.Thread(target=self._scan, args=(deep, roots), daemon=True).start()
        return self.state()

    def _scan(self, deep, roots):
        found = {}; exhausted = False
        def add(row):
            if row:
                row = self._restore_mods(row)
                found[row['game'].casefold()] = row
                with self.lock: self.results = list(found.values())
        try:
            with self.lock: extras = [self.active['game']] if self.active else []
            for row in quick_candidates(extras): add(row)
            if deep or not found:
                start=time.monotonic(); stack=list(roots if roots is not None else search_roots()); visited=set()
                excluded={'windows','$recycle.bin','system volume information','winsxs','node_modules','.git','__pycache__','cache','caches','temp','.trash','studentage_data','workshop'}
                while stack and not self.cancel.is_set():
                    directory=stack.pop()
                    if time.monotonic()-start>180 or self.checked>=250000: exhausted=True; break
                    try:
                        if is_workshop_path(directory): continue
                        if directory.is_symlink() or (hasattr(directory,'is_junction') and directory.is_junction()): continue
                        identity=str(directory.resolve()).casefold()
                        if identity in visited: continue
                        visited.add(identity)
                        with self.lock: self.checked+=1; self.message='正在扫描本机文件夹（已检查 '+str(self.checked)+' 个）…'
                        row=describe_game(directory)
                        if row: add(row); continue
                        with os.scandir(directory) as entries:
                            for entry in entries:
                                if entry.name.casefold() not in excluded and entry.is_dir(follow_symlinks=False): stack.append(Path(entry.path))
                    except (PermissionError, OSError, RuntimeError): continue
            with self.lock:
                self.status='cancelled' if self.cancel.is_set() else 'complete'
                self.message=('扫描已停止。' if self.cancel.is_set() else '本轮扫描已达到扫描上限，可手动选择游戏文件夹。' if exhausted else '扫描完成。')+'找到 '+str(len(found))+' 份游戏。'
        except Exception:
            with self.lock: self.status='error'; self.message='部分位置无法读取，请手动选择游戏文件夹。'
