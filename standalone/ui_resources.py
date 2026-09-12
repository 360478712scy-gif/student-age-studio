"""Serve fixed workbench artwork without opening game bundles or UI prefabs."""
from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'ui-assets'

@lru_cache(maxsize=4)
def resource_manifest(kind):
    if kind not in ('phone', 'goal', 'cg', 'talk'):
        raise FileNotFoundError('未知的界面素材')
    folder = ROOT / kind
    data = json.loads((folder / 'manifest.json').read_text(encoding='utf8'))
    for name in data['files']:
        if Path(name).name != name or not (folder / name).is_file():
            raise FileNotFoundError('软件界面素材缺失，请重新完整解压软件包。')
    return data

def resource_path(kind, name):
    if name not in resource_manifest(kind)['files']:
        raise FileNotFoundError('未知的界面素材')
    return ROOT / kind / name
