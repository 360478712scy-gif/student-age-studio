"""GitHub release updates: stage verified code beside the install, then activate at restart."""
import ast
import certifi
import ssl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from update_bootstrap import RUNTIME_ABI, updates_root, read_state, write_json, version_dir, version_key, state_lock

MAX_ARCHIVE=64*1024*1024
MAX_EXPANDED=128*1024*1024
NOTICE_FILES={'LICENSE','THIRD_PARTY_NOTICES.md'}
CODE_EXTENSIONS={'.py','.js','.json','.html','.css','.png','.svg'}


def code_name(name):
    p=PurePosixPath(name)
    return (len(p.parts)==2 and p.parts[0]=='standalone' and p.name not in ('update_bootstrap.py','update-channel.json')
            and p.suffix in CODE_EXTENSIONS and name==p.as_posix()
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',p.name) is not None
            and p.name.split('.')[0].upper() not in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]})


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        host=urllib.parse.urlsplit(newurl)
        if host.scheme!='https' or host.hostname not in ('github.com','api.github.com','raw.githubusercontent.com','release-assets.githubusercontent.com','objects.githubusercontent.com'):
            raise ValueError('更新下载跳转到了未经允许的地址。')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def tls_context():
    context=ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


def open_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ('github.com','api.github.com','raw.githubusercontent.com'):raise ValueError('更新地址无效。')
    req=urllib.request.Request(url,headers={'User-Agent':'StudentAgeStudio-Updater/1','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2026-03-10'})
    return urllib.request.build_opener(HTTPSRedirect(),urllib.request.HTTPSHandler(context=tls_context())).open(req,timeout=30)


def unpack_archive(archive, destination, expected_version):
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        if len(infos)>1000 or len(names)!=len(set(names)) or len({n.casefold() for n in names})!=len(names):raise ValueError('更新包文件清单异常。')
        if sum(i.file_size for i in infos)>MAX_EXPANDED:raise ValueError('更新包解压尺寸超过限制。')
        if 'update.json' not in names:raise ValueError('缺少更新清单。')
        for info in infos:
            if info.file_size>16*1024*1024 or stat.S_ISLNK(info.external_attr>>16) or info.is_dir():raise ValueError('更新包包含不支持的文件。')
            if info.filename not in NOTICE_FILES|{'update.json'} and not code_name(info.filename):raise ValueError('更新包包含越界或非代码文件。')
        manifest=json.loads(z.read('update.json'))
        if manifest.get('format')!=1 or manifest.get('runtimeAbi')!=RUNTIME_ABI:raise ValueError('此版本需要升级完整客户端运行环境。')
        if version_key(manifest.get('version'))!=version_key(expected_version):raise ValueError('更新包与发布版本不一致。')
        files=manifest.get('files')
        if not isinstance(files,dict) or set(files)!=(set(names)-{'update.json'}):raise ValueError('更新文件与清单不一致。')
        if not {'standalone/server.py','standalone/index.html','standalone/error_logs.py'}<=set(files):raise ValueError('更新包缺少启动文件。')
        for name,digest in files.items():
            data=z.read(name)
            if not isinstance(digest,str) or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('更新文件校验失败：'+name)
            if name.endswith('.py'):compile(data,name,'exec')
            if name=='standalone/error_logs.py':
                value=next(ast.literal_eval(n.value) for n in ast.parse(data).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='APP_VERSION' for t in n.targets))
                if version_key(value)!=version_key(expected_version):raise ValueError('程序版本与更新清单不一致。')
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        write_json(destination/'update.json',manifest)
        return manifest


