"""Export installed Unity Cubism data for local, real-time WebGL preview.

Only preparation runs in a worker; no image frames are rendered on the CPU.
"""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import zlib
from storage_paths import game_cache

VERSION = 2
_failures = {}


def folder(game, role, grade, gender):
    if type(role) is not int or role < 0 or grade not in (0, 1) or gender not in (1, 2):
        raise ValueError('模型参数无效')
    return game_cache(Path(game))/'live-model-v1'/f'{role}-{grade}-{gender}'


def physics_json(rig):
    kinds = ['X', 'Y', 'Angle']
    settings = []
    for i, row in enumerate(rig.get('SubRigs', [])):
        settings.append({
            'Id': f'PhysicsSetting{i}',
            'Input': [{'Source': {'Target':'Parameter','Id':v['SourceId']}, 'Weight':v['Weight'], 'Type':kinds[v['SourceComponent']], 'Reflect':bool(v['IsInverted'])} for v in row['Input']],
            'Output': [{'Destination': {'Target':'Parameter','Id':v['DestinationId']}, 'VertexIndex':v['ParticleIndex'], 'Scale':v['AngleScale'], 'Weight':v['Weight'], 'Type':kinds[v['SourceComponent']], 'Reflect':bool(v['IsInverted'])} for v in row['Output']],
            'Vertices': [{**{k:v[k] for k in ('Mobility','Delay','Acceleration','Radius')}, 'Position':{'X':v['InitialPosition']['x'],'Y':v['InitialPosition']['y']}} for v in row['Particles']],
            'Normalization': row['Normalization'],
        })
    return {'Version':3, 'Meta':{'PhysicsSettingCount':len(settings), 'TotalInputCount':sum(len(v['Input']) for v in settings), 'TotalOutputCount':sum(len(v['Output']) for v in settings), 'VertexCount':sum(len(v['Vertices']) for v in settings), 'EffectiveForces':{k:{'X':rig[k]['x'],'Y':rig[k]['y']} for k in ('Gravity','Wind')}, 'Fps':rig.get('Fps',0)}, 'PhysicsSettings':settings}


def export(game, role, grade, gender):
    from native_portraits import Reader
    from native_core import Model
    from model_idle import streamed_curves
    reader = Reader(game)
    cfg = reader.configs()
    person = cfg['personcfg'][str(role)]
    names = person.get('l2d2' if grade else 'l2d', [])
    if not names: raise ValueError('此学段没有 Live2D 模型')
    name = names[1 if role == 0 and gender == 2 and len(names)>1 else 0]
    asset = reader.extract(name)
    source, root = reader.model_asset(name)
    params, look, eyes, controllers = {}, [], [], {}
    clips = []

    def visit(pointer, prefix=''):
        go = pointer.read(); transform = None
        for component in go.m_Component:
            obj = component.component.deref()
            if obj.type.name == 'Transform': transform = obj.read()
            elif obj.type.name == 'Animator':
                clips.extend(obj.read().m_Controller.read().m_AnimationClips)
            elif obj.type.name == 'MonoBehaviour':
                cls = obj.read().m_Script.read().m_ClassName
                if cls == 'CubismParameter': params[zlib.crc32(prefix.encode())] = go.m_Name
                elif cls == 'CubismLookParameter':
                    t=obj.read_typetree();look.append({'id':go.m_Name,'axis':t['Axis'],'factor':t['Factor']})
                elif cls == 'CubismEyeBlinkParameter': eyes.append(go.m_Name)
                elif cls in ('CubismLookController','CubismEyeBlinkController','CubismAutoEyeBlinkInput','CubismPhysicsController'):
                    controllers[cls] = obj.read_typetree()
        if transform:
            for child in transform.m_Children:
                item=child.read().m_GameObject;n=item.read().m_Name
                visit(item, prefix+'/'+n if prefix else n)
    visit(root)
    clip = None
    for resource, obj in reader.environment(source).container.items():
        if resource.lower().endswith('/'+name.lower()+'/motions/idle.anim'):
            clip=obj.read_typetree();break
    if clip is None:
        for pointer in clips:
            candidate=pointer.deref().read_typetree()
            if candidate.get('m_Name')=='idle': clip=candidate;break
    if clip is None: raise ValueError('未找到原版待机动画')
    muscle=clip['m_MuscleClip'];duration=muscle['m_StopTime']-muscle['m_StartTime']
    if not math.isfinite(duration) or duration<=0: raise ValueError('原版动画时长无效')
    data=muscle['m_Clip']['data'];bindings=clip['m_ClipBindingConstant']['genericBindings']
    stream=streamed_curves(data['m_StreamedClip']['data'])
    animation={'duration':duration,'start':muscle['m_StartTime'],'bindings':[params.get(b['path']) for b in bindings], 'stream':stream,'streamCount':data['m_StreamedClip']['curveCount'],'dense':data['m_DenseClip'],'constant':data.get('m_ConstantClip',{}).get('data',[])}
    native=Model(Path(asset['moc']).read_bytes(),game)
    base={}
    for layer in ['Base Layer','Cloth','Hair','Item','Expression']:
        variants=asset['layers'].get(layer,{})
        if variants:base.update(variants.get('0',next(iter(variants.values()))))
    points=[p for row in native.evaluate(base) if row['visible'] and row['opacity']>.01 for p in row['vertices']]
    if not points: raise ValueError('模型没有可显示的图层')
    x0=min(p[0] for p in points);y0=min(p[1] for p in points)
    width=max(p[0] for p in points)-x0;height=max(p[1] for p in points)-y0
    bounds=[x0-width*.10,y0-height*.05,width*1.20,height*1.10]
    target=folder(game,role,grade,gender);target.mkdir(parents=True,exist_ok=True)
    files={'model.moc3':asset['moc'],**{f'texture-{i}.png':p for i,p in enumerate(asset['textures'])}}
    physics=controllers.get('CubismPhysicsController',{}).get('_rig')
    if physics:
        path=target/'physics.json';path.write_text(json.dumps(physics_json(physics)),encoding='utf-8');files['physics.json']=str(path)
    result={'version':VERSION,'name':name,'bounds':bounds,'layers':asset['layers'],'animation':animation,'look':look,'eyes':eyes,'lookController':controllers.get('CubismLookController',{}),'blink':controllers.get('CubismAutoEyeBlinkInput',{}),'blinkController':controllers.get('CubismEyeBlinkController',{}),'faces':{k:v.get(name,-1) for k,v in cfg.get('personfacecfg',{}).items()},'files':files,'source':str(source),'sourceStamp':[source.stat().st_size,source.stat().st_mtime_ns]}
    temporary=target/'profile.tmp';temporary.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');os.replace(temporary,target/'profile.json')
    return result


