"""Small native reference tables used only when opening character tools."""
import json
import threading
from pathlib import Path

_lock = threading.RLock()
_cached = {}
TABLES = ('PersonalityTypeCfg', 'ScoreRankCfg', 'GradeCfg', 'ItemTypeCfg', 'MinigameCfg', 'MinigameActionCfg', 'KZoneFontCfg', 'GuideCfg', 'PuzzleMinigameCfg')


def native_rules(game):
    game = Path(game)
    paths = sorted((game/'StudentAge_Data/StreamingAssets').rglob('*cfgs*.bundle')) + sorted((game/'DLC').rglob('*cfgs*.bundle'))
    stamp = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
    with _lock:
        previous = _cached.get(str(game))
        if previous and previous[0] == stamp:
            return previous[1]
        result = {t: {} for t in TABLES}
        if paths:
            from extract_game_assets import UnityPy
            lookup = {t.lower(): t for t in TABLES}
            for path in paths:
                env = UnityPy.load(str(path))
                for name, obj in env.container.items():
                    low = name.lower()
                    table = lookup.get(Path(low).stem)
                    if not table or obj.type.name != 'TextAsset' or not any('/'+lang+'/' in low for lang in ('zh-cn', 'dlc_zh-cn')):
                        continue
                    rows = json.loads(obj.read().m_Script, strict=False)
                    if isinstance(rows, list): rows = {str(r['id']): r for r in rows}
                    result[table].update(rows)
        _cached[str(game)] = (stamp, result)
        return result


def references(store, project):
    import copy
    result = copy.deepcopy(native_rules(store.game))
    for name in result:
        result[name].update(store.catalog_rows(name))
        result[name].update(store.social.local(project,name))
    return result
