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
            if old.get('stamp')==[list(s) for s in stamp] and old.get('version')==4:return old['tables']
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
        stage.write_text(json.dumps({'version':4,'stamp':stamp,'tables':tables},ensure_ascii=False),'utf-8');replace_file(stage,cache)
        return tables

def original_rows(game,name):
    paths=sorted((Path(game)/'StudentAge_Data/StreamingAssets').rglob('*cfgs*.bundle'))+sorted((Path(game)/'DLC').rglob('*cfgs*.bundle'))
    if not paths:return {}
    stamp=tuple((str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in paths)
    return _read(str(game),stamp).get(name,{})



def love_issues(name, row):
    """Native assumptions surfaced as acknowledgeable save warnings, not a gate."""
    if name == 'LoveVindicateRateCfg':
        import math
        for key in ('favorParms', 'attrParms'):
            values = row.get(key)
            if not isinstance(values, list) or len(values) != 5 or any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values):
                yield key + ' 需要五个有限数值，否则原版可能无法计算表白成功率。'
            elif values[1] < 0 or values[3] <= 0 or values[2] + values[4] <= 0 or values[2] + values[4] == 1:
                yield key + ' 的对数参数可能无效，请检查系数、偏移和底数。'
    elif name == 'GiftEvtCfg':
        npc, talks, types = row.get('npc', []), row.get('talkId', []), row.get('type', [])
        if not all(isinstance(v, list) for v in (npc, talks, types)):
            yield '收礼人、剧情入口和赠送方式应为列表。'
        elif len(npc) != len(talks) or len(types) > len(npc) or any(not isinstance(v, list) or not 1 <= len(v) <= 2 for v in talks):
            yield '每位收礼人需要一组剧情入口；一项为通用入口，两项分别为男、女主角入口。缺省赠送方式会消耗礼物。'
