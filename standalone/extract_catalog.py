"""Read original configuration locally, without starting or patching StudentAge."""
from storage_paths import game_cache, auxiliary_cache
import argparse
import json
import os
from pathlib import Path
from platform_support import replace_file
from extract_game_assets import UnityPy


def extract(game):
    game = Path(game)
    schema = json.loads((Path(__file__).parent / 'catalog-schema.json').read_text(encoding='utf-8'))
    tables = {}; talks = {}; options = {}; sources = []
    bundles = sorted([p for root in (game / 'StudentAge_Data/StreamingAssets', game / 'DLC') for p in root.rglob('*cfgs*.bundle')], key=lambda p: ('dlc' in str(p).lower(), str(p)))
    for bundle in bundles:
        environment = UnityPy.load(str(bundle))
        count = 0
        for name, obj in environment.container.items():
            name = name.lower().replace('\\', '/')
            if '/cfgs/' not in name or not any('/'+lang+'/' in name for lang in ('zh-cn','dlc_zh-cn')) or not name.endswith('.json') or obj.type.name != 'TextAsset': continue
            table = next((key for key in schema['schemas'] if key.lower() == Path(name).stem), None)
            if not table: continue
            raw = obj.read().m_Script
            rows = json.loads(raw, strict=False)
            if isinstance(rows,list): rows = {str(row['id']): row for row in rows if isinstance(row,dict) and 'id' in row}
            if not isinstance(rows,dict): continue
            if table == 'TalkCfg': talks.update(rows)
            elif table == 'OptionCfg': options.update(rows)
            else: tables.setdefault(table,{}).update(rows)
            count += 1
        if count: sources.append(bundle.name)
    if not tables.get('PersonCfg'): raise RuntimeError('未能读取游戏人物配置，请检查游戏文件完整性。')
    schema.update(tables=tables, baseTalkIds=sorted(talks), language='zh-cn', source='Local installed game bundles', sourceBundles=sources)
    root = game_cache(game); root.mkdir(parents=True,exist_ok=True)
    target = root / 'game-catalog.json'; temp = root / '.catalog-reading.tmp'
    temp.write_text(json.dumps(schema,ensure_ascii=False),encoding='utf-8'); replace_file(temp,target)
    # Dialogue bodies stay out of the catalog; events pull the lines they reach from this store.
    from original_dialogue import write as write_dialogue
    write_dialogue(game, talks, options)
    return {'tables':len(tables),'characters':len(tables['PersonCfg']),'talks':len(talks),'options':len(options)}

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--game',required=True)
    print(json.dumps(extract(p.parse_args().game)),flush=True)
