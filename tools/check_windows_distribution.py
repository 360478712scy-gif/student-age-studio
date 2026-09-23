"""Verify an extracted Windows client before Workshop upload."""
import argparse
import hashlib
import json
from pathlib import Path


def check(package):
    root=Path(package).resolve()
    manifest=json.loads((root/'SHA256SUMS.json').read_text(encoding='utf-8'))
    required={'拾光工坊.exe','runtime/StudioEngine.exe','runtime/_internal/standalone/search-pinyin.js','runtime/_internal/standalone/server.py'}
    if not required.issubset(manifest):
        raise ValueError('Distribution manifest omits required startup files')
    for name,digest in manifest.items():
        path=root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Invalid distribution path: '+name)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('Missing or changed distribution file: '+name)
    print(json.dumps({'result':'DISTRIBUTION_OK','files':len(manifest)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('package')
    check(parser.parse_args().package)
