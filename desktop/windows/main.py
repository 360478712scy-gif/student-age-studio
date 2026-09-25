"""Regular WebView2 edition. The optional bundled edition uses electron-backend.py."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import threading
import time
import uuid

ROOT = Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
WORKER = '--extract' in sys.argv or '--server-only' in sys.argv
BASE_WEB = ROOT / 'standalone'
sys.path.insert(0,str(BASE_WEB))
from update_bootstrap import select_web, RESTART_EXIT
os.environ['STUDIO_BASE_WEB']=str(BASE_WEB)
os.environ['STUDIO_INSTALL_ROOT']=str(Path(sys.executable).resolve().parent.parent) if getattr(sys,'frozen',False) else str(ROOT)
# Source/QA runs cannot install remote updates. The supervising launcher enables packaged runs.
if not getattr(sys,'frozen',False):os.environ['STUDIO_UPDATE_MANAGED']='0'
WEB = Path(os.environ['STUDIO_ACTIVE_WEB']) if WORKER and os.environ.get('STUDIO_ACTIVE_WEB') else select_web(BASE_WEB)
os.environ['STUDIO_ACTIVE_WEB']=str(WEB)
sys.path.insert(0,str(WEB))
if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr,'reconfigure'): sys.stderr.reconfigure(encoding='utf-8')

WEBVIEW_REQUIREMENT = ('未检测到可用的 Microsoft Edge WebView2 Runtime。\n'
    '工作台不能使用旧的 IE 内核，否则会出现布局错乱并停在“正在读取模组”。\n\n'
    '请安装或修复微软 WebView2 Evergreen Runtime 后重新打开工作台：\n'
    'https://developer.microsoft.com/microsoft-edge/webview2/\n\n'
    '本次未打开模组，也未修改模组文件。')

def require_modern_webview():
    import importlib
    guilib = importlib.import_module('webview.guilib')
    guilib.forced_gui_ = 'edgechromium'
    from webview.platforms import winforms
    if winforms.renderer != 'edgechromium':
        raise RuntimeError(WEBVIEW_REQUIREMENT)

def main():
    if '--extract' in sys.argv:
        i=sys.argv.index('--extract'); name=sys.argv[i+1]
        if name not in ('extract_catalog','extract_game_assets','extract_audio_assets','native_portraits','condition_library','model_idle','live_model','warm_ui_assets','studio_cli','studio_mcp'): raise ValueError('Unknown worker')
        sys.argv=[str(WEB/(name+'.py')),*sys.argv[i+2:]]
        runpy.run_path(sys.argv[0],run_name='__main__'); return
    from child_processes import own_children
    child_job = own_children()
    import server
    if '--server-only' in sys.argv:
        sys.argv.remove('--server-only'); server.main(); return
    p=argparse.ArgumentParser(); p.add_argument('--port',type=int,default=0)
    for name in ('game','mods','workshop','qa-ready','qa-script','qa-result','qa-location-settings','qa-storage'): p.add_argument('--'+name)
    p.add_argument('--qa-debug-port',type=int)
    args=p.parse_args(); args.web_root=str(WEB)
    if args.qa_debug_port: os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']='--remote-debugging-port='+str(args.qa_debug_port)
    from storage_paths import user_data_root, cache_root
    storage=Path(args.qa_storage) if args.qa_storage else user_data_root()/'WebView2'
    browser_cache=cache_root()/'WebView2'
    try:
        browser_cache.mkdir(parents=True,exist_ok=True)
    except OSError:
        pass  # Keep the settings UI available when the chosen drive is offline.
    else:
        os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=(os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS','')+' --disk-cache-dir="'+str(browser_cache)+'"').strip()
    storage.mkdir(parents=True,exist_ok=True)
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("StudentAgeStudio.WebView2")
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=(os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS','')+' --autoplay-policy=no-user-gesture-required').strip()
    require_modern_webview()
    host=server.create_server(args)
    threading.Thread(target=host.serve_forever,daemon=True).start()
    import webview
    close_state={'approved':False,'checking':False,'request':None}
    class Bridge:
        def close_result(self, request_id, allowed, error=''):
            if not close_state['checking'] or request_id != close_state['request']: return False
            close_state['checking']=False
            if allowed is True and not error:
                close_state['approved']=True; window.destroy()
            return True
        def choose_game(self):
            result=window.create_file_dialog(webview.FileDialog.FOLDER)
            return result[0] if result else None
        def choose_folder(self, kind=None):
            result=window.create_file_dialog(webview.FileDialog.FOLDER)
            return result[0] if result else None
        def choose_mods(self):
            result=window.create_file_dialog(webview.FileDialog.FOLDER)
            return result[0] if result else None
    from error_logs import APP_VERSION
    window=webview.create_window('拾光工坊·模组编辑器-'+APP_VERSION,host.origin+'/#'+host.token,js_api=Bridge(),width=1440,height=920,min_size=(1040,700),background_color='#f4f6fa',text_select=True,maximized=True)
    def restart_update():
        host.update_restart_requested=True;close_state['approved']=True;window.destroy()
    host.request_update_restart=restart_update
    loaded=threading.Event(); window.events.loaded += loaded.set
    def closing():
        if close_state['approved'] or not loaded.is_set(): return True
        if close_state['checking']: return False
        close_state['checking']=True
        request_id=uuid.uuid4().hex; close_state['request']=request_id
        def decide():
            try:
                script="""(async()=>{let allowed=false,error='';try{allowed=window.STUDIO_REQUEST_CLOSE?await window.STUDIO_REQUEST_CLOSE():!(window.STUDIO_HAS_UNSAVED_CHANGES&&window.STUDIO_HAS_UNSAVED_CHANGES());}catch(e){error=String(e.message||e);}await window.pywebview.api.close_result(%s,allowed===true,error);})();true;""" % json.dumps(request_id)
                window.evaluate_js(script)
            except Exception: close_state['checking']=False
        threading.Thread(target=decide,daemon=True).start(); return False
    window.events.closing += closing
    def ready():
        if args.qa_ready: Path(args.qa_ready).write_text(json.dumps({'url':host.origin,'token':host.token,'pid':os.getpid(),'frozen':getattr(sys,'frozen',False),'executable':sys.executable}),encoding='utf-8')
        if args.qa_script:
            try:
                time.sleep(5);result=window.evaluate_js(Path(args.qa_script).read_text(encoding='utf-8'))
                Path(args.qa_result).write_text(json.dumps({'ok':True,'result':result},ensure_ascii=False),encoding='utf-8')
            except Exception as e: Path(args.qa_result).write_text(json.dumps({'ok':False,'error':str(e)}),encoding='utf-8')
    try: webview.start(ready,gui='edgechromium',private_mode=False,storage_path=str(storage))
    finally:
        host.shutdown();host.server_close()
        import portraits
        portraits.shutdown()
    if host.update_restart_requested:raise SystemExit(RESTART_EXIT)

if __name__=='__main__':
    try: main()
    except Exception as error:
        from update_bootstrap import rollback_failed_start
        if not WORKER and rollback_failed_start():raise SystemExit(RESTART_EXIT)
        from error_logs import ErrorLogs
        logs = ErrorLogs()
        name = logs.write(error, operation='启动 Windows 应用')
        diagnostic = str(logs.root / name) if name else '错误日志无法写入：' + str(logs.root)
        if not WORKER:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,'启动失败：\n'+str(error)+'\n\n详细日志：\n'+diagnostic,'学生时代模组工作台',16)
        raise
