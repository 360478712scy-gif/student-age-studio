"""Render the game's actual idle clip using Cubism Core, in the bounded portrait queue."""
import bisect
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib

from storage_paths import game_cache


def streamed_curves(data):
    raw=struct.pack('<'+'I'*len(data),*data);offset=0;curves={}
    while offset+8<=len(raw):
        time,count=struct.unpack_from('<fI',raw,offset);offset+=8
        if count>(len(raw)-offset)//20: raise ValueError('原版动画曲线损坏')
        for _ in range(count):
            index,*coeff=struct.unpack_from('<I4f',raw,offset);offset+=20
            if math.isfinite(time) and time>=0:curves.setdefault(index,[]).append([time,coeff])
    return curves


def sample_curve(keys,time):
    i=max(0,bisect.bisect_right([k[0] for k in keys],time)-1)
    t,coeff=keys[i];a,b,c,d=coeff;dt=max(0,time-t)
    return ((a*dt+b)*dt+c)*dt+d


def destination(game,role,grade,gender):
    return game_cache(Path(game))/'native-idle-v1'/f'{role}-{grade}-{gender}.webp'


def render(game,role,grade,gender):
    from native_portraits import Reader
    from native_core import Model
    from PIL import Image
    reader=Reader(game);p=reader.configs()['personcfg'][str(role)]
    name=p['l2d2' if grade else 'l2d'][1 if role==0 and gender==2 else 0]
    asset=reader.extract(name);source,root=reader.model_asset(name);params={}
    def visit(go,prefix=''):
        go=go.read();transform=None
        for c in go.m_Component:
            obj=c.component.deref()
            if obj.type.name=='Transform':transform=obj.read()
            elif obj.type.name=='MonoBehaviour':
                obj=obj.read()
                if obj.m_Script.read().m_ClassName=='CubismParameter':params[zlib.crc32(prefix.encode())]=go.m_Name
        if transform:
            for child in transform.m_Children:
                item=child.read().m_GameObject;n=item.read().m_Name;visit(item,prefix+'/'+n if prefix else n)
    visit(root)
    # L2DModel.Init -> PlayAnimation("idle") loads this named motion, not a guessed sine wave.
    clip=None
    for resource,obj in reader.environment(source).container.items():
        if resource.lower().endswith('/'+name.lower()+'/motions/idle.anim'):
            clip=obj.read_typetree();break
    if clip is None:
        for c in root.read().m_Component:
            if c.component.deref().type.name=='Animator':
                for pointer in c.component.read().m_Controller.read().m_AnimationClips:
                    tree=pointer.deref().read_typetree()
                    if tree.get('m_Name')=='idle':clip=tree;break
    if clip is None:raise ValueError('未找到此模型原版 idle 动画')
    muscle=clip['m_MuscleClip'];duration=muscle['m_StopTime']-muscle['m_StartTime']
    if not 0<duration<=30:raise ValueError('此动画时长尚不支持')
    data=muscle['m_Clip']['data'];curves=streamed_curves(data['m_StreamedClip']['data']);bindings=clip['m_ClipBindingConstant']['genericBindings'];dense=data['m_DenseClip'];count=data['m_StreamedClip']['curveCount'];constant=data.get('m_ConstantClip',{}).get('data',[])
    native=Model(Path(asset['moc']).read_bytes(),game);base={}
    for layer in ['Base Layer','Cloth','Hair','Item','Expression']:
        variants=asset['layers'].get(layer,{})
        if variants:base.update(variants.get('0',next(iter(variants.values()))))
    def parameters(t):
        values=dict(base)
        for i,binding in enumerate(bindings):
            parameter=params.get(binding['path'])
            if not parameter:continue
            if i<count:
                if curves.get(i):values[parameter]=sample_curve(curves[i],t)
            elif i<count+dense['m_CurveCount']:
                frame=max(0,min(dense['m_FrameCount']-1,int((t-dense['m_BeginTime'])*dense['m_SampleRate'])))
                values[parameter]=dense['m_SampleArray'][frame*dense['m_CurveCount']+i-count]
            elif i-count-dense['m_CurveCount']<len(constant):values[parameter]=constant[i-count-dense['m_CurveCount']]
        return values
    points=[v for r in native.evaluate(parameters(0)) if r['visible'] and r['opacity']>.01 for v in r['vertices']]
    x=min(v[0] for v in points);y=min(v[1] for v in points);w=(max(v[0] for v in points)-x)*1.08;h=(max(v[1] for v in points)-y)*1.08;bounds=[x-w*.04,y-h*.04,w,h]
    height=600;width=max(120,min(600,round(height*w/h)));fps=15;n=math.ceil(duration*fps);frames=[];raster=None
    if sys.platform=='win32':
        from portrait_raster import Raster
        raster=Raster(asset['textures'],bounds,width,height)
    target=destination(game,role,grade,gender);target.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='studio-idle-') as tmp:
        tmp=Path(tmp)
        for i in range(n):
            rows=native.evaluate(parameters(i/fps));png=tmp/'frame.png'
            if raster:raster.render(rows,png)
            else:
                scene=tmp/'frame.json';scene.write_text(json.dumps(dict(textures=asset['textures'],drawables=rows,bounds=bounds,width=width,height=height),separators=(',',':')))
                subprocess.run([str(Path(__file__).parent/'native/PortraitMetal'),str(scene),str(png)],check=True,capture_output=True,timeout=30)
            with Image.open(png) as image:frames.append(image.convert('RGBA'))
        temporary=target.with_suffix('.tmp.webp');frames[0].save(temporary,save_all=True,append_images=frames[1:],duration=round(1000/fps),loop=0,lossless=False,quality=90,method=3);os.replace(temporary,target)
    meta={'bounds':bounds,'model':name,'clip':clip['m_Name'],'duration':duration,'fps':fps,'frames':n,'parameters':list(parameters(0)),'source':str(source),'sourceStamp':[source.stat().st_size,source.stat().st_mtime_ns],'limitations':['未复刻 Unity 物理、随机眨眼和鼠标跟随；当前为原版 idle 曲线动态渲染']}
    target.with_suffix('.json').write_text(json.dumps(meta,ensure_ascii=False));return meta


