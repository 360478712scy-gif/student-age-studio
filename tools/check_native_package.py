"""Smoke-test a built runtime using an isolated empty game and user-data directory."""
import argparse,json,os,subprocess,tempfile,time,urllib.request
from pathlib import Path


def check(package):
    package=Path(package).resolve()
    if package.suffix=='.app':
        resources=package/'Contents/Resources'
        command=[str(resources/'python/bin/python3'),'-B',str(resources/'standalone/update_bootstrap.py')]
    else:
        command=[str(package/'runtime/StudioEngine.exe'),'--server-only']
    with tempfile.TemporaryDirectory(prefix='studio-package-check-') as d:
        root=Path(d);ready=root/'ready.json'
        for n in ('Game','Mods','Workshop','Cache'):(root/n).mkdir()
        env={**os.environ,'STUDIO_UPDATE_MANAGED':'1','STUDIO_USER_DATA_ROOT':str(root/'User'),'STUDIO_CACHE_ROOT':str(root/'Cache'),'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'}
        env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None);env.pop('STUDIO_ACTIVE_WEB',None);env.pop('STUDIO_ACTIVE_UPDATE',None)
        command+=['--ready-file',str(ready),'--game',str(root/'Game'),'--mods',str(root/'Mods'),'--workshop',str(root/'Workshop')]
        with (root/'backend.log').open('w',encoding='utf8') as log:
            process=subprocess.Popen(command,env=env,stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+60
                while not ready.exists() and time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError((root/'backend.log').read_text(encoding='utf8'))
                    time.sleep(.1)
                if not ready.exists():raise RuntimeError('Packaged backend did not start')
                url=json.loads(ready.read_text(encoding='utf8'))['url'];origin,token=url.split('/#')
                def get(path,auth=True):
                    req=urllib.request.Request(origin+path,headers={'X-Studio-Token':token} if auth else {})
                    with urllib.request.urlopen(req,timeout=20) as response:return response.read()
                assert b'app-updates.js' in get('/')
                status=json.loads(get('/api/updates'));assert status['managed'] is True,status
                assert b'STUDIO_UPDATES' in get('/app-updates.js')
                print(json.dumps({'result':'NATIVE_RUNTIME_SMOKE_OK','version':status['currentVersion'],'managedUpdates':True,'nativeWindowInteraction':'not tested'},ensure_ascii=False))
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('package');check(p.parse_args().package)
