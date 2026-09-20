"""Build an Apple Silicon application with its own relocatable Python runtime."""
from pathlib import Path
import ast
import importlib.metadata
import os
import plistlib
import re
import shutil
import subprocess

root = Path(__file__).resolve().parent.parent
app = Path(os.environ.get('STUDIO_APP_PATH', str(Path.home() / 'Applications/拾光工坊.app')))
if app.exists():
    raise SystemExit('目标已存在，请用 STUDIO_APP_PATH 指定新的应用路径。')
python_root = Path(os.environ['STUDIO_MAC_PYTHON_ROOT']).resolve()
dependencies = Path(os.environ['STUDIO_MAC_DEPENDENCIES']).resolve()
python = python_root / 'bin/python3.12'
if not python.is_file() or not (dependencies/'UnityPy').is_dir():
    raise SystemExit('Mac 构建运行环境或依赖不完整。')
version = next(ast.literal_eval(n.value) for n in ast.parse((root/'standalone/error_logs.py').read_text(encoding='utf-8')).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='APP_VERSION' for t in n.targets))
numeric = re.search(r'\d+\.\d+\.\d+',version).group()
contents = app/'Contents';resources=contents/'Resources';engine=resources/'standalone'
(contents/'MacOS').mkdir(parents=True);engine.mkdir(parents=True)
subprocess.run(['swiftc','-target','arm64-apple-macos14.0',str(root/'desktop/StudioApp.swift'),'-o',str(contents/'MacOS/StudentAgeStudio'),'-framework','AppKit','-framework','WebKit'],check=True)
for source in (root/'standalone').iterdir():
    if source.name != 'steamworks-runtime.json' and source.is_file() and source.suffix in ('.py','.js','.json','.html','.css','.png','.svg'):
        shutil.copy2(source,engine/source.name)
for notice in ('LICENSE','THIRD_PARTY_NOTICES.md'):shutil.copy2(root/notice,resources/notice)
ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store')
for name in ('ui-assets','native'):
    shutil.copytree(root/'standalone'/name,engine/name,ignore=ignore)
runtime=resources/'python';(runtime/'bin').mkdir(parents=True);(runtime/'lib').mkdir()
shutil.copy2(python,runtime/'bin/python3.12');(runtime/'bin/python3').symlink_to('python3.12')
shutil.copy2(python_root/'lib/libpython3.12.dylib',runtime/'lib/libpython3.12.dylib')
shutil.copytree(python_root/'lib/python3.12',runtime/'lib/python3.12',ignore=shutil.ignore_patterns('site-packages','__pycache__','*.pyc','test','tests','idlelib','tkinter','turtledemo','ensurepip'))
shutil.copytree(dependencies,runtime/'lib/python3.12/site-packages',ignore=ignore)
notices=resources/'ThirdPartyNotices';notices.mkdir()
for distribution in importlib.metadata.distributions(path=[str(dependencies)]):
    name=distribution.metadata.get('Name','unknown')
    for item in distribution.files or []:
        filename=Path(str(item)).name
        if any(word in filename.lower() for word in ('license','copying','notice')):
            origin=Path(distribution.locate_file(item))
            if origin.is_file():
                target=notices/name;target.mkdir(exist_ok=True);shutil.copy2(origin,target/filename)
# The copied runtime is independent of the developer's Python and user packages.
env={k:v for k,v in os.environ.items() if k not in ('PYTHONHOME','PYTHONPATH')};env['PYTHONNOUSERSITE']='1'
subprocess.run([str(runtime/'bin/python3'),'-B','-c','import ssl,sqlite3,ctypes,PIL,numpy,UnityPy,imageio_ffmpeg,fmod_toolkit,certifi; ssl.create_default_context().load_verify_locations(certifi.where()); print("MAC_RUNTIME_OK")'],env=env,check=True)
info={'CFBundleName':'拾光工坊','CFBundleDisplayName':'拾光工坊·模组编辑器-'+version,'CFBundleIconFile':'studio.icns','CFBundleIdentifier':'local.shiguang.workshop','CFBundleVersion':numeric,'CFBundleShortVersionString':numeric,'StudioVersion':version,'CFBundleExecutable':'StudentAgeStudio','CFBundlePackageType':'APPL','LSMinimumSystemVersion':'14.0','NSHighResolutionCapable':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True},'NSPrincipalClass':'NSApplication'}
shutil.copy2(root/'desktop/studio.icns',resources/'studio.icns')
with (contents/'Info.plist').open('wb') as f:plistlib.dump(info,f)
# Sign native helpers and extension modules before signing their enclosing app.
macho={b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'}
for path in sorted(contents.rglob('*')):
    if path.is_file() and not path.is_symlink():
        with path.open('rb') as f:header=f.read(4)
        if header in macho:subprocess.run(['codesign','--force','--sign','-',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
print(app)