def request(game,role,grade,gender):
    if type(role)is not int or role<0 or grade not in (0,1) or gender not in (1,2):raise ValueError('模型参数无效')
    target=destination(game,role,grade,gender)
    if target.is_file() and target.with_suffix('.json').is_file():
        m=json.loads(target.with_suffix('.json').read_text());source=Path(m['source'])
        if source.is_file() and [source.stat().st_size,source.stat().st_mtime_ns]==m['sourceStamp']:return {'status':'ready','frame':m,'url':'/api/model-idle-image?role='+str(role)+'&grade='+str(grade)+'&gender='+str(gender)}
    import portraits
    from platform_support import worker_command,process_options
    key=(str(game),'idle:'+target.stem)
    def work():
        p=subprocess.Popen(worker_command(Path(__file__),game)+['--role',str(role),'--grade',str(grade),'--gender',str(gender)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,**process_options())
        with portraits._guard:portraits._processes.add(p)
        try:
            try:_,error=p.communicate(timeout=600)
            except subprocess.TimeoutExpired:
                p.kill();p.communicate()
                raise ValueError('读取原版待机动画超过 10 分钟仍未完成，已中断；稍后会自动重试。')
            if p.returncode:raise ValueError(error[-500:])
        finally:
            if p.poll()is None:p.kill();p.wait()
            with portraits._guard:portraits._processes.discard(p)
    with portraits._guard:
        job=portraits._jobs.get(key)
        if job and job.done():
            # Release the finished slot before reporting, so a failure can be retried.
            portraits._jobs.pop(key,None);portraits._background.discard(key)
            try:job.result()
            except Exception as error:return {'status':'error','message':str(error)}
        if key not in portraits._jobs and not portraits._stopping.is_set() and len(portraits._jobs)<portraits._MAX_PENDING:portraits._jobs[key]=portraits._pool.submit(work)
    return {'status':'rendering','message':'正在读取原版待机动画，首次准备后会缓存复用…'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--game',required=True);parser.add_argument('--role',type=int,required=True);parser.add_argument('--grade',type=int,required=True);parser.add_argument('--gender',type=int,default=1)
    a=parser.parse_args();print(json.dumps(render(a.game,a.role,a.grade,a.gender),ensure_ascii=False))
