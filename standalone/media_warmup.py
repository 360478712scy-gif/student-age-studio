"""One bounded, incremental media warmer independent of the visible editor page."""
import copy
import json
import os
from pathlib import Path
import threading
import time

from storage_paths import auxiliary_cache, game_cache
from headshots import preview_image

IMAGES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tga'}
# One item gets this many attempts in a row before the rest is cached; after everything
# else is done the deferred items automatically get RETRY_TRIES more (only the parts that
# are still missing are touched), then they are given up until their source changes.
MAX_TRIES = 5
RETRY_TRIES = 1
MEDIA = IMAGES | {'.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac', '.mp4', '.webm', '.moc3'}


class MediaWarmup:
    def __init__(self, server):
        self.server = server
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.thread = None
        self.checkpoints = {}
        self.process = None
        self.state = {'status': 'idle', 'percent': 0, 'done': 0, 'total': 0, 'warnings': [], 'abandoned': []}
        self.attempts = None

    def get(self):
        with self.lock: return copy.deepcopy(self.state)

    def update(self, **values):
        with self.lock: self.state.update(values)

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                if self.state['status'] != 'running':
                    # Explicit retry bypasses the automatic failure cooldown.
                    for saved in self.checkpoints.values():
                        if saved.get('warnings'):saved['retryAt']=0
                    # A manual retry also gives the abandoned items a fresh start.
                    self.attempts={}
                    try: self.attempts_path().unlink(missing_ok=True)
                    except (OSError, AttributeError): pass
                    self.update(status='running',phase='检查全部素材',percent=0);self.wake.set()
                return self.get()
            self.update(status='running', phase='检查全部素材', percent=0)
            self.thread = threading.Thread(target=self.loop, daemon=True, name='all-media-cache')
            self.thread.start()
        return self.get()

    # ---- Failure policy: try an item MAX_TRIES times, move on, retry the deferred items once
    # (RETRY_TRIES) after everything else, then give the item up until its source changes (or a manual retry). ----
    def attempts_path(self):
        return game_cache(self.server.store.game)/'warmup-attempts-v1.json'

    def load_attempts(self):
        if self.attempts is None:
            try: data=json.loads(self.attempts_path().read_text())
            except (OSError, ValueError): data={}
            self.attempts=data if isinstance(data, dict) else {}
        return self.attempts

    @staticmethod
    def _index_write(api, path, data):
        # Recomputable warmup indexes skip fsync; same eventual bytes.
        try: api.atomic_write(path, data, fsync=False)
        except TypeError: api.atomic_write(path, data)

    def save_attempts(self, store):
        try: self._index_write(store.asset_catalog.api, self.attempts_path(), store.asset_catalog.api.json_bytes(self.load_attempts()))
        except OSError: pass

    def abandoned(self, key, signature):
        record=self.load_attempts().get(key)
        return record if isinstance(record, dict) and record.get('gaveUp') and record.get('signature')==signature else None

    def attempt(self, store, key, signature, work, tries=MAX_TRIES):
        """Run work() up to `tries` times. Returns (ok, message). Success clears the record."""
        attempts=self.load_attempts()
        record=attempts.get(key) if isinstance(attempts.get(key), dict) and attempts.get(key, {}).get('signature')==signature else {'signature': signature, 'count': 0}
        message=''
        for n in range(tries):
            if self.stop.is_set(): return False, '已停止'
            try:
                work()
                if key in attempts: attempts.pop(key, None); self.save_attempts(store)
                return True, ''
            except Exception as error:
                message=str(error) or '缓存失败'
                record['count']=record.get('count', 0)+1; record['message']=message
                attempts[key]=record; self.save_attempts(store)
                # A stalled worker already waited a long time: defer it right away instead of stalling five times.
                if '长时间没有进展' in message: break
                if n+1<tries: self.stop.wait(min(10, 2*(n+1)))
        return False, message

    def give_up(self, store, key, signature, message):
        attempts=self.load_attempts()
        attempts[key]={'signature': signature, 'count': attempts.get(key, {}).get('count', 0) if isinstance(attempts.get(key), dict) else 0, 'message': message, 'gaveUp': True, 'at': time.time()}
        self.save_attempts(store)

    def request_scan(self):
        # A picker asks for change detection, never invalidates existing media.
        if self.thread and self.thread.is_alive(): self.wake.set()

    def close(self):
        self.stop.set(); self.wake.set();self.update(status="cancelled")
        with self.lock:
            if self.process and self.process.poll() is None: self.process.terminate()

    def loop(self):
        while not self.stop.is_set():
            self.wake.clear()
            try: self.scan()
            except Exception as error:
                self.update(status='error', phase='部分素材缓存未完成', warnings=[str(error)])
            self.wake.wait(30)

    def files(self, roots, excluded):
        found = {}
        # Reuse resolved paths within this scan. Exclusions must compare real
        # paths: an ancestor alias can give the same directory another spelling.
        _cache = {}
        def _resolved(p):
            try:
                key = os.path.normcase(os.path.abspath(p))
            except (OSError, ValueError):
                key = str(p)
            hit = _cache.get(key)
            if hit is not None:
                return hit
            try:
                value = Path(p).resolve()
            except (OSError, ValueError):
                value = Path(p)
            if len(_cache) < 32768:
                _cache[key] = value
            return value
        excluded_resolved = {_resolved(item) for item in excluded}
        def _is_excluded(p):
            return _resolved(p) in excluded_resolved
        for root in roots:
            if not root.is_dir() or root.is_symlink() or _is_excluded(root): continue
            for directory, dirs, files in os.walk(root, followlinks=False):
                if self.stop.is_set(): return found
                base = Path(directory)
                dirs[:] = [n for n in dirs if not n.startswith('.') and n not in {'Backups','ModBackups','Exports','node_modules','__pycache__'}
                           and not (base/n).is_symlink() and not (hasattr(base/n,'is_junction') and (base/n).is_junction()) and not _is_excluded(base/n)]
                for name in files:
                    p = base/name
                    if p.suffix.lower() not in MEDIA or p.is_symlink(): continue
                    try:
                        s = p.stat(); found[str(_resolved(p))] = [s.st_size, s.st_mtime_ns, s.st_ctime_ns]
                    except OSError: pass
        return found

    def checkpoint(self, store, kind, signature, warnings=None):
        # Persist completed checks across launches in the chosen game cache.
        # Failed optional assets retry after a pause, or immediately on change.
        path=game_cache(store.game)/('warmup-'+kind+'-v2.json')
        if warnings is None:
            try: saved=self.checkpoints.get(str(path)) or json.loads(path.read_text())
            except (OSError,ValueError): return None
            if not isinstance(saved,dict): return None
            self.checkpoints[str(path)]=saved
            if saved.get('signature')==signature and (not saved.get('warnings') or saved.get('retryAt',0)>time.time()):
                return saved.get('warnings',[])
            return None
        saved={'signature':signature,'warnings':warnings,'retryAt':time.time()+300 if warnings else 0}
        self._index_write(store.asset_catalog.api,path,store.asset_catalog.api.json_bytes(saved))
        self.checkpoints[str(path)]=saved
        return warnings

    def ui_assets(self, store):
        import subprocess
        from platform_support import worker_command,process_options
        sources=list((store.game/'StudentAge_Data/StreamingAssets').rglob('*.bundle'))+list((store.game/'DLC').rglob('*.bundle'))
        if not sources: return []
        def snapshot():
            outputs=[p for name in ['preview-ui-v1','space-ui-v1','social-media-v1','minigame-images-v1'] for p in (game_cache(store.game)/name).rglob('*') if p.is_file()]
            outputs += [game_cache(store.game)/name for name in ['paper-catalog.json','gift-catalog.json'] if (game_cache(store.game)/name).is_file()]
            return [[str(p),p.stat().st_size,p.stat().st_mtime_ns] for p in sorted(sources+outputs)]
        # Items given up earlier stay given up while the game files are unchanged; they are listed, not retried.
        source_signature=[[str(p),p.stat().st_size,p.stat().st_mtime_ns] for p in sorted(sources)]
        known={key[3:]:record for key,record in self.load_attempts().items() if key.startswith('ui:') and isinstance(record,dict) and record.get('gaveUp') and record.get('signature')==source_signature}
        if known: self.update(abandoned=list(dict.fromkeys(self.get().get('abandoned',[])+[f'界面配图 {name}：{record.get("message","缓存失败")}' for name,record in known.items()])))
        signature=snapshot()
        saved=self.checkpoint(store,'ui',signature)
        if saved is not None:return saved
        self.update(status='running',phase='缓存原版界面与小游戏配图',percent=30)
        failed=[]
        with self.lock:
            if self.stop.is_set():return []
            command=worker_command(Path(__file__).with_name('warm_ui_assets.py'),store.game)+['--skip',json.dumps(sorted(known),ensure_ascii=False)]
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',**process_options())
            self.process=process
        tail=[]
        try:
            # Progress lines arrive per finished item; anything else is error text.
            # The worker never occupies store.lock.
            for line in process.stdout:
                try:value=json.loads(line)
                except ValueError:
                    tail=(tail+[line.strip()])[-8:];continue
                if not isinstance(value,dict):continue
                if isinstance(value.get('failed'),list): failed=[(str(e[0]),str(e[1])) for e in value['failed'] if isinstance(e,list) and len(e)==2]
                done,total=value.get('done') or 0,value.get('total') or 0
                phase='重试未缓存的界面配图' if value.get('retrying') else '缓存原版界面与小游戏配图'
                self.update(status='running',phase=phase+(f' · {done}/{total}' if total else ''),percent=30+int(5*done/max(1,total)),done=done,total=total)
            process.wait()
            if process.returncode and not self.stop.is_set():raise RuntimeError('\n'.join(tail)[-500:] or '原版界面缓存未完成')
            if self.stop.is_set(): return []
            # The worker already tried each failing item MAX_TRIES times and once more at the end:
            # what is still missing is given up (until the game files change or a manual retry).
            abandoned=[]
            for name,message in failed:
                self.give_up(store,'ui:'+name,source_signature,message); abandoned.append(f'界面配图 {name}：{message}')
            if abandoned: self.update(abandoned=list(dict.fromkeys(self.get().get('abandoned',[])+abandoned)))
            self.checkpoint(store,'ui',snapshot(),[])
            return []
        finally:
            if process.poll() is None:process.kill();process.wait()
            with self.lock:self.process=None

    def model_files_signature(self, store, models):
        entries=[]
        for root in [store.game/'StudentAge_Data/StreamingAssets',store.game/'DLC',game_cache(store.game)/'live-model-v1',game_cache(store.game)/'native-models-v1',game_cache(store.game)/'portrait-cache',game_cache(store.game)/'native-portrait-status']:
            if root.exists():
                for p in sorted(root.rglob('*')):
                    if p.is_file():
                        stat=p.stat();entries.append([str(p),stat.st_size,stat.st_mtime_ns])
        return [[list(model) for model in models],entries]

    def native_models(self, store):
        # The runtime renders the complete authored face set per clothing slot.
        from live_model import request
        from portraits import expression_status
        people = store.catalog_rows('PersonCfg')
        models = [(int(key), grade, gender) for key,row in people.items() if str(key).isdigit()
                  for grade,field in [(0,'l2d'),(1,'l2d2')] if row.get(field)
                  for gender in ([1,2] if int(key)==0 and len(row[field])>1 else [1])]
        model_signature=self.model_files_signature(store, models)
        saved=self.checkpoint(store,'models',model_signature)
        if saved is not None:
            known=[f'人物 {key.split(":")[1]}：{record.get("message","缓存失败")}' for key,record in self.load_attempts().items() if key.startswith('model:') and isinstance(record,dict) and record.get('gaveUp') and record.get('signature')==model_signature]
            if known: self.update(abandoned=list(dict.fromkeys(self.get().get('abandoned',[])+known)))
            return saved
        warnings=[];abandoned=[]
        count=max(1,len(models))
        retry_progress={'index':0,'total':0};verified=set()
        def show(i,fraction,retrying=False):
            if retrying:
                k,n=retry_progress['index'],max(1,retry_progress['total'])
                self.update(status='running', phase=f'重试未缓存的人物模型 · {k+1}/{n}', percent=90+int(5*(k+min(1,max(0,fraction)))/n), done=k,total=n)
            else:
                self.update(status='running', phase=f'缓存全部人物模型与表情 · 人物 {i+1}/{len(models)}', percent=35+int(55*(i+min(1,max(0,fraction)))/count), done=i,total=len(models))
        def work(i,role,grade,gender,retrying):
            show(i,0,retrying)
            state=self.wait_for(lambda:request(store.game,role,grade,gender,background=True),'人物模型')
            if self.stop.is_set(): return
            # Reader.extract has already exported the model metadata. Do not
            # import UnityPy into the HTTP process just to inspect clothing.
            name=people[str(role)]['l2d2' if grade else 'l2d'][1 if role==0 and gender==2 else 0]
            clothes={0};signatures=set()
            for path in (game_cache(store.game)/'native-models-v1').glob(name+'-*/model.json'):
                layers=json.loads(path.read_text()).get('layers',{}).get('Cloth',{})
                for key,value in layers.items():
                    signature=json.dumps(value,sort_keys=True)
                    if str(key).isdigit() and 0<=int(key)<=9 and signature not in signatures:
                        clothes.add(int(key));signatures.add(signature)
            for cloth in sorted(clothes):
                from portraits import portrait_key
                stamp_path=game_cache(store.game)/'native-portrait-status'/(portrait_key(role,grade,cloth,gender)+'.json')
                try: old=json.loads(stamp_path.read_text())
                except (OSError,ValueError): old={}
                profile_stamp=state.get('cacheStamp')
                if old.get('complete') and old.get('liveProfileStamp')!=profile_stamp:
                    old['complete']=False
                    store.asset_catalog.api.atomic_write(stamp_path,store.asset_catalog.api.json_bytes(old))
                slot=sorted(clothes).index(cloth)
                # Later attempts only redo what is still missing: clothing this run already cached is left alone.
                if (role,grade,cloth,gender) in verified:
                    show(i,(slot+1)/len(clothes),retrying); continue
                def faces_step(status,slot=slot):
                    known=status.get('faces') if isinstance(status.get('faces'),list) else []
                    drawn=len(status.get('available') or [])
                    show(i,(slot+(drawn/len(known) if known else 0))/len(clothes),retrying)
                status=self.wait_for(lambda:expression_status(store.game,role,grade,cloth,0,request=True,gender=gender,background=True),'人物表情',faces_step)
                if self.stop.is_set(): return
                if status.get('liveProfileStamp')!=profile_stamp:
                    saved=json.loads(stamp_path.read_text());saved['liveProfileStamp']=profile_stamp
                    store.asset_catalog.api.atomic_write(stamp_path,store.asset_catalog.api.json_bytes(saved))
                verified.add((role,grade,cloth,gender))
        deferred=[]
        for i,(role,grade,gender) in enumerate(models):
            if self.stop.is_set(): return []
            key=f'model:{role}:{grade}:{gender}'
            given=self.abandoned(key,model_signature)
            if given: abandoned.append(f'人物 {role}：{given.get("message","缓存失败")}'); continue
            ok,message=self.attempt(store,key,model_signature,lambda:work(i,role,grade,gender,False))
            if not ok and not self.stop.is_set(): deferred.append((i,role,grade,gender,message))
        # Everything else is cached; the items that kept failing automatically get one more try
        # (only their missing parts), then are given up.
        retry_progress['total']=len(deferred)
        for n,(i,role,grade,gender,message) in enumerate(deferred):
            if self.stop.is_set(): return []
            retry_progress['index']=n
            key=f'model:{role}:{grade}:{gender}'
            ok,message=self.attempt(store,key,model_signature,lambda:work(i,role,grade,gender,True),tries=RETRY_TRIES)
            if not ok and not self.stop.is_set():
                self.give_up(store,key,model_signature,message); abandoned.append(f'人物 {role}：{message}')
        self.update(abandoned=list(dict.fromkeys(self.get().get('abandoned',[])+abandoned)))
        if not self.stop.is_set():
            self.checkpoint(store,'models',self.model_files_signature(store, models),warnings)
        return warnings

    def wait_for(self,poll,label,on_progress=None,stall=900,retry=False):
        """Poll a worker until ready. Time out only while nothing changes; waiting
        behind the editor page's own requests never counts as a stall."""
        last=None;since=time.monotonic();retried=not retry
        while not self.stop.is_set():
            status=poll()
            if on_progress:on_progress(status)
            if status.get('status')=='ready' or (status.get('complete') and not status.get('active')):return status
            if status.get('status') in ('error','unavailable') and not status.get('active'):
                if status.get('status')=='error' and not retried:
                    # One transient failure (a killed worker, a busy disk) gets a second attempt.
                    retried=True;self.stop.wait(max(1,min(30,status.get('retryAfter') or 3)));since=time.monotonic();continue
                raise RuntimeError(status.get('message') or label+'缓存失败')
            mark=(status.get('status'),len(status.get('available') or []))
            if mark!=last or status.get('status')=='queued':last=mark;since=time.monotonic()
            if time.monotonic()-since>stall:raise RuntimeError(label+'长时间没有进展，已跳过，稍后自动重试')
            self.stop.wait(.3)
        return {}

    def scan(self):
        store=self.server.store
        projects=store.projects()
        for project in projects:
            if self.stop.is_set(): return
            # Existing, writable local mods only. This method is idempotent for
            # the session, and the foreground load uses the same barrier.
            try: store.clean_orphan_dialogues(project.id)
            except Exception as error:
                logger=getattr(self.server,'error_logs',None)
                if logger:logger.write(error,operation='后台清理无归属对话')
        warnings=[];self.update(abandoned=[])
        # Live2D preview and model prewarming are temporarily paused.
        # Static portrait rendering remains available on demand.
        self.scan_media(store,projects,warnings)
        if self.stop.is_set(): return
        for name,label,stage in (('ui','原版界面与小游戏配图',self.ui_assets),):
            if self.stop.is_set(): return
            self.run_stage(store,name,label,stage,warnings)
        if self.stop.is_set(): return
        assets=self.scan_media(store,projects,warnings,90,9)
        if self.stop.is_set(): return
        abandoned=self.get().get('abandoned',[])
        phase='后台缓存完成' if not warnings else '部分素材缓存未完成'
        if not warnings and abandoned: phase=f'后台缓存完成 · 已放弃 {len(abandoned)} 项多次失败的素材'
        self.update(status='complete' if not warnings else 'error',phase=phase,percent=100 if not warnings else self.get()['percent'],assets=assets,warnings=list(dict.fromkeys(warnings))[:12],abandoned=abandoned[:12])

    def run_stage(self,store,name,label,stage,warnings):
        """A whole stage that keeps crashing follows the same policy as one item: after
        MAX_TRIES+RETRY_TRIES failed scans it is given up (listed, no longer blocking completion)."""
        key='stage:'+name;signature=[str(store.game)]
        given=self.abandoned(key,signature)
        if given:
            self.update(abandoned=list(dict.fromkeys(self.get().get('abandoned',[])+[f'{label}：{given.get("message","缓存失败")}'])));return
        try: warnings.extend(stage(store))
        except Exception as error:
            if self.stop.is_set(): return
            message=str(error) or '缓存失败';attempts=self.load_attempts()
            record=attempts.get(key) if isinstance(attempts.get(key),dict) and attempts.get(key,{}).get('signature')==signature else {'signature':signature,'count':0}
            record['count']=record.get('count',0)+1;record['message']=message;attempts[key]=record;self.save_attempts(store)
            if record['count']>=MAX_TRIES+RETRY_TRIES:
                self.give_up(store,key,signature,message);self.update(abandoned=list(dict.fromkeys(self.get().get('abandoned',[])+[f'{label}：{message}'])))
            else: warnings.append(message)
        else:
            attempts=self.load_attempts()
            if key in attempts: attempts.pop(key,None);self.save_attempts(store)

    def scan_media(self,store,projects,warnings,start=0,span=30):
        cache=game_cache(store.game)
        manifest=auxiliary_cache(store.asset_catalog.settings_path.parent,'AssetCache/media-warmup-v1.json')
        try: previous=json.loads(manifest.read_text())
        except (OSError,ValueError): previous={}
        roots=[cache/name for name in ['assets','audio-cache','portrait-cache','minigame-images-v1','preview-ui-v1','space-ui-v1','social-media-v1']] + [p.path for p in projects]
        roots += [Path(row['path']) for row in store.asset_catalog.folders()['folders'].values() if row.get('path')]
        # Original assets and local mod media stay in their source location;
        # only their indexes and generated previews live in the selected cache.
        found=self.files(roots,{cache.resolve(),manifest.parent.resolve()})
        entries={};pending=[]
        for path,stamp in found.items():
            old=previous.get(path,{})
            if old.get('stamp')==stamp and 'validation' in old and all(Path(p).is_file() for p in old.get('outputs',[])):
                entries[path]=old
                if old.get('validation'):
                    from asset_catalog import stamp as validation_stamp
                    info=dict(old['validation']);info['_fingerprint']=validation_stamp(Path(path))
                    store.asset_catalog._remember_validation((path,info['_fingerprint'],'audio' if Path(path).suffix.lower() not in IMAGES else 'image'),info)
            else: pending.append((path,stamp))
        if pending: self.update(status='running',phase='缓存全部图片与模组素材',percent=start,done=0,total=len(pending))
        def cache_file(path,stamp):
            outputs=[]
            if Path(path).suffix.lower() in IMAGES:
                outputs.append(str(preview_image(path,auxiliary_cache(store.asset_catalog.settings_path.parent,'PreviewCache'))))
            current=Path(path).stat()
            if stamp != [current.st_size,current.st_mtime_ns,current.st_ctime_ns]:
                self.wake.set();return
            from asset_catalog import IMAGES as PICKER_IMAGES, AUDIO
            validation=None
            if Path(path).suffix.lower() in PICKER_IMAGES|AUDIO:
                validation=store.asset_catalog._validate_file(Path(path),'audio' if Path(path).suffix.lower() in AUDIO else 'cg',Path(path).parent)
            entries[path]={'stamp':stamp,'outputs':outputs,'validation':validation}
        deferred=[];abandoned=[]
        for i,(path,stamp) in enumerate(pending):
            if self.stop.is_set(): return
            key='file:'+path;signature=json.dumps(stamp)
            given=self.abandoned(key,signature)
            if given: abandoned.append(Path(path).name+'：'+str(given.get('message','缓存失败')))
            else:
                ok,message=self.attempt(store,key,signature,lambda:cache_file(path,stamp))
                if not ok and not self.stop.is_set(): deferred.append((path,stamp,message))
            self.update(done=i+1,total=len(pending),percent=start+int(span*.7*(i+1)/max(1,len(pending))))
            self.stop.wait(.005)
        for n,(path,stamp,message) in enumerate(deferred):
            if self.stop.is_set(): return
            key='file:'+path;signature=json.dumps(stamp)
            self.update(status='running',phase=f'重试未缓存的素材 · {n+1}/{len(deferred)} · '+Path(path).name)
            ok,message=self.attempt(store,key,signature,lambda:cache_file(path,stamp),tries=RETRY_TRIES)
            if not ok and not self.stop.is_set():
                self.give_up(store,key,signature,message); abandoned.append(Path(path).name+'：'+message)
        if abandoned: self.update(abandoned=list(dict.fromkeys(self.get().get('abandoned',[])+abandoned)))
        images=[{'_path':Path(p),'assetId':p,'name':Path(p).name} for p in entries if Path(p).suffix.lower() in IMAGES]
        store.asset_catalog._deduplicate_backgrounds(images)
        while store.asset_catalog.hash_progress()['running'] and not self.stop.is_set():
            status=store.asset_catalog.hash_progress()
            self.update(status='running',phase=f"整理全部素材索引 · {status['done']}/{status['total']}",percent=start+int(span*(.7+.3*status['percent']/100)),done=status['done'],total=status['total'])
            self.stop.wait(.2)
        if self.stop.is_set(): return
        # Delete only outputs owned by this manifest, never source images.
        live_outputs={p for row in entries.values() for p in row['outputs']}
        preview_root=auxiliary_cache(store.asset_catalog.settings_path.parent,'PreviewCache').resolve()
        for row in previous.values():
            for output in row.get('outputs',[]):
                p=Path(output)
                if output not in live_outputs and p.resolve().parent==preview_root: p.unlink(missing_ok=True)
        if entries!=previous:
            manifest.parent.mkdir(parents=True,exist_ok=True)
            self._index_write(store.asset_catalog.api,manifest,store.asset_catalog.api.json_bytes(entries))
        return len(entries)
