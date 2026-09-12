"""Durable user-selected cache locations, independent of editor releases."""
import hashlib
from functools import lru_cache
import os
import sys
from pathlib import Path


def user_data_root():
    override = os.environ.get('STUDIO_USER_DATA_ROOT')
    if override: return Path(override).expanduser().resolve()
    base = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local')) if os.name == 'nt' else Path.home()/'Library/Application Support'
    # Retain the existing stable name: upgrades and renamed executables use it.
    return base/'StudentAgeStudio'


def installation_root():
    override = os.environ.get('STUDIO_INSTALL_ROOT')
    if override: return Path(override).expanduser().resolve()
    if getattr(sys, 'frozen', False):
        folder = Path(sys.executable).resolve().parent
        return folder.parent if folder.name.lower() == 'runtime' else folder
    return Path(__file__).resolve().parents[1]


def preference_path():
    return Path(os.environ.get('STUDIO_DISPLAY_SETTINGS') or user_data_root()/'display-settings.json')


@lru_cache(maxsize=8)
def saved_cache_path(settings):
    # A running editor keeps its current location. A changed setting applies on
    # the next launch, so active preview workers never split across two roots.
    from user_preferences import load
    value = load(settings).get('cachePath', '')
    return str(Path(value).expanduser().resolve()) if isinstance(value, str) and value.strip() else ''


def cache_root(fallback=None):
    override = os.environ.get('STUDIO_CACHE_ROOT')
    if override: return Path(override).expanduser().resolve()
    configured = saved_cache_path(str(preference_path()))
    if configured: return Path(configured)
    if os.name == 'nt': return installation_root()/'Cache'
    return Path(fallback) if fallback is not None else user_data_root()/'Cache'


def game_cache(game):
    game = Path(game).resolve()
    if os.name != 'nt' and not os.environ.get('STUDIO_CACHE_ROOT') and not saved_cache_path(str(preference_path())): return game/'StudentAgeStudio'
    key = hashlib.sha256(os.path.normcase(str(game)).encode()).hexdigest()[:20]
    return cache_root()/'Games'/key


def auxiliary_cache(settings_dir, name):
    return cache_root(Path(settings_dir))/name


def storage_info(game):
    return {'userData':str(user_data_root()), 'cache':str(cache_root()), 'gameCache':str(game_cache(game)), 'install':str(installation_root())}


def prepare_game_cache(game):
    """Reuse a prior cache without moving/deleting the user's old installation."""
    source, target = Path(game).resolve()/'StudentAgeStudio', game_cache(game)
    if source == target or saved_cache_path(str(preference_path())): return target
    target.mkdir(parents=True, exist_ok=True)
    marker = target/'.legacy-cache-imported'
    if marker.exists() or not source.is_dir(): return target
    import shutil
    import secrets
    from platform_support import lock_file, unlock_file
    with (target/'.migration.lock').open('a+b') as handle:
        lock_file(handle)
        try:
            if marker.exists(): return target
            for directory, folders, files in os.walk(source, followlinks=False):
                base = Path(directory)
                folders[:] = [n for n in folders if n not in ('Exports','Backups') and not (base/n).is_symlink() and not (hasattr(base/n, 'is_junction') and (base/n).is_junction())]
                for name in files:
                    origin = base/name
                    if origin.is_symlink() or name.endswith(('.tmp','.lock')): continue
                    dest = target/origin.relative_to(source)
                    if dest.exists(): continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    temp = dest.with_name(dest.name+'.'+secrets.token_hex(4)+'.tmp')
                    try:
                        shutil.copy2(origin,temp)
                        os.replace(temp,dest)
                    finally: temp.unlink(missing_ok=True)
            marker.write_text(str(source),encoding='utf-8')
        finally: unlock_file(handle)
    return target
