"""Small picker headshots; prefer the game's authored head asset."""
import hashlib
import os
import secrets
import time
import threading
from pathlib import Path
from PIL import Image

_preview_slots = threading.BoundedSemaphore(4)
_preview_cleanup = threading.Lock()


def preview_image(path, cache):
    """Bound picker image decoding without changing the full-resolution asset."""
    path, cache = Path(path), Path(cache)
    stat = path.stat()
    key = hashlib.sha256((str(path.resolve()) + str((stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))).encode()).hexdigest()
    target = cache / (key + '.webp')
    if target.is_file():
        return target
    with _preview_slots:
        if target.is_file(): return target
        with Image.open(path) as source:
            source.thumbnail((480, 320), Image.Resampling.LANCZOS)
            picture = source.convert('RGBA' if 'A' in source.getbands() else 'RGB')
            cache.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.' + secrets.token_hex(6) + '.tmp')
            try:
                picture.save(temporary, format='WEBP', quality=84, method=3)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
    # A fully warmed library must not evict still-current thumbnails at an
    # arbitrary size limit. The warmup manifest removes only superseded files.
    return target


def head_paths(row, grade=1):
    result = []
    for field in (('url2', 'url') if grade > 1 else ('url', 'url2')):
        values = row.get(field) or []
        for raw in values if isinstance(values, list) else [values]:
            if not isinstance(raw, str) or not raw: continue
            raw = raw.replace('\\', '/')
            p = Path(raw)
            result.append(str(p.with_name(p.stem + '_head' + p.suffix)) if raw.lower().startswith('mods/') else 'role_head/' + raw)
    return result


def crop_head(path, cache):
    """Fallback for custom portraits without an authored head thumbnail."""
    path, cache = Path(path), Path(cache)
    key = hashlib.sha256((str(path) + str(path.stat().st_mtime_ns) + str(path.stat().st_size)).encode()).hexdigest()
    target = cache / (key + '.png')
    if target.is_file(): return target
    with Image.open(path) as source:
        picture = source.convert('RGBA')
        bounds = picture.getbbox() or (0, 0, picture.width, picture.height)
        picture = picture.crop(bounds)
        if picture.height > picture.width * 1.2:
            side = min(picture.width, max(1, round(picture.height * .34)))
            left = (picture.width - side) // 2
            picture = picture.crop((left, 0, left + side, side))
        picture.thumbnail((192, 192))
        canvas = Image.new('RGBA', (192, 192))
        canvas.alpha_composite(picture, ((192-picture.width)//2, (192-picture.height)//2))
        cache.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.' + secrets.token_hex(6) + '.tmp')
        canvas.save(temporary, format='PNG'); os.replace(temporary, target)
    return target


def has_affection(row):
    # RelationData.IsNpcAppearInThisGame excludes init <= 1 (self and extras).
    value = row.get('init') or []
    return bool(isinstance(value, list) and value and isinstance(value[0], (int, float)) and value[0] > 1)


def scene_location(name):
    for label, words in (
        ('学校', ('学校','小学','中学','教学楼','教室','操场','体育馆','校门','校园','实验室','音乐室','美术室','食堂')),
        ('家', ('家','客厅','卧室','厨房','书房','阳台','浴室')),
        ('游戏中心', ('游戏中心','游戏厅','电玩城','街机','网吧')),
        ('商店', ('商店','小卖部','超市','商场','书店','服装店','便利店','市场')),
        ('医院', ('医院','诊所','病房','医务室')),
        ('公园', ('公园','游乐园','动物园','广场','海边','海滩','河边','湖边')),
        ('餐饮', ('餐厅','饭店','咖啡','餐馆','小吃','甜品','烧烤')),
        ('街道', ('街道','马路','路口','车站','公交','地铁','小巷')),
    ):
        if any(word in str(name) for word in words): return label
    return '其他'
