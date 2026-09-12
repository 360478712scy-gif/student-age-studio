"""Normalize native portrait framing and queue original game expression rendering."""
from storage_paths import game_cache, auxiliary_cache
import json
import re
import time
from pathlib import Path
from PIL import Image
from platform_support import replace_file,worker_command,process_options


def normalize_portrait(path):
    """Use the default face's frame for the whole set, never fit each emotion separately."""
    default=path.with_name(path.stem.rsplit('-',1)[0]+'-0.png')
    if not default.is_file(): default=path
    output=path.parent/'framed';output.mkdir(exist_ok=True)
    target=output/path.name
    if target.exists() and target.stat().st_mtime_ns>=max(path.stat().st_mtime_ns,default.stat().st_mtime_ns):return target
    with Image.open(default).convert('RGBA') as base, Image.open(path).convert('RGBA') as selected:
        box=base.getchannel('A').point(lambda a:255 if a>10 else 0).getbbox()
        if not box:return path
        # Old previews came from differently sized inspector panels. Match the reference canvas.
        if selected.size!=base.size:selected=selected.resize(base.size,Image.Resampling.LANCZOS)
        selected=selected.crop(box)
        temp=target.with_suffix('.tmp')
        selected.save(temp,format='PNG');replace_file(temp,target)
    return target


import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='native-portrait')
_jobs={}
_failures={}
_RETRY_SECONDS=15
_MAX_PENDING=4
_STALL_SECONDS=600
_background=set()
_guard=threading.Lock()
_stopping=threading.Event()
_processes=set()

def portrait_key(role,grade,cloth,gender=1):
    return f'{role}{"-female" if role==0 and gender==2 else ""}-{grade}-{cloth}'


def native_cache_faces(game,role,grade,cloth,gender=1):
    root=game_cache(Path(game));name=portrait_key(role,grade,cloth,gender)
    try:
        metadata=json.loads((root/'native-portrait-status'/(name+'.json')).read_text(encoding='utf-8'))
        if metadata.get('source') not in ('macOS Metal + Cubism Core','Windows Raster + Cubism Core'):return []
        return sorted(f for f in metadata.get('available',[]) if isinstance(f,int) and 0<=f<=99 and (root/'portrait-cache'/f'{name}-{f}.png').is_file())
    except (OSError,ValueError,TypeError):return []

def foreground_pending():
    """True while a request made by the editor page, not the background warmer, is queued or running."""
    with _guard:return any(key not in _background and not job.done() for key,job in _jobs.items())


def expression_status(game,role,grade,cloth,face=0,request=False,gender=1,background=False):
    if not all(isinstance(v,int) and not isinstance(v,bool) for v in (role,grade,cloth,face)) or role<0 or grade not in (0,1) or not 0<=cloth<=9 or not 0<=face<=99:raise ValueError('人物表情参数无效')
    if type(gender) is not int or gender not in (1,2):raise ValueError('主角性别无效')
    home=game_cache(Path(game));root=home/'native-portrait-status';name=portrait_key(role,grade,cloth,gender)
    cached=native_cache_faces(game,role,grade,cloth,gender)
    metadata={}
    try:metadata=json.loads((root/(name+'.json')).read_text(encoding='utf-8'))
    except (OSError,ValueError):pass
    if metadata.get('source') not in ('macOS Metal + Cubism Core','Windows Raster + Cubism Core'):metadata={}
    key=(str(game),name)
    def run():
        command=worker_command(Path(__file__).parent/'native_portraits.py',game)+['--role',str(role),'--grade',str(grade),'--cloth',str(cloth),'--face',str(face),'--gender',str(gender)]
        with _guard:
            if _stopping.is_set():return
            options=process_options()
            if sys.platform=='win32':options['creationflags']|=subprocess.BELOW_NORMAL_PRIORITY_CLASS
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',**options)
            _processes.add(process)
        status_path=root/(name+'.json')
        def progress():
            try:return len(json.loads(status_path.read_text(encoding='utf-8')).get('available',[]))
            except (OSError,ValueError,TypeError):return -1
        last=progress();since=time.monotonic()
        try:
            # Every finished face is written to the status file. Only a worker
            # that makes no progress for a long time is treated as hung.
            while True:
                try:_,error=process.communicate(timeout=20);break
                except subprocess.TimeoutExpired:
                    current=progress()
                    if current!=last:last=current;since=time.monotonic()
                    elif time.monotonic()-since>_STALL_SECONDS:
                        process.kill();process.communicate()
                        raise RuntimeError('人物表情绘制长时间没有进展，已中断；稍后会自动继续。')
            if process.returncode and not _stopping.is_set():raise RuntimeError('原版模型读取失败：'+error[-300:])
        finally:
            if process.poll() is None:process.kill();process.wait()
            with _guard:_processes.discard(process)
    # A face the model does not define never becomes available; only re-render
    # when the set is incomplete, lacks frame metadata, or misses a defined face.
    known=metadata.get('faces') if isinstance(metadata.get('faces'),list) else None
    needed=not metadata.get('complete') or not metadata.get('frame') or known is None or (face in known and any(defined not in cached for defined in known))
    with _guard:
        # Reap all finished work, including panels no longer being polled.
        # Keep only bounded error text, not Future tracebacks and their object graphs.
        for done_key, done_job in list(_jobs.items()):
            if not done_job.done():continue
            error=RuntimeError('已取消人物读取') if done_job.cancelled() else done_job.exception()
            if error:_failures[done_key]=(time.monotonic(),str(error)[-600:])
            else:_failures.pop(done_key,None)
            _jobs.pop(done_key,None);_background.discard(done_key)
        while len(_failures)>128:_failures.pop(next(iter(_failures)))
        failed_at,error=_failures.get(key,(0,''))
        cooldown=bool(error) and time.monotonic()-failed_at<_RETRY_SECONDS
        job=_jobs.get(key)
        # The single renderer serves the editor page first; the warmer yields.
        yielding=background and job is None and any(k not in _background and not j.done() for k,j in _jobs.items())
        waiting=request and needed and job is None and not cooldown and (len(_jobs)>=_MAX_PENDING or yielding)
        if request and not _stopping.is_set() and needed and sys.platform in ('darwin','win32') and job is None and not cooldown and not waiting:
            job=_pool.submit(run);_jobs[key]=job;error='';_failures.pop(key,None)
            if background:_background.add(key)
            else:_background.discard(key)
        queue_size=len(_jobs)
    active=waiting or (job is not None and not job.done())
    status='ready' if face in cached else 'queued' if waiting else 'rendering' if active else 'unavailable'
    if error and face not in cached:status='error'
    message=error or ('人物读取排队中，会自动继续…' if waiting else '正在从游戏文件读取人物与全部表情…' if active else '这个人物没有对应的模型表情，可导入自定义表情图片。')
    return dict(metadata,available=cached,active=active,status=status,message='' if face in cached else message,queueSize=queue_size,retryAfter=_RETRY_SECONDS if cooldown else 1)


def shutdown():
    """Cancel only disposable preview work after the editor has saved and closed."""
    _stopping.set()
    with _guard:
        for process in list(_processes):
            if process.poll() is None:
                try:process.kill()
                except OSError:pass
    _pool.shutdown(wait=True,cancel_futures=True)
