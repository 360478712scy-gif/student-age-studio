#!/usr/bin/env python3
"""Build a code-only release asset; never includes installed game art or user data."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'standalone'))
from app_updates import code_name, version_key, NOTICE_FILES
from update_bootstrap import RUNTIME_ABI


def build(root, output, version=None):
    root=Path(root);output=Path(output)
    current=next(ast.literal_eval(n.value) for n in ast.parse((root/'standalone/error_logs.py').read_text(encoding='utf-8')).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='APP_VERSION' for t in n.targets))
    if version is not None and version_key(version)!=version_key(current):raise ValueError('Tag 与 APP_VERSION 不一致。')
    files={p.relative_to(root).as_posix():p.read_bytes() for p in sorted((root/'standalone').iterdir()) if p.is_file() and not p.is_symlink() and code_name(p.relative_to(root).as_posix())}
    files.update({name:(root/name).read_bytes() for name in sorted(NOTICE_FILES)})
    manifest={'format':1,'version':current,'runtimeAbi':RUNTIME_ABI,'files':{n:hashlib.sha256(data).hexdigest() for n,data in files.items()}}
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in [*files.items(),('update.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True).encode())]:
            info=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,data)
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n', encoding='utf-8')
    return {'version':current,'files':len(files),'bytes':output.stat().st_size,'sha256':digest,'path':str(output)}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',default='release/student-age-studio-update.zip');p.add_argument('--version');a=p.parse_args()
    print(json.dumps(build(ROOT,a.out,a.version),ensure_ascii=False))
