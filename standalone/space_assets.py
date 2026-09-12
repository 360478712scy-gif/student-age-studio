"""Extract KZone's actual signature fonts; no replacement-font downloads."""
import json
import threading
from pathlib import Path
from storage_paths import game_cache
_lock = threading.Lock()

def resources(game):
    from extract_game_assets import UnityPy, bundle_members, connect_dependencies
    from UnityPy.classes import PPtr
    from character_rules import native_rules
    game = Path(game)
    cache = game_cache(game) / 'space-ui-v1'
    manifest = cache / 'manifest.json'
    with _lock:
        if manifest.is_file():
            saved = json.loads(manifest.read_text())
            if saved.get('version') == 4 and all((game/p).is_file() and [(game/p).stat().st_size,(game/p).stat().st_mtime_ns] == stamp for p,stamp in saved['sources'].items()) and all((cache/f).is_file() for f in saved['files']):
                return saved
        folder = game/'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64'
        paths = list(folder.rglob('*.bundle'))
        index = {n.lower():p for p in paths for n in bundle_members(p)}
        wanted = {r['url']:str(r['id']) for r in native_rules(game)['KZoneFontCfg'].values() if not r.get('colors')}
        fonts, missing, sources, glyph_fonts, files = {}, [], {}, {}, []
        cache.mkdir(parents=True,exist_ok=True)
        for path in folder.glob('fonts_assets_*.bundle'):
            env = UnityPy.load(str(path)); connect_dependencies(env,index)
            for obj in list(env.objects):
                if obj.type.name != 'MonoBehaviour': continue
                d = obj.read_typetree(); key = wanted.get(d.get('m_Name'))
                if not key: continue
                if d.get('m_CharacterTable'):
                    from PIL import Image
                    glyphs={str(g['m_Index']):g for g in d['m_GlyphTable']}
                    characters={str(c['m_Unicode']):glyphs[str(c['m_GlyphIndex'])] for c in d['m_CharacterTable'] if str(c['m_GlyphIndex']) in glyphs}
                    atlas_names=[]
                    for i,ptr in enumerate(d['m_AtlasTextures']):
                        tex=PPtr(**ptr,assetsfile=obj.assets_file).deref().read().image.convert('RGBA')
                        alpha=tex.getchannel('A').point(lambda a:max(0,min(255,(a-112)*8)))
                        picture=Image.new('RGBA',tex.size,(255,255,255,255));picture.putalpha(alpha)
                        name=f'font-{key}-{i}.png';picture.save(cache/name);atlas_names.append(name);files.append(name)
                    glyph_fonts[key]={'characters':characters,'face':d['m_FaceInfo'],'atlases':atlas_names}
                try:
                    font = PPtr(**d['m_SourceFontFile'], assetsfile=obj.assets_file).deref().read()
                    data = bytes(font.m_FontData)
                    if not data: raise ValueError('No native source font')
                    name = key+'.otf'; tmp = cache/(name+'.tmp'); tmp.write_bytes(data); tmp.replace(cache/name)
                    fonts[key] = name
                except (KeyError,ValueError,FileNotFoundError,AttributeError) as error:
                    missing.append({'id':key,'reason':str(error)})
        # Dependencies are source inputs too; a game update invalidates this small cache.
        sources = {str(p.relative_to(game)):[p.stat().st_size,p.stat().st_mtime_ns] for p in paths}
        from PIL import Image
        for key,font in glyph_fonts.items():
            sample=Image.new('RGBA',(260,70),(0,0,0,0));x=4
            atlas=None;atlas_index=None
            for char in native_rules(game)['KZoneFontCfg'][key]['name']:
                g=font['characters'].get(str(ord(char)))
                if not g: continue
                idx=g.get('m_AtlasIndex',0)
                if atlas_index!=idx:
                    if atlas: atlas.close()
                    atlas=Image.open(cache/font['atlases'][idx]);atlas_index=idx
                rect=g['m_GlyphRect'];metrics=g['m_Metrics'];rx=rect['m_X'];ry=atlas.height-rect['m_Y']-rect['m_Height']
                tile=atlas.crop((rx,ry,rx+rect['m_Width'],ry+rect['m_Height']))
                sample.alpha_composite(tile,(round(x+metrics['m_HorizontalBearingX']),round(52-metrics['m_HorizontalBearingY'])))
                x+=metrics['m_HorizontalAdvance']
            if atlas:atlas.close()
            name='sample-'+key+'.png';sample.save(cache/name);files.append(name)
        glyph_file=cache/'glyphs.json';glyph_file.write_text(json.dumps(glyph_fonts,separators=(',',':')));files.append('glyphs.json')
        saved = {'version':4,'files':list(fonts.values())+files,'fonts':fonts,'missing':missing,'sources':sources}
        tmp=cache/'manifest.tmp';tmp.write_text(json.dumps(saved));tmp.replace(manifest)
        return saved

def resource_file(game,name):
    saved=resources(game)
    if name not in saved['files']: raise FileNotFoundError('原版签名字体尚不可用')
    return game_cache(Path(game))/'space-ui-v1'/name
