"""Prepare required tables, then warm disposable media without blocking editing."""
import copy
import threading
import time


class StartupPreparation:
    def __init__(self, server):
        self.server = server
        self.lock = threading.RLock()
        self.state = self.initial_state('idle')

    @staticmethod
    def initial_state(status):
        return {'status': status, 'editorReady': False, 'phase': '读取模组目录',
                'done': 0, 'total': 0, 'percent': 0, 'assets': 0, 'warnings': []}

    def get(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def start(self, preferred=None, folders_only=False):
        with self.lock:
            if self.state['status'] == 'running':
                return self.get()
            self.state = self.initial_state('running')
        threading.Thread(target=self.run, args=(preferred, folders_only), daemon=True).start()
        return self.get()

    def run(self, preferred, folders_only):
        app = self.server
        notices = []
        try:
            store = app.store
            # Capture this location's workers: never accidentally warm a newly
            # selected game's resources with this run's progress state.
            jobs_by_kind = [('原版图片', app.resources), ('原版声音', app.audio_resources)]
            media_warmup = getattr(app, 'media_warmup', None)
            if not folders_only and store.game.is_dir() and not store.catalog_prepared():
                self.update(phase='首次读取原版游戏配置')
                try:
                    app.prepare_game()
                except Exception as error:
                    notices.append(str(error))
            schemas = bool(store.catalog().get('schemas'))
            # Only table definitions are needed to initialize the editor. Media
            # extraction continues independently after this readiness signal.
            self.update(editorReady=True)
            if not folders_only and schemas:
                for index, (label, jobs) in enumerate(jobs_by_kind):
                    self.update(phase='缓存'+label, done=0, total=0, percent=index*25)
                    state = jobs.get()
                    # Refresh checks bundle fingerprints; unchanged outputs are reused.
                    if state['status'] != 'running':
                        try:
                            state = jobs.start()
                        except Exception as error:
                            # An on-demand picker can start the same worker.
                            state = jobs.get()
                            if state['status'] != 'running': raise error
                    while state['status'] == 'running':
                        progress = state.get('progress') or {}
                        done, total = progress.get('bundle') or 0, progress.get('total') or 0
                        fraction = progress.get('fraction')
                        if not isinstance(fraction,(int,float)): fraction=done/total if total else 0
                        percent = min(49, index*25 + min(24,max(0,int(25*fraction))))
                        self.update(phase='缓存'+label+' · '+state.get('message',''),
                                    done=done, total=total, percent=percent)
                        time.sleep(.3)
                        state = jobs.get()
                    if state['status'] == 'error' or state.get('failures'):
                        notices.append(state.get('message', label+'部分内容未能读取'))
            if not schemas:
                notices.append('尚未找到可用的原版游戏数据，可进入工坊后在“工坊设置”选择游戏。')
            if media_warmup and not getattr(getattr(media_warmup,'stop',None),'is_set',lambda:False)():
                state = media_warmup.start()
                while state['status'] == 'running':
                    self.update(phase=state.get('phase','缓存全部素材'),percent=50+int(state.get('percent',0)*.49),done=state.get('done',0),total=state.get('total',0))
                    time.sleep(.3);state=media_warmup.get()
                notices.extend(state.get('warnings',[]))
            self.update(status='complete', editorReady=True, percent=100 if not notices else self.get()['percent'], phase='后台缓存完成' if not notices else '部分缓存未完成',
                        warnings=list(dict.fromkeys(notices))[:12])
        except Exception as error:
            log = app.error_logs.write(error, operation='启动素材预加载')
            self.update(status='error', editorReady=True, phase='部分内容未能准备完成',
                        warnings=[*notices,str(error)], errorLog=log)
