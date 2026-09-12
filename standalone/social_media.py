"""Read the complete TMP emoji texture, never the thumbnail of a sliced sprite."""
from storage_paths import game_cache, auxiliary_cache
from pathlib import Path
import json
import os
import threading

_lock=threading.Lock()
_HINT='textures_assets__97f9f51cbf6ffb1283f143bc8432e9b9.bundle'

def emoji_atlas(game):
    game=Path(game)
    cache=game_cache(game) / 'social-media-v1'
    target=cache/'tmoji.png'; meta=cache/'tmoji.json'
    with _lock:
        if target.is_file() and meta.is_file():
            try:
                saved=json.loads(meta.read_text(encoding='utf8'));source=game/saved['source'];stat=source.stat()
                if [stat.st_size,stat.st_mtime_ns]==saved['stamp']:return target
            except (OSError,ValueError,KeyError,TypeError):pass
        from extract_game_assets import UnityPy
        bundles=[]
        for folder in (game/'StudentAge_Data/StreamingAssets',game/'DLC'):
            bundles.extend(folder.rglob('textures_assets_*.bundle'))
        for source in sorted(bundles,key=lambda p:(p.name!=_HINT,str(p))):
            env=UnityPy.load(str(source))
            for name,ptr in env.container.items():
                if name.lower().replace('\\','/')!='assets/res/textures/icon/tmoji.png':continue
                obj=ptr.deref() if hasattr(ptr,'deref') else ptr
                # Unity exposes slices and their parent under the same filename.
                if obj.type.name!='Texture2D':continue
                image=obj.parse_as_object().image
                if image.size!=(504,1224):continue
                cache.mkdir(parents=True,exist_ok=True)
                temp=cache/'tmoji.tmp';image.save(temp,format='PNG');os.replace(temp,target)
                stat=source.stat();temp=cache/'tmoji-meta.tmp';temp.write_text(json.dumps({'source':str(source.relative_to(game)),'stamp':[stat.st_size,stat.st_mtime_ns]}),encoding='utf8');os.replace(temp,meta)
                return target
        raise FileNotFoundError('游戏表情图集未读取到。请检查游戏位置。')
