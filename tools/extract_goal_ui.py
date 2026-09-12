"""Read native objective-panel sprites and font files on demand, separately from story UI."""
import json
import threading
from pathlib import Path

_lock = threading.Lock()

def resources(game, cache_dir=None):
    from extract_game_assets import UnityPy, connect_dependencies, bundle_members
    from UnityPy.classes import PPtr
    from PIL import Image, ImageChops
    game = Path(game)
    folder = game / 'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64'
    cache = Path(cache_dir) if cache_dir is not None else game / 'StudentAgeStudio/goal-ui-v1'
    with _lock:
        manifest = cache / 'manifest.json'
        if manifest.is_file():
            try:
                saved = json.loads(manifest.read_text(encoding='utf8'))
                if saved.get('version') == 1 and all((cache / name).is_file() for name in saved['files']) and all((game / p).is_file() and [(game / p).stat().st_size, (game / p).stat().st_mtime_ns] == stamp for p, stamp in saved['sources'].items()):
                    return saved
            except (OSError, ValueError, KeyError):pass
        index = {member.lower():path for path in folder.rglob('*.bundle') for member in bundle_members(path)}
        files, sprites, sources, fonts = [], {}, {}, {}
        cache.mkdir(parents=True, exist_ok=True)
        wanted = {'_bg':'background', 'group_data/Scroll View':'list',
                  'group_intent':'panel', 'Cell_DetailIntentItem/icon_bg':'card',
                  'Cell_DetailIntentItem/group_round':'card-round', 'Cell_DetailIntentItem/pin':'pin',
                  'Cell_DetailIntentItem/group_progress/img_progress':'progress',
                  'Cell_DetailIntentCondItem/img_bg':'condition', 'Cell_DetailIntentCondItem/img_finish':'check',
                  'group_intent/group_round':'round', 'group_reward':'reward',
                  'group_reward/_img':'reward-label', 'group_intent/btn_focus':'button',
                  'group_intent/img_success':'success', 'group_intent/img_fail':'fail'}
        def save_sprite(sprite, key, color=None):
            color = color or {'r':1,'g':1,'b':1,'a':1}
            picture = sprite.image.convert('RGBA')
            tint = Image.new('RGBA', picture.size, tuple(round(255*color.get(c,1)) for c in 'rgba'))
            picture = ImageChops.multiply(picture, tint)
            name = key + '.png';picture.save(cache / name);files.append(name)
            border = sprite.m_Border
            sprites[key] = {'file':name, 'border':[border.w,border.z,border.y,border.x], 'size':list(picture.size)}
        def save_font(obj, data, key):
            if key in fonts:return
            pointer = data.get('m_FontData', {}).get('m_Font') or data.get('m_fontAsset')
            if not pointer or not pointer.get('m_PathID'):return
            font = PPtr(**pointer, assetsfile=obj.assets_file).deref()
            if font.type.name != 'Font':
                font_data = font.read_typetree()
                source = font_data.get('m_SourceFontFile')
                if not source or not source.get('m_PathID'):return
                font = PPtr(**source, assetsfile=font.assets_file).deref()
            raw = bytes(font.parse_as_object().m_FontData)
            if raw:
                name = key + '.ttf';(cache / name).write_bytes(raw);files.append(name);fonts[key] = name
        def walk(go, prefix=''):
            tree = go.read_typetree();path = (prefix + '/' + tree['m_Name']).lstrip('/');transform = {}
            for entry in tree['m_Component']:
                obj = go.assets_file.objects[entry['component']['m_PathID']]
                try: data = obj.read_typetree()
                except ValueError: continue
                if obj.type.name == 'RectTransform':transform = data
                if tree['m_Name'] in ('txt_title', 'txtex_desc', 'txt_Round'):
                    save_font(obj, data, {'txt_title':'title','txtex_desc':'body','txt_Round':'number'}[tree['m_Name']])
                pointer = data.get('m_Sprite', {})
                if not pointer.get('m_PathID'):continue
                for suffix, key in wanted.items():
                    if path == suffix or path.endswith('/' + suffix):
                        sprite = PPtr(**pointer, assetsfile=obj.assets_file).deref().parse_as_object()
                        save_sprite(sprite, key, data.get('m_Color'))
                        if key == 'condition':
                            save_sprite(sprite, 'condition-complete')
                            save_sprite(sprite, 'condition', {'r':238/255,'g':231/255,'b':213/255,'a':1})
            for child in transform.get('m_Children', []):
                t = go.assets_file.objects[child['m_PathID']].read_typetree()
                walk(go.assets_file.objects[t['m_GameObject']['m_PathID']], path)
        for bundle in folder.glob('prefabs_assets__*.bundle'):
            env = UnityPy.load(str(bundle))
            entries = list(env.container.items())
            selected = next((ptr for name,ptr in entries if name.lower().endswith('/detailintentview@main.prefab')), None)
            if selected is None:continue
            connect_dependencies(env, index)
            walk(selected.deref())
            # Selection is switched at runtime; the prefab stores its unselected card.
            for obj in list(env.objects):
                if obj.type.name != 'Sprite':continue
                value = obj.parse_as_object()
                if value.m_Name == 'img_intent_select':save_sprite(value, 'card')
            break
        if not {'panel','card','condition','button','round'}.issubset(sprites):
            raise FileNotFoundError('未找到完整的原版目标界面素材，请确认游戏资源位置。')
        # Track only files loaded for the target prefab and its dependencies.
        def record_sources(assets):
            for asset in assets:
                name = str(getattr(asset, 'name', '')).lower()
                path = index.get(name) or next((p for p in folder.rglob('*.bundle') if p.name.lower() == Path(name).name), None)
                if path and path.is_file():
                    stat = path.stat();sources[str(path.relative_to(game))] = [stat.st_size,stat.st_mtime_ns]
                record_sources((getattr(asset, 'files', None) or {}).values())
        record_sources(env.files.values())
        stat = bundle.stat();sources[str(bundle.relative_to(game))] = [stat.st_size,stat.st_mtime_ns]
        result = {'version':1,'files':list(dict.fromkeys(files)), 'sprites':sprites,'fonts':fonts,'sources':sources,'reference':[1700,1100]}
        temporary = cache / 'manifest.tmp';temporary.write_text(json.dumps(result,ensure_ascii=False),encoding='utf8');temporary.replace(manifest)
        return result

def resource_file(game, name):
    data = resources(game)
    if name not in data['files']:raise FileNotFoundError('未知的目标预览素材')
    return Path(game) / 'StudentAgeStudio/goal-ui-v1' / name
