import importlib.metadata as md
from pathlib import Path
import os,shutil,json,hashlib
root=Path(os.environ.get('STUDIO_BUILD_ROOT', str(Path(os.environ['LOCALAPPDATA'])/'StudentAgeStudioBuild')));package=root/os.environ.get('STUDIO_PACKAGE_NAME','StudentAgeStudio-Windows-beta1.0.3-release')
folder=package/'ThirdPartyNotices';folder.mkdir(exist_ok=True)
excluded={'playwright','pyee','greenlet','pip'}
if (package/'runtime-version.json').exists():excluded.update({'pywebview','pythonnet','clr_loader'})
for dist in md.distributions():
 name=dist.metadata['Name']
 if name.lower() in excluded:continue
 for item in dist.files or []:
  if any(word in Path(str(item)).name.lower() for word in ('license','copying','notice')) and str(item).lower().endswith(('.txt','.md','license','copying','notice')):
   path=Path(dist.locate_file(item))
   if path.is_file():
    dest=folder/name;dest.mkdir(exist_ok=True);shutil.copy2(path,dest/Path(item).name)
(folder/'components.json').write_text(json.dumps([{ 'name':d.metadata['Name'],'version':d.version,'homepage':d.metadata.get('Home-page','')} for d in md.distributions() if d.metadata['Name'].lower() not in excluded],indent=2),encoding='utf-8')
files=[p for p in package.rglob('*') if p.is_file() and p.relative_to(package).parts[0] != 'Cache']
# Data must be read from the user's own game; never include game cache, user projects, or test session credentials.
assert not any(p.name in ('asset-map.json','audio-map.json','catalog.json','workshop-catalog.json','game-catalog.json','condition-library.json','game-location.json','windows-ready.json') for p in files)
manifest={str(p.relative_to(package)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.name!='SHA256SUMS.json'}
(package/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({'files':len(manifest),'bytes':sum(p.stat().st_size for p in files)}))