class AppUpdates:
    def __init__(self, web_root, current_version, root=None, opener=open_url, managed=None):
        self.base=Path(os.environ.get('STUDIO_BASE_WEB') or web_root).resolve()
        self.web=Path(web_root).resolve();self.current=current_version;self.root=root or updates_root();self.opener=opener
        self.managed=os.environ.get('STUDIO_UPDATE_MANAGED')=='1' if managed is None else managed
        self.config=json.loads((self.base/'update-channel.json').read_text('utf-8'))
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',self.config['repository']):raise ValueError('GitHub 仓库配置无效。')
        self.running_id=os.environ.get('STUDIO_ACTIVE_UPDATE')
        self.lock=threading.RLock();self.release=None;self.asset=None;self.staged=None
        self.state={'status':'idle','message':'可从 GitHub 检查新版本。','progress':0}

    def status(self):
        with self.lock:
            return {**self.state,'currentVersion':self.current,'repository':self.config['repository'],'managed':self.managed,
                    'notice':read_state(self.root).get('notice',''),'canRollback':bool(read_state(self.root).get('active'))}

    def check(self):
        with self.lock:
            if self.state['status'] in ('checking','downloading','ready','activating'):return self.status()
            self.state.update(status='checking',message='正在检查 GitHub 发布…')
        try:
            if self.config.get('sourceUpdates',self.config['repository']=='360478712scy-gif/student-age-studio'):
                result=self.check_source_feed()
                if result is not None:return result
            url='https://api.github.com/repos/'+self.config['repository']+'/releases?per_page=30'
            with self.opener(url) as response:
                data=response.read(2*1024*1024+1)
            if len(data)>2*1024*1024:raise ValueError('发布列表超过限制。')
            releases=json.loads(data);candidates=[]
            if not isinstance(releases,list):raise ValueError('GitHub 发布列表格式错误。')
            for release in releases:
                if release.get('draft') or self.config.get('channel')!='beta' and release.get('prerelease'):continue
                try:key=version_key(release['tag_name'])
                except (KeyError,ValueError):continue
                if key>version_key(self.current):candidates.append((key,release))
            with self.lock:
                self.release=max(candidates,key=lambda r:r[0])[1] if candidates else None;self.asset=None;self.staged=None
                if not self.release:self.state={'status':'current','message':'当前已经是最新版本。','progress':0}
                else:
                    release=self.release;asset=next((a for a in release.get('assets',[]) if a.get('name')==self.config['asset']),None)
                    if not asset or not re.fullmatch(r'sha256:[0-9a-f]{64}',asset.get('digest') or ''):raise ValueError('新版本尚未提供可校验的在线更新包。')
                    prefix='https://github.com/'+self.config['repository']+'/releases/download/'+urllib.parse.quote(release['tag_name'],safe='')+'/'
                    if asset.get('browser_download_url')!=prefix+urllib.parse.quote(self.config['asset'],safe=''):raise ValueError('发布附件地址与仓库不符。')
                    if not isinstance(asset.get('size'),int) or not 0<asset['size']<=MAX_ARCHIVE:raise ValueError('更新包尺寸异常。')
                    self.asset=asset;self.state={'status':'available','version':release['tag_name'],'notes':str(release.get('body') or '')[:12000],'message':'发现新版本，可以下载。','progress':0}
            return self.status()
        except Exception as error:
            with self.lock:self.state.update(status='error',message=self.error_text(error))
            return self.status()

    def check_source_feed(self):
        prefix='https://raw.githubusercontent.com/'+self.config['repository']+'/'
        try:
            with self.opener(prefix+'updates/latest.json') as response:data=response.read(32769)
        except urllib.error.HTTPError as error:
            if error.code==404:return None
            raise
        if len(data)>32768:raise ValueError('更新清单超过限制。')
        feed=json.loads(data)
        if not isinstance(feed,dict) or feed.get('format')!=1:raise ValueError('更新清单格式错误。')
        version=feed.get('version');key=version_key(version)
        if self.config.get('channel')!='beta' and '-' in version:return None
        if feed.get('runtimeAbi')!=RUNTIME_ABI:raise ValueError('此版本需要升级完整客户端运行环境。')
        commit=feed.get('commit','');digest=feed.get('sha256','');size=feed.get('size')
        if not re.fullmatch(r'[0-9a-f]{40}',commit) or not re.fullmatch(r'[0-9a-f]{64}',digest) or type(size)!=int or not 0<size<=MAX_ARCHIVE:raise ValueError('更新清单校验信息无效。')
        with self.lock:
            self.asset=None;self.release=None;self.staged=None
            if key<=version_key(self.current):self.state={'status':'current','message':'当前已经是最新版本。','progress':0}
            else:
                self.release={'tag_name':version}
                self.asset={'size':size,'digest':'sha256:'+digest,'browser_download_url':prefix+commit+'/'+self.config['asset']}
                self.state={'status':'available','version':version,'notes':str(feed.get('notes') or '')[:12000],'message':'发现新版本，可以下载。','progress':0}
        return self.status()

    @staticmethod
    def error_text(error):
        if isinstance(error,urllib.error.HTTPError):
            return {404:'GitHub 仓库尚未公开或尚无发布版本。',403:'GitHub 暂时限制访问，请稍后重试。',429:'检查过于频繁，请稍后重试。'}.get(error.code,'GitHub 暂时无法访问，请稍后重试。')
        if isinstance(error,(TimeoutError,urllib.error.URLError)):return '无法连接 GitHub，请检查网络后重试。'
        if isinstance(error,PermissionError):return '更新目录不可写，请检查用户数据目录权限。'
        if isinstance(error,OSError):return '更新文件读写失败，请检查磁盘空间和目录权限。'
        return str(error)

    def download(self):
        with self.lock:
            if not self.managed:raise ValueError('源码预览不会安装更新，请使用带在线更新的客户端。')
            if self.state['status']=='downloading':return self.status()
            if self.state['status']!='available' or not self.asset:raise ValueError('请先检查并选择有效的新版本。')
            asset=dict(self.asset);version=self.release['tag_name'];self.state.update(status='downloading',message='正在下载更新…',progress=0)
        threading.Thread(target=self._download,args=(asset,version),daemon=True).start()
        return self.status()

    def _download(self,asset,version):
        temporary=self.root/('staging-'+uuid.uuid4().hex)
        try:
            temporary.mkdir(parents=True);archive=temporary/'payload.zip';digest=hashlib.sha256();count=0
            with self.opener(asset['browser_download_url']) as source, archive.open('xb') as dest:
                while True:
                    block=source.read(128*1024)
                    if not block:break
                    count+=len(block)
                    if count>asset['size'] or count>MAX_ARCHIVE:raise ValueError('下载内容超过发布尺寸。')
                    digest.update(block);dest.write(block)
                    with self.lock:self.state['progress']=int(count*85/asset['size'])
            if count!=asset['size'] or 'sha256:'+digest.hexdigest()!=asset['digest']:raise ValueError('更新包校验失败，请重新下载。')
            overlay=temporary/'version';overlay.mkdir()
            manifest=unpack_archive(archive,overlay,version)
            # Preserve installed private artwork/optional SDKs without putting them in the update feed.
            for source in self.base.iterdir():
                if source.name in ('tests','__pycache__'):continue
                dest=overlay/'standalone'/source.name
                if dest.exists():continue
                if source.is_dir():shutil.copytree(source,dest,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                elif source.name in ('update_bootstrap.py','update-channel.json') or source.suffix not in CODE_EXTENSIONS:shutil.copy2(source,dest)
            identifier=version.removeprefix('v')+'-'+digest.hexdigest()[:12]
            destination=version_dir(self.root,identifier);destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists():
                if json.loads((destination/'update.json').read_text('utf-8'))!=manifest:raise ValueError('同名更新目录不一致，请联系维护者。')
            else:os.replace(overlay,destination)
            with self.lock:self.staged=identifier;self.state.update(status='ready',progress=100,message='更新已准备好。保存并重启后生效。')
        except Exception as error:
            with self.lock:self.state.update(status='error',message=self.error_text(error))
        finally:shutil.rmtree(temporary,ignore_errors=True)

    def activate(self, rollback=False):
        with self.lock, state_lock(self.root):
            if not self.managed:raise ValueError('当前客户端不支持在线更新重启。')
            state=read_state(self.root)
            if state.get('active')!=self.running_id:raise ValueError('其他窗口已更改更新版本，请先关闭并重新打开应用。')
            if rollback:
                if not state.get('active'):raise ValueError('没有可回退的在线更新。')
                write_json(self.root/'active.json',{'active':state.get('previous'),'notice':'已手动恢复上一版本。'})
            else:
                if self.state['status']!='ready' or not self.staged:raise ValueError('请先下载更新。')
                write_json(self.root/'active.json',{'active':self.staged,'previous':state.get('active'),'pending':True,'attempted':False})
            self.state.update(status='activating',message='正在重启…')
            return self.status()
