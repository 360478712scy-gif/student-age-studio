"""Native table contracts for the visual gameplay editors."""
import uuid
import json
import threading
from functools import lru_cache
from pathlib import Path
from storage_paths import game_cache
_SCHEMA=json.loads(Path(__file__).with_name('catalog-schema.json').read_text('utf-8'))['schemas']
NAMES=tuple(n for n,s in _SCHEMA.items() if s.get('allowIncomplete'))
LOOKUPS=tuple(n for n in ('NegotiationSkillCfg','NegotiationBuffCfg') if n not in NAMES)
@lru_cache(maxsize=1)
def schemas():
    data=json.loads(Path(__file__).with_name('catalog-schema.json').read_text('utf-8'))['schemas']
    return {n:data[n] for n in (*NAMES,*LOOKUPS)}
_lock=threading.RLock()
@lru_cache(maxsize=4)
def _read(game,stamp):
    cache=game_cache(Path(game))/'gameplay-catalog.json'
    with _lock:
        try:
            old=json.loads(cache.read_text('utf-8'))
            if old.get('stamp')==[list(s) for s in stamp] and old.get('version')==2:return old['tables']
        except (OSError,ValueError,KeyError):pass
        from extract_game_assets import UnityPy
        tables={n:{} for n in (*NAMES,*LOOKUPS)}
        by_stem={n.lower():n for n in tables}
        for path,_,_ in stamp:
            env=UnityPy.load(path)
            for name,obj in env.container.items():
                lower=name.lower().replace('\\','/')
                table=by_stem.get(Path(lower).stem)
                if not table or not any('/'+lang+'/' in lower for lang in ('zh-cn','dlc_zh-cn')) or obj.type.name!='TextAsset':continue
                rows=json.loads(obj.read().m_Script,strict=False)
                if isinstance(rows,list):rows={str(r['id']):r for r in rows if isinstance(r,dict) and 'id' in r}
                if isinstance(rows,dict):tables[table].update(rows)
        from platform_support import replace_file
        cache.parent.mkdir(parents=True,exist_ok=True);stage=cache.with_name(cache.name+'.'+uuid.uuid4().hex+'.tmp')
        stage.write_text(json.dumps({'version':2,'stamp':stamp,'tables':tables},ensure_ascii=False),'utf-8');replace_file(stage,cache)
        return tables

def original_rows(game,name):
    paths=sorted((Path(game)/'StudentAge_Data/StreamingAssets').rglob('*cfgs*.bundle'))+sorted((Path(game)/'DLC').rglob('*cfgs*.bundle'))
    if not paths:return {}
    stamp=tuple((str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in paths)
    return _read(str(game),stamp).get(name,{})

