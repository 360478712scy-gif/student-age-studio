"""Original game preview UI resources, read from the installed game into a small cache."""
from storage_paths import game_cache, auxiliary_cache
from pathlib import Path
import json
import threading

_lock = threading.Lock()
_SPRITES = {'dialogue':'common5/img_talk_content','name':'common5/img_talk_name','history':'common2/img_duihua3','aside':'common3/img_box_2','history-name':'main/img_bianyuanmohu', **{'option-'+state:'evt/btn_option_'+state for state in ('normal','highlight','select','disable')}}
_SPRITES.update({'plane':'item/img_zfj','key-bg':'common5/img_key_bg', **{'key-'+key:'keys/icon_key_'+key for key in ('tab','shift','esc')}})
_FONTS = {'sans':'SourceHanSansCN-Medium','serif':'SourceHanSerifCN-Heavy'}
_COLORS = {'male':[1603,1604,1614,1615], 'female':[1605,1606,1616,1617], 'neutral':[1607,1608,1609,1610]}

def resources(game):
    game=Path(game);cache=game_cache(game) / 'preview-ui-v1';manifest=cache/'manifest.json'
    with _lock:
        if manifest.is_file():
            saved=json.loads(manifest.read_text(encoding='utf8'))
            if saved.get('version')==4 and saved.get('reference')==[2560,1440] and all((cache/name).is_file() for name in saved['files']) and all((game/path).is_file() and [(game/path).stat().st_size,(game/path).stat().st_mtime_ns]==stamp for path,stamp in saved['sources'].items()):return saved
        from extract_game_assets import UnityPy,connect_dependencies,bundle_members
        from PIL import Image,ImageChops
        folder=game/'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64';bundles=list(folder.rglob('*.bundle'));sources={};files=[];palette={};cache.mkdir(parents=True,exist_ok=True)
        def load(path):
            st=path.stat();sources[str(path.relative_to(game))]=[st.st_size,st.st_mtime_ns];return UnityPy.load(str(path))
        for path in folder.glob('*cfgs*.bundle'):
            env=load(path)
            for name,obj in env.container.items():
                if name.lower().endswith('/zh-cn/colorcfg.json'):palette=json.loads(obj.read().m_Script);break
            if palette:break
        if not palette:raise FileNotFoundError('未能读取游戏的界面颜色配置')
        # Resolve only these atlases and fonts; never enumerate or cache mod content.
        index={}
        for path in bundles:
            for member in bundle_members(path):index[member.lower()]=path
        def connected(path):
            env=load(path)
            tracked={k:v for k,v in index.items()}
            connect_dependencies(env,tracked);return env
        images={}
        for group in {v.split('/')[0] for v in _SPRITES.values()}:
            path=next(folder.glob('localization-assets-chinese(simplified)*.bundle')) if group=='keys' else next(folder.rglob(group+'_*.bundle'));env=connected(path)
            wanted={v.split('/')[1]:k for k,v in _SPRITES.items() if v.startswith(group+'/')}
            for obj in list(env.objects):
                if obj.type.name=='Sprite':
                    sprite=obj.parse_as_object()
                    if sprite.m_Name in wanted:images[wanted[sprite.m_Name]]=sprite.image.convert('RGBA')
        if len(images)!=len(_SPRITES):raise FileNotFoundError('游戏对话界面贴图不完整')
        def save(name,picture):
            tmp=cache/(name+'.tmp');picture.save(tmp,format='PNG');tmp.replace(cache/name);files.append(name)
        colors={}
        for gender,ids in _COLORS.items():
            colors[gender]=[palette[str(i)]['color'] for i in ids]
            for key in ('dialogue','name','history','aside','history-name'):
                color=colors[gender][2 if key in ('name','history-name') else 0]
                original=images[key];tint=Image.new('RGBA',original.size,color);tinted=ImageChops.multiply(original,tint);tinted.putalpha(original.getchannel('A'));save(key+'-'+gender+'.png',tinted)
        for key in images:
            if key=='key-bg':
                bg=Image.new('RGBA',images[key].size,(0,0,0,0));bg.putalpha(images[key].getchannel('A').point(lambda a:round(a*.298039)));save(key+'.png',bg)
            elif key.startswith(('option-','key-')) or key=='plane':save(key+'.png',images[key])
        fonts={}
        # The serif source font is an Addressables dependency, not always in fonts_assets.
        font_paths=[p for p in bundles if p.name.startswith(('fonts_assets_','prefabs_assets_evt_'))]
        for path in font_paths:
            env=connected(path)
            for obj in list(env.objects):
                if obj.type.name=='MonoBehaviour':
                    try:
                        d=obj.read_typetree()
                        if d.get('m_Name')=='SourceHanSerifCN-Heavy SDF':
                            from UnityPy.classes import PPtr
                            ptr=PPtr(**d['m_SourceFontFile'],assetsfile=obj.assets_file);font=ptr.deref().parse_as_object();fonts['serif']=bytes(font.m_FontData)
                    except (ValueError,KeyError,FileNotFoundError):pass
                elif obj.type.name=='Font':
                    font=obj.parse_as_object()
                    for key,name in _FONTS.items():
                        if font.m_Name==name:fonts[key]=bytes(font.m_FontData)
            if len(fonts)==2:break
        if len(fonts)!=2:raise FileNotFoundError('未能读取游戏原版字体')
        for key,data in fonts.items():
            name=key+'.otf';tmp=cache/(name+'.tmp');tmp.write_bytes(data);tmp.replace(cache/name);files.append(name)
        from paper_ui import extract
        paper_files,paper_sources=extract(game,cache);files.extend(paper_files);sources.update(paper_sources)
        result={'version':4,'files':files,'colors':colors,'sources':sources,'source':'installed-game','reference':[2560,1440]}
        tmp=cache/'manifest.tmp';tmp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf8');tmp.replace(manifest);return result

def resource_file(game,name):
    result=resources(game)
    if name not in result['files']:raise FileNotFoundError('未知的预览界面资源')
    return game_cache(Path(game)) / 'preview-ui-v1'/name
