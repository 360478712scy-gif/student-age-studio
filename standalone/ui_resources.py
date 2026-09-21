"""Use installed artwork, or prepare it locally from the user's selected game."""
from functools import lru_cache
import json
from pathlib import Path
import shutil
import threading

ROOT = Path(__file__).resolve().parent / 'ui-assets'
KINDS = ('phone', 'goal', 'cg', 'talk')
LOCKS = {kind:threading.RLock() for kind in KINDS}


def _folder(kind, game):
    if kind not in KINDS:raise FileNotFoundError('未知的界面素材')
    bundled=ROOT/kind
    if (bundled/'manifest.json').is_file():return bundled
    if game is None:raise FileNotFoundError('请先在工坊设置中选择游戏目录。')
    from storage_paths import game_cache
    return game_cache(Path(game))/'editor-ui-v1'/kind


def _read(folder):
    data=json.loads((folder/'manifest.json').read_text(encoding='utf8'))
    for name in data['files']:
        if Path(name).name!=name or not (folder/name).is_file():raise FileNotFoundError('界面素材缺失。')
    return data


def _prepare(kind, game, folder):
    game=Path(game)
    if not (game/'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64').is_dir():
        raise FileNotFoundError('请先在工坊设置中选择有效的游戏目录。')
    folder.mkdir(parents=True,exist_ok=True)
    if kind=='goal':
        from game_goal_ui import resources
        resources(game,cache_dir=folder)
    elif kind=='phone':
        from game_phone_ui import resources
        resources(game,cache_dir=folder)
    elif kind=='talk':
        from game_talk_ui import resources
        resources(game,folder)
    else:
        from PIL import Image
        resource_manifest('phone',game);resource_manifest('goal',game)
        body=resource_path('phone','body.otf',game);goal=_folder('goal',game)/'title.ttf'
        shutil.copy2(body,folder/'body.otf');shutil.copy2(goal if goal.is_file() else body,folder/'name.otf')
        mask=Image.new('RGBA',(1,256));mask.putdata([(0,0,0,round(i/255*210)) for i in range(256)]);mask.save(folder/'mask.png')
        data={'files':['body.otf','name.otf','mask.png'],'reference':[2560,1440],'source':'Local game fonts and editor gradient','maskHeight':600,'body':{'bottom':100,'height':200,'side':100,'fontSize':50},'name':{'bottom':300,'height':57,'fontSize':40}}
        temp=folder/'manifest.json.tmp';temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8');temp.replace(folder/'manifest.json')


@lru_cache(maxsize=32)
def resource_manifest(kind, game=None):
    folder=_folder(kind,game)
    with LOCKS[kind]:
        try:return _read(folder)
        except (OSError,ValueError,KeyError):
            # Existing complete installs retain their bundled resources unchanged.
            if folder==ROOT/kind:raise
            from platform_support import lock_file, unlock_file
            folder.mkdir(parents=True,exist_ok=True)
            with (folder/'.prepare.lock').open('a+b') as handle:
                try:
                    lock_file(handle)
                except BlockingIOError as error:
                    from server import ApiError
                    raise ApiError('界面素材正在被另一个窗口准备，请稍后重试。', 409, 'ui_assets_busy') from error
                try:
                    try:return _read(folder)
                    except (OSError,ValueError,KeyError):
                        _prepare(kind,game,folder)
                        return _read(folder)
                finally:unlock_file(handle)


def resource_path(kind, name, game=None):
    if name not in resource_manifest(kind,game)['files']:raise FileNotFoundError('未知的界面素材')
    return _folder(kind,game)/name