def _cached_resource(game, data, name):
    root=game_cache(Path(game)).resolve()
    path=Path(data['files'][name])
    if path.is_relative_to(root) and path.is_file() and path.resolve().is_relative_to(root): return path
    # Old profile files may contain absolute paths from a previous installation.
    parts=path.parts
    if 'native-models-v1' in parts:
        path=root/Path(*parts[parts.index('native-models-v1'):])
    else:
        # Physics belongs beside the profile, never at an arbitrary external path.
        return None
    return path if path.is_file() and path.resolve().is_relative_to(root) else None


def request(game,role,grade,gender,background=False):
    target=folder(game,role,grade,gender);meta=target/'profile.json'
    if meta.is_file():
        try:
            data=json.loads(meta.read_text(encoding='utf-8'));source=Path(data['source'])
            valid=data.get('version')==VERSION and source.is_file() and data['sourceStamp']==[source.stat().st_size,source.stat().st_mtime_ns]
            valid=valid and all((target/name).is_file() if name=='physics.json' else _cached_resource(game,data,name) is not None for name in data['files'])
        except (OSError,ValueError,KeyError,TypeError): valid=False
        if valid:
            import portraits
            with portraits._guard:
                key=(str(game),'live:'+target.name)
                job=portraits._jobs.get(key)
                if job and job.done(): portraits._jobs.pop(key,None)
                _failures.pop(key,None)
            return {'status':'ready','key':target.name,'cacheStamp':str(meta.stat().st_mtime_ns),'profile':{k:v for k,v in data.items() if k not in ('files','source','sourceStamp')},'files':list(data['files'])}
    import portraits
    from platform_support import worker_command,process_options
    key=(str(game),'live:'+target.name)
    def work():
        p=subprocess.Popen(worker_command(Path(__file__),game)+['--role',str(role),'--grade',str(grade),'--gender',str(gender)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,**process_options())
        with portraits._guard: portraits._processes.add(p)
        try:
            try:_,error=p.communicate(timeout=900)
            except subprocess.TimeoutExpired:
                p.kill();p.communicate()
                raise ValueError('读取原版模型超过 15 分钟仍未完成，已中断；稍后会自动重试。')
            if p.returncode: raise ValueError(error[-500:])
        finally:
            if p.poll() is None:p.kill();p.wait()
            with portraits._guard:portraits._processes.discard(p)
    with portraits._guard:
        job=portraits._jobs.get(key)
        if job and job.done():
            portraits._jobs.pop(key,None)
            try:job.result()
            except Exception as e:_failures[key]=(time.monotonic(),str(e))
        failure=_failures.get(key)
        if failure and time.monotonic()-failure[0]<3:return {'status':'error','message':failure[1]}
        # The single worker serves the editor page first; the warmer yields.
        yielding=background and any(k not in portraits._background and not j.done() for k,j in portraits._jobs.items())
        if key not in portraits._jobs and not portraits._stopping.is_set() and len(portraits._jobs)<portraits._MAX_PENDING and not yielding:
            portraits._jobs[key]=portraits._pool.submit(work)
            if background:portraits._background.add(key)
            else:portraits._background.discard(key)
        if yielding and key not in portraits._jobs:return {'status':'queued','message':'人物读取排队中，会自动继续…'}
    return {'status':'rendering','message':'正在读取原版模型与动态参数…'}


def resource(game,key,name):
    if not re.fullmatch(r'\d+-[01]-[12]',key):raise ValueError('模型编号无效')
    target=folder(game,*map(int,key.split('-')))
    profile=json.loads((target/'profile.json').read_text(encoding='utf-8'))
    if name not in profile['files']:raise ValueError('模型素材无效')
    path=(target/name) if name=='physics.json' else _cached_resource(game,profile,name)
    if path is None or not path.is_file():raise ValueError('模型缓存文件缺失，请重新读取模型。')
    if not path.resolve().is_relative_to(game_cache(Path(game)).resolve()):raise ValueError('模型素材越界')
    return path


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--game',required=True);parser.add_argument('--role',type=int,required=True);parser.add_argument('--grade',type=int,required=True);parser.add_argument('--gender',type=int,default=1)
    a=parser.parse_args();result=export(a.game,a.role,a.grade,a.gender);print(json.dumps({'model':result['name'],'ready':True}))
