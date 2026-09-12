"""Read only requested native minigame guide/puzzle images, not whole atlases."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import threading
from storage_paths import game_cache
_lock=threading.Lock()

def image_file(game,resource):
    from character_rules import native_rules
    rules=native_rules(game)
    allowed={r['url'] for r in rules['GuideCfg'].values() if r.get('url')}
    allowed.update('puzzle/'+r['url'] for r in rules['PuzzleMinigameCfg'].values() if r.get('url'))
    if resource not in allowed: raise FileNotFoundError('找不到这个原版小游戏配图。')
    game=Path(game);folder=game/'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64'
    group=resource.split('/')[0]
    paths=list(folder.glob('textures_assets_'+group+'_*.bundle'))
    stamp=[(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in paths]
    key=hashlib.sha256(json.dumps([resource,stamp]).encode()).hexdigest()
    cache=game_cache(game)/'minigame-images-v1';target=cache/(key+'.png')
    with _lock:
        if target.is_file(): return target
        from extract_game_assets import UnityPy, bundle_members, connect_dependencies
        index={n.lower():p for p in folder.glob('*.bundle') for n in bundle_members(p)}
        for path in paths:
            env=UnityPy.load(str(path));matches=[o for n,o in env.container.items() if str(PurePosixPath(str(n).replace('\\','/')).with_suffix('')).lower().endswith('/textures/'+resource.lower())]
            if not matches:continue
            connect_dependencies(env,index)
            obj=matches[0].read()
            picture=obj.image
            cache.mkdir(parents=True,exist_ok=True);temp=target.with_suffix('.tmp');picture.save(temp,format='PNG');temp.replace(target);return target
    raise FileNotFoundError('原版小游戏配图文件尚不可用。')
