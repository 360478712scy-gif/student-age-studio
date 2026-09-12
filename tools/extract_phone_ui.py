"""Extract the installed game's phone shell and message widgets on demand."""
import json
import threading
from pathlib import Path

_lock=threading.Lock()

def resources(game, cache_dir=None):
    from extract_game_assets import UnityPy,connect_dependencies,bundle_members
    from UnityPy.classes import PPtr
    from PIL import Image,ImageChops
    game=Path(game);folder=game/'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64';cache=Path(cache_dir) if cache_dir is not None else game/'StudentAgeStudio/phone-ui-v1'
    with _lock:
        manifest=cache/'manifest.json'
        if manifest.is_file():
            try:
                data=json.loads(manifest.read_text(encoding='utf8'))
                if data.get('version')==2 and all((cache/n).is_file() for n in data['files']) and all((game/p).is_file() and [(game/p).stat().st_size,(game/p).stat().st_mtime_ns]==v for p,v in data['sources'].items()):return data
            except (OSError,KeyError,ValueError):pass
        index={k.lower():p for p in folder.rglob('*.bundle') for k in bundle_members(p)}
        wanted={'group_anime/_front':'frame','group_anime/_keyboard':'keyboard','group_anime/group_bg':'screen',
                'group_bg/icon_wallpaper':'wallpaper','group_bg/img_phone_energy':'battery','group_bg/img_lefttop':'signal',
                'group_top_bar/group_title':'title','btn_back/_img':'back','btn_close/_img':'close',
                'Cell_PhoneMsgLeftItem/bg_content':'left','Cell_PhoneMsgRightItem/bg_content':'right',
                'Cell_PhoneOptionItem/btn_click':'option','itemgroup_options/_bg':'options',
                'Cell_PhoneMsgItem/btn_click':'contact','Cell_PhoneMsgLeftItem/img_loading':'loading',
                'Cell_PhoneTimeItem/txt_time/_img':'time-line'}
        files=[];sprites={};fonts={};sources={};cache.mkdir(parents=True,exist_ok=True)
        def tracked(env):
            def visit(parts):
                for obj in parts:
                    name=str(getattr(obj,'name','')).replace('\\','/').rsplit('/',1)[-1].lower();p=index.get(name) or (folder/name if (folder/name).is_file() else None)
                    if p:sources[str(p.relative_to(game))]=[p.stat().st_size,p.stat().st_mtime_ns]
                    visit((getattr(obj,'files',None) or {}).values())
            visit(env.files.values())
        def walk(go,prefix=''):
            g=go.read_typetree();path=(prefix+'/'+g['m_Name']).lstrip('/');transform={}
            for c in g['m_Component']:
                obj=go.assets_file.objects[c['component']['m_PathID']]
                try:d=obj.read_typetree()
                except ValueError:continue
                if obj.type.name=='RectTransform':transform=d
                pointer=d.get('m_Sprite') or d.get('m_Texture') or {}
                if pointer.get('m_PathID'):
                    for suffix,key in wanted.items():
                        if not path.endswith('/'+suffix):continue
                        resource=PPtr(**pointer,assetsfile=obj.assets_file).deref().parse_as_object();picture=resource.image.convert('RGBA');color=d.get('m_Color',{})
                        tint=Image.new('RGBA',picture.size,tuple(round(255*color.get(c,1)) for c in 'rgba'));picture=ImageChops.multiply(picture,tint)
                        file=key+'.png';picture.save(cache/file);files.append(file);border=getattr(resource,'m_Border',None)
                        sprites[key]={'file':file,'size':list(picture.size),'border':[border.w,border.z,border.y,border.x] if border else [0,0,0,0]}
                if path.endswith('/Cell_PhoneMsgLeftItem/txtex_content') and 'body' not in fonts:
                    p=d.get('m_fontAsset') or d.get('m_FontData',{}).get('m_Font')
                    if p and p.get('m_PathID'):
                        font=PPtr(**p,assetsfile=obj.assets_file).deref()
                        if font.type.name!='Font':
                            p=font.read_typetree().get('m_SourceFontFile')
                            if not p or not p.get('m_PathID'):continue
                            font=PPtr(**p,assetsfile=font.assets_file).deref()
                        raw=bytes(font.parse_as_object().m_FontData)
                        if raw:(cache/'body.otf').write_bytes(raw);files.append('body.otf');fonts['body']='body.otf'
            for child in transform.get('m_Children',[]):
                t=go.assets_file.objects[child['m_PathID']].read_typetree();walk(go.assets_file.objects[t['m_GameObject']['m_PathID']],path)
        for bundle in folder.glob('prefabs_assets_phone_*.bundle'):
            env=UnityPy.load(str(bundle));entries=list(env.container.items());connect_dependencies(env,index)
            for name,ptr in entries:
                if name.lower().endswith(('/phoneview@main.prefab','/phonepagemsgview@main.prefab')):walk(ptr.deref())
            tracked(env);sources[str(bundle.relative_to(game))]=[bundle.stat().st_size,bundle.stat().st_mtime_ns]
        if not {'frame','left','right','option'}.issubset(sprites):raise FileNotFoundError('未找到完整的原版短信界面，请确认游戏资源位置。')
        data={'version':2,'files':list(dict.fromkeys(files)),'sprites':sprites,'fonts':fonts,'sources':sources,'reference':[917,1393]}
        temp=cache/'manifest.tmp';temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8');temp.replace(manifest);return data

def resource_file(game,name):
    if name not in resources(game)['files']:raise FileNotFoundError('未知的短信界面素材')
    return Path(game)/'StudentAgeStudio/phone-ui-v1'/name
