"""Read durable preferences, including pre-onboarding versions, without data loss."""
import json
from pathlib import Path


def load(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return {'onboardingComplete': False}
    if not isinstance(data, dict):
        raise ValueError('用户设置必须是对象，原文件已保留。')
    if 'onboardingComplete' not in data:
        # Old releases persisted preferences and the game location before this
        # flag existed. Upgrading them must not start first-run setup again.
        try:
            location = json.loads(path.with_name('game-location.json').read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            location = {}
        data['onboardingComplete'] = bool(isinstance(location, dict) and location.get('game'))
    return data
