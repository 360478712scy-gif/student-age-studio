"""Native paper sprite and TMP glyph atlas, without downloading replacement fonts."""
from storage_paths import game_cache, auxiliary_cache
import json
from pathlib import Path

def extract(game, cache):
    from extract_game_assets import UnityPy, connect_dependencies, bundle_members
    from UnityPy.classes import PPtr
    from PIL import Image
    folder=Path(game)/'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64'
    index={k.lower():p for p in folder.glob('*.bundle') for k in bundle_members(p)}
    fonts={}; files=[]; sources={}
    def font_data(obj,key):
        d=obj.read_typetree()
        if not d.get('m_CharacterTable'):return
        glyphs={str(g['m_Index']):g for g in d['m_GlyphTable']}
        characters={str(c['m_Unicode']):glyphs[str(c['m_GlyphIndex'])] for c in d['m_CharacterTable'] if str(c['m_GlyphIndex']) in glyphs}
        names=[]
        for i,ptr in enumerate(d['m_AtlasTextures']):
            tex=PPtr(**ptr,assetsfile=obj.assets_file).deref().parse_as_object().image.convert('RGBA')
            # TMP SDF distance 0.5 is the outline. Preserve antialiasing at its edge.
            alpha=tex.getchannel('A').point(lambda a:max(0,min(255,(a-112)*8)))
            image=Image.new('RGBA',tex.size,(0,0,0,255));image.putalpha(alpha)
            name=f'paper-{key}-{i}.png';image.save(cache/name);names.append(name);files.append(name)
        fonts[key]={'characters':characters,'face':d['m_FaceInfo'],'atlases':names}
    for path in folder.glob('prefabs_assets_evt_*.bundle'):
        env=UnityPy.load(str(path));entries=list(env.container.items());connect_dependencies(env,index)
        for name,ptr in entries:
            if '/paperview@talk.prefab' not in name.lower():continue
            def walk(go):
                g=go.read_typetree();transform={}
                for c in g['m_Component']:
                    obj=go.assets_file.objects.get(c['component']['m_PathID'])
                    try:d=obj.read_typetree()
                    except (ValueError,AttributeError):continue
                    if obj.type.name=='RectTransform':transform=d
                    if g['m_Name']=='group_paper' and d.get('m_Sprite',{}).get('m_PathID'):
                        sprite=PPtr(**d['m_Sprite'],assetsfile=obj.assets_file).deref().parse_as_object()
                        sprite.image.save(cache/'paper.png');files.append('paper.png')
                    if g['m_Name']=='txtex_content' and d.get('m_fontAsset',{}).get('m_PathID'):
                        font_data(PPtr(**d['m_fontAsset'],assetsfile=obj.assets_file).deref(),'108')
                for child in transform.get('m_Children',[]):
                    t=go.assets_file.objects[child['m_PathID']].read_typetree();walk(go.assets_file.objects[t['m_GameObject']['m_PathID']])
            walk(ptr.deref())
            # Both native paper fonts are in the prefab font dependency.
            for obj in list(env.objects):
                if obj.type.name!='MonoBehaviour':continue
                try:d=obj.read_typetree()
                except ValueError:continue
                if d.get('m_Name')=='YangRenDongZhuShiTi-Regular SDF':font_data(obj,'107')
            st=path.stat();sources[str(path.relative_to(game))]=[st.st_size,st.st_mtime_ns]
            break
        if '108' in fonts:break
    if 'paper.png' not in files or '108' not in fonts:raise FileNotFoundError('原版纸条资源不完整')
    (cache/'paper-fonts.json').write_text(json.dumps(fonts,separators=(',',':')),encoding='utf8');files.append('paper-fonts.json')
    return files,sources

def base_papers(game, table='PaperCfg'):
    if table not in ('PaperCfg', 'GiftEvtCfg'): raise ValueError('Unsupported native table')
    game=Path(game);paths=sorted((game/'StudentAge_Data/StreamingAssets').rglob('*cfgs*.bundle'))+sorted((game/'DLC').rglob('*cfgs*.bundle'))
    if not paths:return {}
    stamp=[[str(p),p.stat().st_size,p.stat().st_mtime_ns] for p in paths]
    cache=game_cache(game) / ('paper-catalog.json' if table == 'PaperCfg' else 'gift-catalog.json')
    if cache.is_file():
        try:
            data=json.loads(cache.read_text(encoding='utf8'))
            if data.get('sources')==stamp:return data['rows']
        except (ValueError,KeyError):pass
    from extract_game_assets import UnityPy
    rows={}
    for path in paths:
        env=UnityPy.load(str(path))
        for name,obj in env.container.items():
            if name.lower().endswith(('/zh-cn/'+table.lower()+'.json','/dlc_zh-cn/'+table.lower()+'.json')):rows.update(json.loads(obj.read().m_Script))
    cache.parent.mkdir(parents=True,exist_ok=True)
    temp=cache.with_suffix('.tmp');temp.write_text(json.dumps({'sources':stamp,'rows':rows},ensure_ascii=False),encoding='utf8');temp.replace(cache)
    return rows
