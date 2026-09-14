"""Personal editor player. No music is copied into a mod or release."""
import base64
import hashlib
import threading
from pathlib import Path
from storage_paths import user_data_root
_lock=threading.RLock()
TITLE='遠い空へ'
SOURCE='https://cnt.kingrecords.co.jp/high-resolution/anime/3233.html'

def folder():return user_data_root()/'EditorMusic'
def settings(api):
    value=api.read_json(folder()/'player.json',{})
    if (not isinstance(value,dict) or not isinstance(value.get('library',[]),list)
        or any(not isinstance(r,dict) or any(not isinstance(r.get(k),str) for k in ('id','file','name')) for r in value.get('library',[]))):raise api.ApiError('播放器设置无法读取。')
    return {'mode':'list','collapsed':False,'volume':0.35,**value}
def access(store,api,payload=None):
    with _lock:
        pref=settings(api)
        if payload is not None:
            if 'data' in payload:
                try:raw=base64.b64decode(payload['data'],validate=True)
                except (ValueError,TypeError):raise api.ApiError('音乐文件无法读取。')
                suffix=Path(str(payload.get('fileName',''))).suffix.lower()
                if not raw or len(raw)>40*1024*1024 or suffix not in ('.mp3','.ogg','.wav','.m4a','.flac'):raise api.ApiError('请选择 40 MB 内的 MP3、OGG、WAV、M4A 或 FLAC。')
                valid=(raw[:3]==b'ID3' or raw[:2] in (b'\xff\xfb',b'\xff\xf3',b'\xff\xf2') or raw[:4] in (b'OggS',b'fLaC',b'RIFF') or raw[4:8]==b'ftyp')
                if not valid:raise api.ApiError('文件不是可识别的音频。')
                track_id=payload.get('trackId','tooi-sora')
                if track_id not in ('tooi-sora','odoriko','local'):raise api.ApiError('曲目无效。')
                digest=hashlib.sha256(raw).hexdigest();name=digest+suffix
                api.atomic_write(folder()/name,raw)
                if track_id=='tooi-sora':pref['track']=name
                elif track_id=='odoriko':pref['odoriko']=name
                else:
                    library=pref.setdefault('library',[])
                    if not any(r.get('id')=='local-'+digest for r in library):
                        library.append({'id':'local-'+digest,'file':name,'name':Path(str(payload.get('fileName','音乐')).replace('\\','/')).stem[:200] or '本地音乐','artist':'本地音乐'})
            for key in ('mode','collapsed','volume'):
                if key not in payload:continue
                v=payload[key]
                if key=='mode' and v not in ('single','list','shuffle'):raise api.ApiError('播放模式无效。')
                if key=='collapsed' and type(v)!=bool:raise api.ApiError('收起状态无效。')
                if key=='volume' and (type(v) not in (float,int) or not 0<=v<=1):raise api.ApiError('音量无效。')
                pref[key]=v
            folder().mkdir(parents=True,exist_ok=True);api.atomic_write(folder()/'player.json',api.json_bytes(pref))
        tracks=[{'id':'tooi-sora','name':TITLE,'artist':'市川淳 · 缘之空','source':SOURCE,'local':bool(pref.get('track') and (folder()/pref['track']).is_file())}]
        if pref.get('odoriko') and (folder()/pref['odoriko']).is_file():tracks.append({'id':'odoriko','name':'踊り子','artist':'VAUNDY','local':True})
        for row in pref.get('library',[]):
            if isinstance(row,dict) and row.get('file') and api.safe_path(folder(),row['file']).is_file():
                tracks.append({'id':row['id'],'name':row['name'],'artist':row.get('artist','本地音乐'),'local':True})
        for ident,row in store.catalog_rows('AudioCfg').items():
            if row.get('type',1)==1 and 8 in (row.get('group') or []) and row.get('url'):
                tracks.append({'id':str(ident),'name':row.get('name') or row['url'],'artist':'原版空间 BGM','assetPath':row['url']})
        return {'tracks':tracks,'preferences':{k:pref[k] for k in ('mode','collapsed','volume')}}
def media(api,track_id="tooi-sora"):
    pref=settings(api)
    if track_id in ('tooi-sora','odoriko'):name=pref.get('track' if track_id=='tooi-sora' else 'odoriko','')
    else:name=next((r.get('file','') for r in pref.get('library',[]) if isinstance(r,dict) and r.get('id')==track_id),'')
    path=api.safe_path(folder(),name)
    if not name or not path.is_file():raise api.ApiError('请先导入本地音乐。',404)
    return path
