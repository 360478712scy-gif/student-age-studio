"""Extract the original talk bubble (Cell_NewTalkRoleItemUI.img_bubble_face) into standalone/ui-assets/talk.

Run on a machine with the game installed (the same Python that has the vendored UnityPy):
  python3 -B tools/extract_talk_bubble.py [--game <StudentAge folder>]
Writes bubble.png + emoji.png + manifest.json describing the exact RectTransform layout of the bubble
and its txtex_emoji child, in the game's 2560x1440 canvas units, so the editor's stage can
draw the bubble like NewTalkView does (x 0, y bubbleParm, scaled in over 0.5 s).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'standalone'))
from extract_game_assets import UnityPy, connect_dependencies, bundle_members, DEFAULT_GAME  # noqa: E402
from UnityPy.classes import PPtr  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402


def vec(value, keys):
    return [float(value.get(k, 0)) for k in keys] if isinstance(value, dict) else [0.0 for _ in keys]


def rect_info(data):
    return {'anchoredPosition': vec(data.get('m_AnchoredPosition'), 'xy'), 'sizeDelta': vec(data.get('m_SizeDelta'), 'xy'),
            'pivot': vec(data.get('m_Pivot'), 'xy'), 'anchorMin': vec(data.get('m_AnchorMin'), 'xy'), 'anchorMax': vec(data.get('m_AnchorMax'), 'xy'),
            'scale': vec(data.get('m_LocalScale'), 'xyz')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--game', default=str(DEFAULT_GAME))
    parser.add_argument('--out', default=str(ROOT / 'standalone/ui-assets/talk'))
    args = parser.parse_args()
    game = Path(args.game)
    folder = game / 'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64'
    if not folder.is_dir():
        sys.exit('找不到游戏资源目录：' + str(folder))
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    index = {member.lower(): path for path in folder.rglob('*.bundle') for member in bundle_members(path)}
    found = {}
    names = []

    def walk(go, prefix='', depth=0):
        tree = go.read_typetree(); path = (prefix + '/' + tree['m_Name']).lstrip('/'); transform = {}
        names.append(path)
        if '/img_bubble_face/' in path:
            found.setdefault('bubbleChildren', []).append({'path': path, 'active': bool(tree.get('m_IsActive'))})
        components = []
        for entry in tree['m_Component']:
            obj = go.assets_file.objects[entry['component']['m_PathID']]
            try:
                data = obj.read_typetree()
            except ValueError:
                continue
            components.append((obj, data))
            if obj.type.name == 'RectTransform':
                transform = data
        name = tree['m_Name']
        if name == 'img_bubble_face' and 'bubble' not in found:
            info = rect_info(transform)
            # Unity UI Image and TMP are serialized as MonoBehaviour; retain every component.
            image = next(((obj, data) for obj, data in components if 'm_Sprite' in data), None)
            if image:
                obj, data = image
                pointer = data.get('m_Sprite', {})
                info['imageType'] = data.get('m_Type', 0); info['preserveAspect'] = bool(data.get('m_PreserveAspect', 0))
                color = data.get('m_Color') or {'r': 1, 'g': 1, 'b': 1, 'a': 1}
                info['color'] = [color.get(c, 1) for c in 'rgba']
                if pointer.get('m_PathID'):
                    sprite = PPtr(**pointer, assetsfile=obj.assets_file).deref().parse_as_object()
                    picture = sprite.image.convert('RGBA')
                    tint = Image.new('RGBA', picture.size, tuple(round(255 * color.get(c, 1)) for c in 'rgba'))
                    picture = ImageChops.multiply(picture, tint)
                    picture.save(out / 'bubble.png')
                    border = sprite.m_Border
                    info['sprite'] = {'name': sprite.m_Name, 'size': list(picture.size), 'border': [border.w, border.z, border.y, border.x],
                                      'pixelsPerUnit': getattr(sprite, 'm_PixelsToUnits', 100)}
            info['path'] = path
            found['bubble'] = info
        if name == 'txtex_emoji':
            info = rect_info(transform); info['path'] = path
            for obj, data in components:
                if 'm_fontSize' in data:
                    info['fontSize'] = data.get('m_fontSize'); info['alignment'] = data.get('m_HorizontalAlignment', data.get('m_textAlignment'))
                    info['verticalAlignment'] = data.get('m_VerticalAlignment')
                    info['fontSizeMax'] = data.get('m_fontSizeMax'); info['autoSize'] = data.get('m_enableAutoSizing')
                    info['margin'] = vec(data.get('m_margin'), 'xyzw')
                    font = PPtr(**data['m_fontAsset'], assetsfile=obj.assets_file).deref().read_typetree()
                    info['fontFace'] = font['m_FaceInfo']
                    sprite_obj = PPtr(**data['m_spriteAsset'], assetsfile=obj.assets_file).deref()
                    sprite_data = sprite_obj.read_typetree()
                    info['spriteFace'] = sprite_data['m_FaceInfo']
                    info['characters'] = sprite_data['m_SpriteCharacterTable']
                    info['glyphs'] = sprite_data['m_SpriteGlyphTable']
                    atlas = PPtr(**sprite_data['spriteSheet'], assetsfile=sprite_obj.assets_file).deref().parse_as_object().image
                    atlas.save(out / 'emoji.png'); info['atlasSize'] = list(atlas.size)
            found['emoji'] = info
        if name in ('Cell_NewTalkRoleItem', 'Cell_NewTalkRoleItemUI') or depth == 0:
            found.setdefault('cell', {**rect_info(transform), 'path': path})
        for child in transform.get('m_Children', []):
            t = go.assets_file.objects[child['m_PathID']].read_typetree()
            walk(go.assets_file.objects[t['m_GameObject']['m_PathID']], path, depth + 1)

    sources = {}
    for bundle in sorted(folder.glob('prefabs_assets_cell_*.bundle')):
        env = UnityPy.load(str(bundle))
        entries = list(env.container.items())
        selected = [(n, p) for n, p in entries if 'newtalkroleitem' in n.lower() and n.lower().endswith('.prefab')]
        if not selected:
            selected = [(n, p) for n, p in entries if n.lower().endswith('newtalkview@main.prefab')]
        if not selected:
            continue
        connect_dependencies(env, index)
        for name, ptr in selected:
            print('读取预制体：', name)
            walk(ptr.deref())
            if 'bubble' in found:
                break
        stat = bundle.stat(); sources[str(bundle.relative_to(game))] = [stat.st_size, stat.st_mtime_ns]
        if 'bubble' in found:
            break
    if 'bubble' not in found or 'sprite' not in found['bubble']:
        print('未找到 img_bubble_face。已遍历的节点：')
        for n in names[:200]:
            print('  ', n)
        sys.exit(2)
    manifest = {'version': 2, 'files': ['bubble.png', 'emoji.png'], 'reference': [2560, 1440], 'source': found['bubble']['path'],
                'bubble': found['bubble'], 'emoji': found.get('emoji', {}), 'cell': found.get('cell', {}), 'bubbleChildren': found.get('bubbleChildren', []), 'sources': sources}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'source': manifest['source'], 'bubble': found['bubble'], 'emojiCount': len(found.get('emoji', {}).get('characters', []))}, ensure_ascii=False, indent=2))
    print('已写入', out)


if __name__ == '__main__':
    main()
