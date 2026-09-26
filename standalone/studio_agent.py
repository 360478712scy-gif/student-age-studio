"""Programmatic access to the editor for scripts and AI agents.

The CLI (studio_cli.py) and the MCP server (studio_mcp.py) are thin layers over this module. It drives the
editor's own StudioStore in-process, so reads, id rules, ownership, revision checks, save warnings and
pre-save backups are exactly the editor's: nothing here writes a configuration file directly.

Every write loads the mod at its current revision, applies the change to the same document the editor
edits, and saves through the editor's save pipeline with that revision. If the mod changed in between
(another window, the game, a person in the editor), the save is refused rather than overwriting.
Validation warnings are returned to the caller; they are only accepted when passed back explicitly.
"""
from __future__ import annotations

import copy
import random
import re
import uuid
from pathlib import Path

import server
import save_review
from game_locator import GameLocations

NARRATOR, PROTAGONIST = -1, 0
MAX_ID = 2147483647
# Native TalkAxis: Left = 1, Right = 2, Mid = 3 (the editor shows them as 左侧 / 右侧 / 中间).
AXES = {'左': 1, '左侧': 1, '左边': 1, 'left': 1, '右': 2, '右侧': 2, '右边': 2, 'right': 2,
        '中': 3, '中间': 3, '中央': 3, 'mid': 3, 'middle': 3, 'center': 3, 'centre': 3}
AXIS_NAMES = {1: '左', 2: '右', 3: '中'}
# Standard expression slots, as the editor names them. Mods may name their own in ModFaceCfg.
FACES = ['默认', '高兴', '生气', '伤心', '害羞', '喜欢', '认真', '疑惑', '惊讶', '得意', '微笑', '坏笑', '担心', '害怕', '难过', '咆哮', '窘迫', '不满', '冷笑', '无语', '苦笑']
ENTRY, EXIT = (1001, 1002, 1003), (2001, 2002)
ACTION_NAMES = {1001: '直接登场', 1002: '渐显登场', 1003: '从下方登场', 2001: '滑动退场', 2002: '渐隐退场', 3000: '切换表情', 3001: '跳跃',
                3002: '摇晃', 3003: '调整大小', 3004: '水平移动', 3005: '转身', 3006: '更换服装', 3007: '翻转', 3008: '垂直移动', 3009: '气泡表情', 3012: '黑影', 3013: '取消黑影'}
EVENT_FIELDS = {'title', 'type', 'npc', 'mapId', 'rate', 'maxcount', 'condition', 'effect', 'displayType', 'content', 'desc'}
TALK_FIELDS = {'content', 'roleIds', 'roleName', 'bg', 'audio', 'effect', 'effect2', 'check', 'screenEffect', 'roles', 'nextTalk', 'nextTalk2', 'option', 'showTxt'}


class AgentError(Exception):
    def __init__(self, message, *, warnings=None, code='error'):
        super().__init__(message)
        self.message, self.warnings, self.code = message, warnings or [], code


def _int(value, label):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise AgentError(f'{label} 应为整数：{value!r}')
    if not 0 <= number <= MAX_ID:
        raise AgentError(f'{label} 超出范围：{number}')
    return number


def _ids(value):
    return [int(v) for v in value if isinstance(v, int) or isinstance(v, str) and v.isdigit()] if isinstance(value, list) else []


class Studio:
    """One editor data session. Mods, game and workshop default to the editor's saved locations."""

    def __init__(self, mods=None, workshop=None, game=None):
        # Unspecified locations follow the editor's saved settings; explicit ones override them.
        active = GameLocations().active or {}
        game = game or active.get('game') or server.DEFAULT_GAME
        mods = mods or active.get('mods') or server.DEFAULT_MODS
        workshop = workshop or active.get('workshop') or server.DEFAULT_WORKSHOP
        if not Path(game).exists():
            raise AgentError('找不到游戏目录。请先打开编辑器完成设置，或用 --game 指定游戏目录。', code='not_configured')
        extra = active.get('extraMods', []) if active and str(Path(mods)) == str(Path(active.get('mods', ''))) else ()
        self.store = server.StudioStore(mods, workshop, game, extra, migrate_cache=False)

    # ---------- helpers ----------
    def _call(self, fn, *args):
        try:
            return fn(*args)
        except server.ApiError as error:
            raise AgentError(error.message, warnings=getattr(error, 'warnings', None), code=error.code) from None

    def _project(self, mod):
        rows = self._project_rows()
        text = str(mod or '').strip()
        if not text:
            raise AgentError('请指定模组（编号或名称）。可先用 mods 查看列表。')
        for row in rows:
            if row.get('id') == text or row.get('packageId') == text:
                return row
        exact = [row for row in rows if row.get('name') == text]
        if len(exact) == 1:
            return exact[0]
        partial = [row for row in rows if text.casefold() in str(row.get('name', '')).casefold()]
        if len(partial) == 1:
            return partial[0]
        candidates = exact or partial
        if candidates:
            raise AgentError('模组名称不唯一，请用编号指定：' + '；'.join(f"{r['id']} {r.get('name')}" for r in candidates[:10]))
        raise AgentError(f'找不到模组：{text}。可先用 mods 查看列表。')

    def _load(self, mod):
        project = self._project(mod)
        return project, self._call(self.store.load, project['id'])

    def _person_name(self, doc, ident):
        if ident == NARRATOR:
            return '旁白'
        row = doc.get('persons', {}).get(str(ident))
        return (row or {}).get('name') or f'人物 {ident}'

    def _speaker(self, doc, value):
        """Resolve a speaker given as an id, 旁白/narrator, 主角/protagonist, or a person name."""
        if value is None or value == '':
            return NARRATOR
        if isinstance(value, int) or isinstance(value, str) and re.fullmatch(r'-?\d+', value.strip()):
            ident = int(value)
            if ident != NARRATOR and str(ident) not in doc.get('persons', {}):
                raise AgentError(f'找不到人物编号 {ident}。可用 persons 查看。')
            return ident
        text = str(value).strip()
        if text.casefold() in ('旁白', 'narrator', 'narration'):
            return NARRATOR
        if text.casefold() in ('主角', '玩家', 'protagonist', 'player'):
            return PROTAGONIST
        matches = [int(k) for k, row in doc.get('persons', {}).items() if row.get('name') == text]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AgentError(f'名为「{text}」的人物有多个，请用编号：' + '、'.join(map(str, matches)))
        raise AgentError(f'找不到名为「{text}」的人物。可用 persons 查看，或直接写人物编号。')

    # ---------- staging: positions, expressions, backgrounds, sound ----------
    def _axis(self, value):
        if isinstance(value, str) and value.strip().casefold() in AXES:
            return AXES[value.strip().casefold()]
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = None
        if number not in (1, 2, 3):
            raise AgentError(f'登场位置无效：{value!r}。请写 "左"、"中"、"右"（或原版编号 1 左 / 2 右 / 3 中）。')
        return number

    def _expression(self, doc, person, value):
        """An expression by number (0–99) or by name: the standard names, or ones this person's faces define."""
        if isinstance(value, int) or isinstance(value, str) and value.strip().isdigit():
            number = int(value)
            if not 0 <= number <= 99:
                raise AgentError(f'表情编号应在 0–99：{number}')
            return number
        text = str(value or '').strip()
        own = sorted({int(k) % 100 for k, row in doc.get('faces', {}).items()
                      if str(k).isdigit() and int(k) // 1000 == person and (row or {}).get('name') == text})
        if own:
            return own[0]
        if text in FACES:
            return FACES.index(text)
        raise AgentError(f'找不到表情「{text}」。可用 list_assets(kind="expressions", person=…) 查看，或直接写表情编号。')

    def _audio_rows(self, project_id):
        project = self._call(self.store.project, project_id)
        local = server.read_json(server.safe_path(project.path, 'Cfgs/zh-cn/AudioCfg.json'), {})
        rows = {**self.store.catalog_rows('AudioCfg'), **(local if isinstance(local, dict) else {})}
        return {str(k): r for k, r in rows.items() if isinstance(r, dict) and str(k).isdigit()}

    def _audio(self, rows, value, kind):
        """Music (AudioCfg type 1) or a sound effect (type 2/3), by id or name."""
        wanted = (1,) if kind == 'music' else (2, 3)
        label = '背景音乐' if kind == 'music' else '音效'
        if isinstance(value, int) or isinstance(value, str) and value.strip().isdigit():
            key = str(int(value))
            if key not in rows:
                raise AgentError(f'找不到{label} {key}。可用 list_assets 查看。')
            return int(key)
        import asset_labels
        text = str(value or '').strip()
        matches = [k for k, r in rows.items() if r.get('type', 1) in wanted and text in (r.get('name'), asset_labels.asset_name(r, 'audio'))]
        if not matches:
            matches = [k for k, r in rows.items() if r.get('type', 1) in wanted and text and text.casefold() in str(r.get('url') or '').casefold()]
        if len(matches) == 1 or matches and all(rows[m].get('url') == rows[matches[0]].get('url') for m in matches):
            return int(matches[0])
        if matches:
            raise AgentError(f'名为「{text}」的{label}有多个，请用编号：' + '、'.join(matches[:10]))
        raise AgentError(f'找不到{label}「{text}」。可用 list_assets(kind="{kind}") 查看。')

    def _background(self, doc, value):
        """A background by id or name/file name. 0 keeps the current one."""
        if isinstance(value, int) or isinstance(value, str) and re.fullmatch(r'-?\d+', value.strip()):
            number = int(value)
            if number in (0, -2) or str(number) in doc.get('backgrounds', {}):
                return number
            raise AgentError(f'找不到背景 {number}。可用 list_assets(kind="backgrounds") 查看。')
        import asset_labels
        text = str(value or '').strip().casefold()
        rows = doc.get('backgrounds', {})
        named = [k for k, r in rows.items() if text == asset_labels.asset_name(r, 'background').casefold()]
        files = [k for k, r in rows.items() if text and text in str((r or {}).get('url') or '').casefold()]
        matches = named or files
        if len(matches) == 1:
            return int(matches[0])
        if matches:
            raise AgentError(f'背景「{value}」匹配多个，请用编号：' + '、'.join(matches[:10]))
        raise AgentError(f'找不到背景「{value}」。可用 list_assets(kind="backgrounds") 查看。')

    def _stage_row(self, doc, row, present, background):
        """Follow one line the way the game's NewTalkView does: background changes clear the cast
        (except -2), a line without actions brings its speakers in, entries/exits change the cast."""
        if not str(row.get('content') or '').strip():
            return background  # the game skips empty lines entirely
        bg = int(row.get('bg') or 0) if str(row.get('bg') or 0).lstrip('-').isdigit() else 0
        if bg in (-1, -2) or bg > 0 and bg != background and str(bg) in doc.get('backgrounds', {}):
            if bg != -2:
                present.clear()
            if bg > 0:
                background = bg
        actions = [a for a in row.get('roles') or [] if isinstance(a, list) and a]
        if not actions:
            for speaker in _ids(row.get('roleIds')):
                if speaker >= 0:
                    present.setdefault(speaker, None)
        for action in actions:
            try:
                person, code = int(action[0]), int(action[1]) if len(action) > 1 else 0
            except (TypeError, ValueError):
                continue
            if code in ENTRY:
                present[person] = int(action[3]) if len(action) > 3 and str(action[3]).isdigit() else present.get(person)
            elif code in EXIT:
                present.pop(person, None)
            elif code >= 3000:
                present.setdefault(person, None)
        return background

    def _stage_before(self, doc, event_id, anchor, include_anchor=True):
        """Who is on stage (and where) when the line after `anchor` starts, along a path from the event start."""
        present, background = {}, 0
        if anchor is None:
            return present, background
        row = doc.get('events', {}).get(str(event_id), {})
        starts = [*_ids(row.get('talkId'))]
        parent, queue = {t: None for t in starts}, list(starts)
        while queue and anchor not in parent:
            tid = queue.pop(0)
            talk = doc['talks'].get(str(tid))
            if not talk:
                continue
            nxt = [*_ids(talk.get('nextTalk')), *_ids(talk.get('nextTalk2'))]
            for oid in _ids(talk.get('option')):
                nxt += _ids(doc.get('options', {}).get(str(oid), {}).get('talkId'))
            for target in nxt:
                if target not in parent:
                    parent[target] = tid
                    queue.append(target)
        path, cursor = [], anchor if anchor in parent else None
        while cursor is not None:
            path.append(cursor)
            cursor = parent[cursor]
        path = list(reversed(path or [anchor]))
        for tid in path if include_anchor else path[:-1]:
            background = self._stage_row(doc, doc['talks'].get(str(tid), {}), present, background)
        return present, background

    def _persons(self, doc, value, speaker):
        if value is True:
            return [speaker] if speaker >= 0 else []
        values = value if isinstance(value, list) else [value]
        return [self._speaker(doc, v) for v in values if v not in (None, False, '')]

    def _raw_actions(self, doc, value):
        if not isinstance(value, list) or not all(isinstance(a, list) and len(a) >= 2 for a in value):
            raise AgentError('actions 应为动作数组的列表，如 [["小雅", 3001, 1, 0, 1]]（人物, 动作编号, 参数…）。')
        out = []
        for action in value:
            person = self._speaker(doc, action[0])
            try:
                numbers = [float(v) if isinstance(v, float) else int(v) for v in action[1:]]
            except (TypeError, ValueError):
                raise AgentError(f'动作参数应为数字：{action!r}')
            out.append([person, *numbers])
        return out

    def _staging(self, doc, spec, speaker, present, background, *, audio_rows=None, project_id=None):
        """Actions and background for one line, given who is on stage. Returns (roles, bg, background, sound)."""
        actions, bg = [], 0
        if spec.get('background') not in (None, ''):
            bg = self._background(doc, spec['background'])
            if bg == -2 or bg > 0 and bg != background:
                if bg != -2:
                    present.clear()  # a new background clears the cast, as in the game
                background = bg if bg > 0 else background
        exits = self._persons(doc, spec['exit'], speaker) if spec.get('exit') else []
        enter = spec.get('enter')
        if enter not in (None, False, '', 0) and speaker >= 0:
            axis = self._axis(enter)
            # Someone already standing there stays put: re-entering would restart their entrance.
            if present.get(speaker, 0) != axis or speaker not in present:
                actions.append([speaker, 1002, 1, axis, 0])
            present[speaker] = axis
        if spec.get('expression') not in (None, '') and speaker >= 0:
            actions.append([speaker, 3000, self._expression(doc, speaker, spec['expression'])])
        for person, value in (spec.get('expressions') or {}).items() if isinstance(spec.get('expressions'), dict) else ():
            actions.append([self._speaker(doc, person), 3000, self._expression(doc, self._speaker(doc, person), value)])
        if spec.get('actions'):
            actions += self._raw_actions(doc, spec['actions'])
        for person in exits:
            if person in present or any(a[0] == person for a in actions):
                actions.append([person, 2002, 0])
        # Lines with actions only run those: the game no longer brings the speaker in by itself.
        if actions and speaker >= 0 and speaker not in present and not any(a[0] == speaker for a in actions):
            actions.insert(0, [speaker, 1001])
        row = {'content': spec.get('text') or ' ', 'roleIds': [speaker], 'roles': actions, 'bg': bg}
        self._stage_row(doc, {**row, 'bg': 0}, present, background)
        sound = None
        if spec.get('sound') not in (None, '', [], 0):
            rows = audio_rows if audio_rows is not None else self._audio_rows(project_id)
            sound = [self._audio(rows, v, 'sound') for v in (spec['sound'] if isinstance(spec['sound'], list) else [spec['sound']])]
        return actions, bg, background, sound

    def _music(self, rows, value):
        """{"name"|"id", "loop", "volume"} or a bare name/id."""
        spec = value if isinstance(value, dict) else {'id': value}
        target = spec.get('id', spec.get('name'))
        volume = spec.get('volume', 1)
        if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 1:
            raise AgentError('音量应在 0 到 1 之间。')
        return {'audioId': self._audio(rows, target, 'music'), 'loop': bool(spec.get('loop', True)), 'volume': volume}

    def _line_view(self, doc, tid):
        row = doc['talks'].get(str(tid), {})
        speaker = (_ids(row.get('roleIds')) or [NARRATOR])[0]
        view = {'id': int(tid), 'speaker': self._person_name(doc, speaker), 'speakerId': speaker, 'text': row.get('content') or ''}
        if row.get('roleName'):
            view['displayName'] = row['roleName']
        options = []
        for oid in _ids(row.get('option')):
            option = doc.get('options', {}).get(str(oid), {})
            options.append({'id': oid, 'text': option.get('content') or '', 'goto': _ids(option.get('talkId')),
                            **({'condition': option['precondition']} if option.get('precondition') else {}),
                            **({'effect': option['effect']} if option.get('effect') else {})})
        if options:
            view['options'] = options
        nxt = _ids(row.get('nextTalk'))
        if nxt:
            view['next'] = nxt
        if row.get('check'):
            view['check'] = row['check']
            view['nextIfFailed'] = _ids(row.get('nextTalk2'))
        if row.get('effect'):
            view['effect'] = row['effect']
        bg = row.get('bg') or 0
        if bg:
            import asset_labels
            view['background'] = {'id': bg, 'name': asset_labels.asset_name(doc.get('backgrounds', {}).get(str(bg), {}), 'background') if bg > 0 else '保留人物的黑场' if bg == -2 else '黑场'}
        if row.get('roles'):
            view['stage'] = self._describe_actions(doc, row['roles'])
        screen = row.get('screenEffect') or []
        if screen and int(screen[0]) == 4015 and len(screen) > 1:
            view['cg'] = {'id': screen[1], 'name': (doc.get('cgs', {}).get(str(screen[1])) or {}).get('name')}
        elif screen and int(screen[0]) == 4017:
            view['cg'] = 'end'
        cues = doc.get('audioCues') or {}
        if cues.get('sfx', {}).get(str(tid)):
            view['sound'] = [c.get('audioId') for c in cues['sfx'][str(tid)]]
        music = next((g for g in cues.get('bgm', []) if int(tid) in [int(i) for i in g.get('talkIds', [])]), None)
        if music and int(music['talkIds'][0]) == int(tid):
            view['musicStarts'] = music.get('audioId')
        return view

    def _describe_actions(self, doc, actions):
        out = []
        for action in actions or []:
            if not isinstance(action, list) or len(action) < 2:
                continue
            person, code = action[0], int(action[1])
            text = f'{self._person_name(doc, person)} {ACTION_NAMES.get(code, "动作 " + str(code))}'
            if code in ENTRY and len(action) > 3:
                text += f'（{AXIS_NAMES.get(int(action[3]), action[3])}）'
            elif code == 3000 and len(action) > 2:
                face = int(action[2])
                text += f'：{FACES[face] if 0 <= face < len(FACES) else face}'
            out.append({'text': text, 'raw': action})
        return out

    def _walk(self, doc, starts):
        order, seen, stack = [], set(), list(reversed(starts))
        while stack:
            tid = stack.pop()
            if tid in seen or str(tid) not in doc['talks']:
                continue
            seen.add(tid)
            order.append(tid)
            row = doc['talks'][str(tid)]
            nxt = [*_ids(row.get('nextTalk')), *_ids(row.get('nextTalk2'))]
            for oid in _ids(row.get('option')):
                option = doc.get('options', {}).get(str(oid), {})
                nxt += [*_ids(option.get('talkId')), *_ids(option.get('talkId2'))]
            stack.extend(reversed(nxt))
        return order

    def _event_row(self, doc, event_id):
        row = doc.get('events', {}).get(str(event_id))
        if not row:
            raise AgentError(f'找不到事件 {event_id}。可用 events 查看。')
        return row

    def _is_local(self, doc, key, ident):
        return str(ident) in {str(v) for v in doc.get('localIds', {}).get(key, [])}

    # ---------- reads ----------
    def _project_rows(self):
        return [project.public() for project in self._call(self.store.project_list)]

    def mods(self):
        return [{'id': r.get('id'), 'name': r.get('name'), 'readOnly': bool(r.get('readOnly')), 'source': r.get('source')}
                for r in self._project_rows()]

    def summary(self, mod):
        project, doc = self._load(mod)
        local = doc.get('localIds', {})
        return {'mod': {'id': project['id'], 'name': project.get('name'), 'readOnly': bool(project.get('readOnly'))},
                'revision': doc.get('revision'),
                'ownCounts': {key: len(value) for key, value in local.items() if value},
                'warnings': doc.get('warnings', [])}

    def events(self, mod, query=None, include_original=False, limit=50, offset=0):
        _project, doc = self._load(mod)
        rows = []
        for key, row in doc.get('events', {}).items():
            local = self._is_local(doc, 'events', key)
            if not include_original and not local:
                continue
            first = next(iter(_ids(row.get('talkId'))), None)
            first_text = (doc['talks'].get(str(first), {}).get('content') or '') if first else ''
            item = {'id': int(key), 'title': row.get('title') or '', 'type': row.get('type'), 'npc': row.get('npc'),
                    'mapId': row.get('mapId'), 'firstLine': first_text[:60], 'own': local}
            if query and not any(str(query).casefold() in str(v).casefold() for v in (key, item['title'], first_text)):
                continue
            rows.append(item)
        rows.sort(key=lambda r: r['id'])
        return {'total': len(rows), 'offset': offset, 'events': rows[offset:offset + limit]}

    def event(self, mod, event_id):
        _project, doc = self._load(mod)
        event_id = _int(event_id, '事件编号')
        row = self._event_row(doc, event_id)
        starts = [*_ids(row.get('talkId'))]
        for oid in _ids(row.get('options')):
            option = doc.get('options', {}).get(str(oid), {})
            starts += _ids(option.get('talkId'))
        lines = [self._line_view(doc, tid) for tid in self._walk(doc, starts)]
        fields = {k: row.get(k) for k in ('title', 'type', 'npc', 'mapId', 'rate', 'maxcount', 'condition', 'effect') if k in row}
        return {'id': event_id, **fields, 'own': self._is_local(doc, 'events', event_id),
                'npcName': self._person_name(doc, row['npc']) if row.get('npc') else None, 'lines': lines}

    def line(self, mod, talk_id):
        _project, doc = self._load(mod)
        talk_id = _int(talk_id, '对话编号')
        if str(talk_id) not in doc['talks']:
            raise AgentError(f'找不到对话 {talk_id}。')
        owners = doc.get('talkOwners', {}).get(str(talk_id), [])
        return {**self._line_view(doc, talk_id), 'events': owners, 'own': self._is_local(doc, 'talks', talk_id),
                'raw': doc['talks'][str(talk_id)]}

    def search(self, mod, text, include_original=False, limit=50):
        _project, doc = self._load(mod)
        needle = str(text or '').casefold()
        if not needle:
            raise AgentError('请提供要搜索的文字。')
        found = []
        for key, row in doc['talks'].items():
            if not include_original and not self._is_local(doc, 'talks', key):
                continue
            if needle in str(row.get('content') or '').casefold():
                found.append({**self._line_view(doc, key), 'events': doc.get('talkOwners', {}).get(key, [])})
                if len(found) >= limit:
                    break
        return {'count': len(found), 'lines': found}

    def persons(self, mod, query=None, limit=100):
        _project, doc = self._load(mod)
        rows = [{'id': int(k), 'name': r.get('name') or '', 'own': self._is_local(doc, 'persons', k)}
                for k, r in doc.get('persons', {}).items() if str(k).lstrip('-').isdigit()]
        if query:
            rows = [r for r in rows if str(query).casefold() in r['name'].casefold() or str(query) == str(r['id'])]
        rows.sort(key=lambda r: r['id'])
        return {'total': len(rows), 'persons': rows[:limit], 'special': {'旁白': NARRATOR, '主角': PROTAGONIST}}

    def commands(self, mod, kind='condition', query=None, limit=60):
        """Condition/effect templates the editor knows, to compose event conditions and effects."""
        project = self._project(mod)
        if kind not in ('condition', 'effect'):
            raise AgentError('kind 只能是 condition 或 effect。')
        catalog = self._call(self.store.command_catalog, project['id'])
        catalog = catalog.get('commands', catalog)
        rows = []
        for row in catalog.get(kind, []):
            if not isinstance(row, dict):
                continue
            item = {'label': row.get('label'), 'template': row.get('template'), 'category': row.get('category'),
                    'description': row.get('description'),
                    'parameters': [{k: p.get(k) for k in ('index', 'label', 'type', 'range', 'min', 'max', 'options') if k in p} for p in row.get('parameters', []) if isinstance(p, dict)]}
            if query and not any(str(query).casefold() in str(v or '').casefold() for v in (item['label'], item['category'], item['description'])):
                continue
            rows.append(item)
        return {'kind': kind, 'total': len(rows), 'commands': rows[:limit]}

    def table(self, mod, name, ids=None, query=None, own_only=True, limit=50):
        project = self._project(mod)
        data = self._call(self.store.table, project['id'], name)
        rows = data.get('rows', {})
        local = {str(v) for v in data.get('localIds', [])}
        keys = [str(i) for i in ids] if ids else [k for k in rows if not own_only or k in local]
        out = []
        for key in keys:
            row = rows.get(key)
            if row is None:
                continue
            if query and str(query).casefold() not in str(row).casefold():
                continue
            out.append(row)
            if len(out) >= limit:
                break
        return {'table': data.get('name', name), 'revision': data.get('revision'), 'total': len(keys), 'rows': out,
                'fields': [f.get('name') for f in data.get('schema', {}).get('fields', []) if isinstance(f, dict)]}

    # ---------- writes ----------
    def _new_event_id(self, project, doc):
        registry = self._call(self.store.record_ids.public, project['id'])
        used = {int(v) for values in registry.get('tables', {}).values() for v in values if str(v).isdigit()}
        used |= {int(v) for v in registry.get('reservedIds', []) if str(v).isdigit()}
        used |= {int(k) for k in doc.get('events', {}) if str(k).isdigit()}
        rng = random.Random()
        for _ in range(20000):
            candidate = rng.randint(1000000, 1999999)
            if candidate not in used:
                return candidate
        raise AgentError('找不到可用的事件编号。')

    def _free_ids(self, doc, table, block, factor, count):
        taken = {int(k) for k in doc.get(table, {}) if str(k).isdigit()}
        taken |= {int(v) for v in doc.get('catalogIds', {}).get(table, []) if str(v).isdigit()}
        taken |= {int(v) for v in doc.get('deletedIds', []) if str(v).isdigit()}
        found, n = [], 0
        while len(found) < count:
            n += 1
            if n >= factor:
                raise AgentError(f'事件 {block} 下的{"对话" if table == "talks" else "选项"}编号已用尽（每个事件最多 {factor - 1} 个）。')
            ident = block * factor + n
            if ident not in taken:
                found.append(ident)
        return found

    def _build_lines(self, doc, event_id, specs, then=None, stage=None, project_id=None):
        """Turn line specs into talk (and option) rows chained in order.

        Returns (first id, rows, options, order, cues): cues holds the lines' sound effects and music starts."""
        if not isinstance(specs, list) or not specs:
            raise AgentError('lines 需要至少一句对话。')
        flat = self._flatten(specs)
        # Numbers follow reading order (a line, then its branches, then the next line), as the editor numbers them.
        numbers = dict(zip(map(id, flat), self._free_ids(doc, 'talks', event_id, 1000, len(flat))))
        options_needed = sum(len(s.get('options') or []) for s in flat if isinstance(s, dict))
        option_ids = self._free_ids(doc, 'options', event_id, 100, options_needed) if options_needed else []
        talks, options, cues = {}, {}, {'sfx': {}, 'music': {}}
        order = [numbers[id(spec)] for spec in flat]
        needs_audio = any(isinstance(s, dict) and (s.get('sound') or s.get('music')) for s in flat)
        audio_rows = self._audio_rows(project_id) if needs_audio and project_id else {}

        def chain(items, continuation, present, background):
            ids_here = [numbers[id(spec)] for spec in items]
            for index, (spec, tid) in enumerate(zip(items, ids_here)):
                if not isinstance(spec, dict) or not isinstance(spec.get('text', ''), str):
                    raise AgentError('每句对话应为 {"speaker": 人物, "text": 文字}。')
                after = ids_here[index + 1] if index + 1 < len(ids_here) else continuation
                row = server.inert_talk(tid, [after] if after else [])
                speaker = self._speaker(doc, spec.get('speaker'))
                row.update(content=spec.get('text', ''), roleIds=[speaker])
                if spec.get('displayName'):
                    row['roleName'] = str(spec['displayName'])
                actions, bg, background, sound = self._staging(doc, spec, speaker, present, background, audio_rows=audio_rows)
                row['roles'] = actions
                if bg:
                    row['bg'] = bg
                if sound:
                    cues['sfx'][str(tid)] = [{'audioId': a, 'volume': 1} for a in sound]
                if spec.get('music') not in (None, ''):
                    cues['music'][tid] = self._music(audio_rows, spec['music'])
                talks[str(tid)] = row
                branches = spec.get('options') or []
                if branches:
                    row['nextTalk'] = []
                    rejoin = after if spec.get('rejoin', True) else None
                    for option in branches:
                        if not isinstance(option, dict) or not str(option.get('text', '')).strip():
                            raise AgentError('每个选项需要 text（选项文字），可选 lines（选择后的对话）。')
                        oid = option_ids.pop(0)
                        target = chain(option['lines'], rejoin, dict(present), background) if option.get('lines') else rejoin
                        options[str(oid)] = {'id': oid, 'content': option['text'], 'talkId': [target] if target else [],
                                             'talkId2': [], 'effect': option.get('effect', []), 'effect2': [], 'check': [],
                                             'precondition': option.get('condition', [])}
                        row['option'].append(oid)
            return ids_here[0] if ids_here else continuation

        present, background = stage if stage else ({}, 0)
        first = chain(specs, then, dict(present), background)
        return first, talks, options, order, cues

    def _apply_cues(self, doc, order, cues):
        """Record sound effects, and music ranges running from each music line to the next one."""
        audio = doc.setdefault('audioCues', {'version': 1, 'sfx': {}, 'bgm': []})
        audio.setdefault('sfx', {}); audio.setdefault('bgm', [])
        audio['sfx'].update(cues['sfx'])
        starts = [i for i, tid in enumerate(order) if tid in cues['music']]
        for n, index in enumerate(starts):
            stop = starts[n + 1] if n + 1 < len(starts) else len(order)
            music = cues['music'][order[index]]
            audio['bgm'].append({'id': 'ai-' + uuid.uuid4().hex[:16], **music, 'talkIds': order[index:stop]})

    def _flatten(self, specs):
        out = []
        for spec in specs or []:
            out.append(spec)
            for option in (spec.get('options') or []) if isinstance(spec, dict) else []:
                out += self._flatten(option.get('lines') if isinstance(option, dict) else [])
        return out

    def _snapshot(self, doc):
        return copy.deepcopy({**{k: doc.get(k) for k in server.TABLES if k != 'talks'}, 'audioCues': doc.get('audioCues')})

    def _save(self, project, doc, before, *, order=None, talk_rows=None, deleted_talks=None, confirm=None, dry_run=False, summary=None):
        payload = {'projectId': project['id'], 'revision': doc['revision']}
        for key in server.TABLES:
            if key == 'talks':
                continue
            if doc.get(key) != before.get(key):
                payload[key] = doc[key]
        if doc.get('audioCues') != before.get('audioCues'):
            payload['audioCues'] = doc['audioCues']
        if talk_rows or deleted_talks:
            payload['talkPatch'] = {'version': 1, 'upsert': talk_rows or {}, 'deleted': list(deleted_talks or [])}
        if order is not None:
            payload['order'] = order
        if confirm:
            payload['_confirmedSaveWarnings'] = list(confirm)
        changed = sorted(k for k in payload if k not in ('projectId', 'revision', '_confirmedSaveWarnings'))
        if dry_run:
            return {'dryRun': True, 'wouldChange': changed, **(summary or {})}
        try:
            result = save_review.perform(self.store.save, payload, server.ApiError)
        except server.ApiError as error:
            if error.code == 'save_warnings':
                raise AgentError('保存前需要确认以下警告；确认无误后，把 warnings 原样传回 confirm 再执行一次。',
                                 warnings=getattr(error, 'warnings', []), code='save_warnings') from None
            raise AgentError(error.message, code=error.code) from None
        return {'saved': True, 'revision': result.get('revision'), 'changed': changed,
                'warnings': result.get('warnings', []), **(summary or {})}

    def create_event(self, mod, title, lines, type=1, npc=0, map_id=0, rate=1, maxcount=1, condition=None, effect=None,
                     event_id=None, confirm=None, dry_run=False):
        project, doc = self._load(mod)
        if project.get('readOnly'):
            raise AgentError('订阅模组只读，不能修改。可先在编辑器中创建副本。')
        if not str(title or '').strip():
            raise AgentError('请填写事件名称。')
        before = self._snapshot(doc)
        ident = _int(event_id, '事件编号') if event_id else self._new_event_id(project, doc)
        if str(ident) in doc['events']:
            raise AgentError(f'事件编号 {ident} 已存在。')
        if ident * 1000 + 999 > MAX_ID:
            raise AgentError('事件编号过大，对话编号（事件号×1000+序号）会超出范围。')
        npc_id = self._speaker(doc, npc) if npc not in (None, 0, '0', '') else 0
        first, talks, options, order, cues = self._build_lines(doc, ident, lines, project_id=project['id'])
        self._apply_cues(doc, order, cues)
        doc['events'][str(ident)] = {'id': ident, 'title': str(title).strip(), 'type': _int(type, '事件类型'), 'talkId': [first],
                                     'rate': float(rate) if float(rate) != int(float(rate)) else int(float(rate)), 'npc': npc_id,
                                     'maxcount': _int(maxcount, '最多发生次数'), 'mapId': _int(map_id, '地点'),
                                     'effect': list(effect or []), 'condition': list(condition or []), 'displayType': 0,
                                     'content': None, 'desc': None, 'maxoptions': 0, 'miniGame': [], 'options': [],
                                     'probability': [], 'replace': [], 'weight': 0}
        doc['options'].update(options)
        current_order = [int(v) for v in doc.get('order', [])]
        return self._save(project, doc, before, order=current_order + order, talk_rows=talks, confirm=confirm, dry_run=dry_run,
                          summary={'eventId': ident, 'lineIds': order, 'optionIds': [int(k) for k in options]})

    def add_lines(self, mod, event_id, lines, after=None, confirm=None, dry_run=False):
        """Insert lines after a given line (default: the end of the event's main chain)."""
        project, doc = self._load(mod)
        event_id = _int(event_id, '事件编号')
        row = self._event_row(doc, event_id)
        before = self._snapshot(doc)
        chain = self._walk(doc, _ids(row.get('talkId')))
        if after is None:
            tail = [t for t in chain if not _ids(doc['talks'][str(t)].get('nextTalk')) and not _ids(doc['talks'][str(t)].get('option'))]
            after = tail[-1] if tail else None
        changed = {}
        if after is None:
            first, talks, options, order, cues = self._build_lines(doc, event_id, lines, project_id=project['id'])
            row['talkId'] = [first]
        else:
            after = _int(after, '插入位置')
            if str(after) not in doc['talks']:
                raise AgentError(f'找不到对话 {after}。')
            anchor = copy.deepcopy(doc['talks'][str(after)])
            if _ids(anchor.get('option')):
                raise AgentError(f'对话 {after} 后面是选项分支，请在分支内的某句之后插入。')
            following = _ids(anchor.get('nextTalk'))
            # New lines start from the stage as it stands after the anchor: characters already there keep their place.
            first, talks, options, order, cues = self._build_lines(doc, event_id, lines, then=following[0] if following else None,
                                                                   stage=self._stage_before(doc, event_id, after), project_id=project['id'])
            anchor['nextTalk'] = [first]
            changed[str(after)] = anchor
        self._apply_cues(doc, order, cues)
        doc['options'].update(options)
        current = [int(v) for v in doc.get('order', [])]
        position = current.index(after) + 1 if after in current else len(current)
        new_order = current[:position] + order + current[position:]
        return self._save(project, doc, before, order=new_order, talk_rows={**changed, **talks}, confirm=confirm, dry_run=dry_run,
                          summary={'eventId': event_id, 'lineIds': order})

    def edit_line(self, mod, talk_id, text=None, speaker=None, display_name=None, confirm=None, dry_run=False, *,
                  background=None, enter=None, expression=None, exit=None, sound=None, actions=None,
                  goto=None, effect=None, cg=None, check=None, next_if_failed=None):
        """Change a line's words, speaker, staging (background, entry, expression, exits, sound, CG),
        where it leads (goto / a check with next_if_failed) and the effect it runs."""
        project, doc = self._load(mod)
        talk_id = _int(talk_id, '对话编号')
        if str(talk_id) not in doc['talks']:
            raise AgentError(f'找不到对话 {talk_id}。')
        before = self._snapshot(doc)
        row = copy.deepcopy(doc['talks'][str(talk_id)])
        if text is not None:
            row['content'] = str(text)
        if speaker is not None:
            row['roleIds'] = [self._speaker(doc, speaker)]
        if display_name is not None:
            row['roleName'] = str(display_name) or None
        who = (_ids(row.get('roleIds')) or [NARRATOR])[0]
        staged = any(v is not None for v in (background, enter, expression, exit, actions))
        if staged:
            owner = next(iter(doc.get('talkOwners', {}).get(str(talk_id), [])), None)
            present, _background = self._stage_before(doc, owner, talk_id, include_anchor=False) if owner else ({}, 0)
            roles = self._raw_actions(doc, actions) if actions is not None else [list(a) for a in row.get('roles') or [] if isinstance(a, list)]
            if background is not None:
                row['bg'] = self._background(doc, background)
            if enter is not None and who >= 0:
                roles = [a for a in roles if not (a and a[0] == who and len(a) > 1 and a[1] in ENTRY)]
                if enter not in (0, False, '', 'none', '无'):
                    roles.insert(0, [who, 1002, 1, self._axis(enter), 0])
            if expression is not None and who >= 0:
                roles = [a for a in roles if not (a and a[0] == who and len(a) > 1 and a[1] == 3000)]
                if expression != '':
                    roles.append([who, 3000, self._expression(doc, who, expression)])
            for person in self._persons(doc, exit, who) if exit else []:
                if not any(a[0] == person and len(a) > 1 and a[1] in EXIT for a in roles):
                    roles.append([person, 2002, 0])
            if roles and who >= 0 and who not in present and not any(a[0] == who for a in roles):
                roles.insert(0, [who, 1001])
            row['roles'] = roles
        if cg is not None:
            row['screenEffect'] = self._cg(doc, cg)
        if effect is not None:
            row['effect'] = self._commands(effect, '效果')
        if goto is not None:
            if _ids(row.get('option')):
                raise AgentError('这句后面是玩家选项，跳转由选项决定；请用 set_options 修改。')
            row['nextTalk'] = self._targets(doc, goto)
        if check is not None:
            row['check'] = self._commands(check, '判定条件')
        if next_if_failed is not None:
            row['nextTalk2'] = self._targets(doc, next_if_failed)
        if row.get('check') and not _ids(row.get('nextTalk2')):
            raise AgentError('设置了判定条件时，请同时用 next_if_failed 指定判定失败后跳到哪句。')
        if sound is not None:
            cues = doc.setdefault('audioCues', {'version': 1, 'sfx': {}, 'bgm': []})
            cues.setdefault('sfx', {})
            values = sound if isinstance(sound, list) else [] if sound in (0, '', 'none', '无') else [sound]
            if values:
                rows = self._audio_rows(project['id'])
                cues['sfx'][str(talk_id)] = [{'audioId': self._audio(rows, v, 'sound'), 'volume': 1} for v in values]
            else:
                cues['sfx'].pop(str(talk_id), None)
        return self._save(project, doc, before, talk_rows={str(talk_id): row}, confirm=confirm, dry_run=dry_run,
                          summary={'lineId': talk_id, **({'stage': self._describe_actions(doc, row.get('roles'))} if staged else {})})

    def _targets(self, doc, value):
        values = value if isinstance(value, list) else [] if value in (0, None, '', 'none', '无', 'end', '结束') else [value]
        out = [_int(v, '跳转对话') for v in values]
        for ident in out:
            if str(ident) not in doc['talks']:
                raise AgentError(f'跳转目标对话 {ident} 不存在。')
        return out[:1]

    def _commands(self, value, label):
        if not isinstance(value, list) or not all(isinstance(r, list) and r and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in r) for r in value):
            raise AgentError(f'{label}应为数字数组的列表，如 [[4, 1, 520, 30]]。可用 list_commands 查模板。')
        return [list(r) for r in value]

    def _cg(self, doc, value):
        """A CG shown from this line (screen effect 4015), 'end' to close it (4017), or 'none'."""
        if value in ('end', '结束', '关闭'):
            return [4017]
        if value in (0, '', 'none', '无'):
            return []
        cgs = doc.get('cgs', {})
        if isinstance(value, int) or isinstance(value, str) and value.strip().isdigit():
            if str(int(value)) not in cgs:
                raise AgentError(f'找不到 CG {value}。可用 list_assets(kind="cgs") 查看。')
            return [4015, int(value)]
        matches = [k for k, r in cgs.items() if (r or {}).get('name') == str(value).strip()]
        if len(matches) != 1:
            raise AgentError(f'找不到唯一名为「{value}」的 CG，请用编号。')
        return [4015, int(matches[0])]

    def set_options(self, mod, talk_id, options, rejoin_to=None, confirm=None, dry_run=False):
        """Replace the player options after a line. Each option keeps its id when given, and leads to
        an existing line (goto) or to new lines (lines) that continue at rejoin_to."""
        project, doc = self._load(mod)
        talk_id = _int(talk_id, '对话编号')
        if str(talk_id) not in doc['talks']:
            raise AgentError(f'找不到对话 {talk_id}。')
        if not isinstance(options, list):
            raise AgentError('options 应为选项数组；传空数组表示去掉选项。')
        before = self._snapshot(doc)
        row = copy.deepcopy(doc['talks'][str(talk_id)])
        owner = next(iter(doc.get('talkOwners', {}).get(str(talk_id), [])), None)
        old_ids = _ids(row.get('option'))
        continuation = rejoin_to if rejoin_to is not None else (_ids(row.get('nextTalk')) or [None])[0]
        continuation = self._targets(doc, continuation)[0] if continuation not in (None, '', 0) else None
        talks, order_new, kept = {}, [], []
        block = owner or self._new_event_id(project, doc)
        fresh = [o for o in options if isinstance(o, dict) and not o.get('id')]
        new_ids = self._free_ids(doc, 'options', block, 100, len(fresh)) if fresh else []
        for option in options:
            if not isinstance(option, dict) or not str(option.get('text', '')).strip():
                raise AgentError('每个选项需要 text（选项文字），以及 goto（跳到已有对话）或 lines（新写的对话）。')
            oid = _int(option['id'], '选项编号') if option.get('id') else new_ids.pop(0)
            if option.get('id') and oid not in old_ids:
                raise AgentError(f'选项 {oid} 不属于这句对话。')
            current = copy.deepcopy(doc.get('options', {}).get(str(oid), {}))
            if option.get('lines'):
                first, rows, sub_options, order, cues = self._build_lines(doc, block, option['lines'], then=continuation,
                                                                       stage=self._stage_before(doc, owner, talk_id) if owner else None, project_id=project['id'])
                doc['options'].update(sub_options)
                self._apply_cues(doc, order, cues)
                talks.update(rows); order_new += order
                target = [first]
            elif option.get('goto') not in (None, ''):
                target = self._targets(doc, option['goto'])
            elif current:
                target = _ids(current.get('talkId'))
            else:
                target = [continuation] if continuation else []
            current.update(id=oid, content=str(option['text']).strip(), talkId=target)
            for key, field, label in (('condition', 'precondition', '选项出现条件'), ('effect', 'effect', '选项效果')):
                if key in option:
                    current[field] = self._commands(option[key] or [], label)
            for field, default in (('talkId2', []), ('effect', []), ('effect2', []), ('check', []), ('precondition', [])):
                current.setdefault(field, default)
            doc['options'][str(oid)] = current
            kept.append(oid)
        for oid in old_ids:
            if oid not in kept and not any(oid in _ids(t.get('option')) for k, t in doc['talks'].items() if k != str(talk_id)):
                doc['options'].pop(str(oid), None)
        row['option'] = kept
        row['nextTalk'] = [] if kept else ([continuation] if continuation else [])
        current_order = [int(v) for v in doc.get('order', [])]
        at = current_order.index(talk_id) + 1 if talk_id in current_order else len(current_order)
        return self._save(project, doc, before, order=current_order[:at] + order_new + current_order[at:], talk_rows={str(talk_id): row, **talks},
                          confirm=confirm, dry_run=dry_run, summary={'lineId': talk_id, 'optionIds': kept, 'newLineIds': order_new})

    def set_music(self, mod, line_ids, music=None, confirm=None, dry_run=False):
        """Play background music over these lines (replacing their current range), or clear it with music=None."""
        project, doc = self._load(mod)
        chosen = [_int(t, '对话编号') for t in (line_ids or [])]
        if not chosen:
            raise AgentError('请指定要设置背景音乐的对话编号。')
        for tid in chosen:
            if str(tid) not in doc['talks']:
                raise AgentError(f'找不到对话 {tid}。')
        before = self._snapshot(doc)
        cues = doc.setdefault('audioCues', {'version': 1, 'sfx': {}, 'bgm': []})
        cues.setdefault('bgm', [])
        wanted = set(chosen)
        for group in cues['bgm']:
            group['talkIds'] = [t for t in group.get('talkIds', []) if int(t) not in wanted]
        cues['bgm'] = [g for g in cues['bgm'] if g.get('talkIds')]
        if music not in (None, '', 0, 'none', '无'):
            cue = self._music(self._audio_rows(project['id']), music)
            cues['bgm'].append({'id': 'ai-' + uuid.uuid4().hex[:16], **cue, 'talkIds': list(dict.fromkeys(chosen))})
        return self._save(project, doc, before, confirm=confirm, dry_run=dry_run, summary={'lines': chosen})

    def assets(self, mod, kind, query=None, person=None, limit=40):
        """Backgrounds, music, sound effects or a character's expressions, with the ids lines refer to."""
        project, doc = self._load(mod)
        import asset_labels
        needle = str(query or '').strip().casefold()
        match = lambda *values: not needle or any(needle in str(v or '').casefold() for v in values)
        if kind == 'backgrounds':
            rows = []
            for key, row in doc.get('backgrounds', {}).items():
                if not str(key).isdigit() or not isinstance(row, dict):
                    continue
                name, file = asset_labels.asset_name(row, 'background'), str(row.get('url') or '').rsplit('/', 1)[-1]
                if match(key, name, file):
                    rows.append({'id': int(key), 'name': name, 'file': file, 'own': self._is_local(doc, 'backgrounds', key)})
            rows.sort(key=lambda r: (r['name'] == f"场景 {r['id']}", r['id']))  # named backgrounds first
            for item in rows[:limit]:  # an image path lets agents that read images look at the place
                try:
                    item['image'] = str(self.store.asset(project['id'], doc['backgrounds'][str(item['id'])].get('url')))
                except Exception:
                    pass
            return {'kind': kind, 'total': len(rows), 'items': rows[:limit],
                    'note': '背景名称多为「场景 编号」时，可从 file（拼音文件名，如 tiantai 天台、jiaoshi 教室）判断地点；有 image 时可直接查看图片。'}
        if kind in ('music', 'sounds'):
            wanted = (1,) if kind == 'music' else (2, 3)
            rows = [{'id': int(k), 'name': asset_labels.asset_name(r, 'audio'), 'file': str(r.get('url') or '').rsplit('/', 1)[-1]}
                    for k, r in self._audio_rows(project['id']).items() if r.get('type', 1) in wanted]
            rows = [r for r in rows if match(r['id'], r['name'], r['file'])]
            rows.sort(key=lambda r: r['id'])
            return {'kind': kind, 'total': len(rows), 'items': rows[:limit]}
        if kind == 'expressions':
            if person in (None, ''):
                raise AgentError('查看表情需要 person（人物名称或编号）。')
            ident = self._speaker(doc, person)
            own = {}
            for key, row in doc.get('faces', {}).items():
                if str(key).isdigit() and int(key) // 1000 == ident and (row or {}).get('name'):
                    own.setdefault(int(key) % 100, row['name'])
            items = [{'id': n, 'name': own.get(n, name)} for n, name in enumerate(FACES)]
            items += [{'id': n, 'name': name} for n, name in sorted(own.items()) if n >= len(FACES)]
            return {'kind': kind, 'person': ident, 'items': [i for i in items if match(i['id'], i['name'])],
                    'note': '表情编号对应人物模型里的表情槽，不同人物实际拥有的表情不同；不确定时优先用 0–10 的常用表情，并在编辑器预览中确认。'}
        if kind == 'cgs':
            rows = [{'id': int(k), 'name': asset_labels.asset_name(r, 'cg')} for k, r in doc.get('cgs', {}).items() if str(k).isdigit() and isinstance(r, dict)]
            rows = [r for r in rows if match(r['id'], r['name'])]
            rows.sort(key=lambda r: r['id'])
            return {'kind': kind, 'total': len(rows), 'items': rows[:limit], 'note': '在对话上用 edit_line(cg=编号) 显示，cg="end" 结束。'}
        if kind == 'maps':
            maps = self._call(self.store.table, project['id'], 'MapCfg').get('rows', {})
            rows = [{'id': int(k), 'name': (r or {}).get('name') or ''} for k, r in maps.items() if str(k).isdigit()]
            rows = [r for r in rows if match(r['id'], r['name'])]
            rows.sort(key=lambda r: r['id'])
            return {'kind': kind, 'total': len(rows), 'items': rows[:limit], 'note': '事件的 map_id / mapId 填这里的编号，0 为不限地点。'}
        if kind == 'event_types':
            import json as _json
            text = (Path(__file__).with_name('event-types.js')).read_text(encoding='utf-8')
            types, _end = _json.JSONDecoder().raw_decode(text, text.index('{'))
            rows = [{'id': int(k), 'name': v.get('name')} for k, v in types.items() if match(k, v.get('name'))]
            return {'kind': kind, 'items': rows, 'note': '常用：1 可跳过的普通事件、2 社交触发、20 关系任务、22 恋爱话题、110 送礼、520 表白、522 恋爱社交。'}
        if kind == 'dialogue_uses':
            return {'kind': kind, 'items': self.dialogue_uses()}
        raise AgentError('kind 只能是 backgrounds、music、sounds、expressions、cgs、maps、event_types 或 dialogue_uses。')

    def delete_lines(self, mod, talk_ids, confirm=None, dry_run=False):
        """Delete lines and reconnect the chain around them, so the event keeps playing."""
        project, doc = self._load(mod)
        doomed = [_int(t, '对话编号') for t in (talk_ids or [])]
        if not doomed:
            raise AgentError('请指定要删除的对话编号。')
        for tid in doomed:
            if str(tid) not in doc['talks']:
                raise AgentError(f'找不到对话 {tid}。')
        before = self._snapshot(doc)
        doomed_set = set(doomed)

        def resolve(target, seen=()):
            while target in doomed_set and target not in seen:
                seen = (*seen, target)
                nxt = _ids(doc['talks'][str(target)].get('nextTalk'))
                target = nxt[0] if nxt else None
            return target
        changed = {}
        for key, row in doc['talks'].items():
            if int(key) in doomed_set:
                continue
            for field in ('nextTalk', 'nextTalk2'):
                values = _ids(row.get(field))
                if any(v in doomed_set for v in values):
                    fixed = [r for r in (resolve(v) for v in values) if r]
                    changed.setdefault(key, copy.deepcopy(row))[field] = fixed
        for oid, option in doc.get('options', {}).items():
            for field in ('talkId', 'talkId2'):
                values = _ids(option.get(field))
                if any(v in doomed_set for v in values):
                    option[field] = [r for r in (resolve(v) for v in values) if r]
        for event in doc.get('events', {}).values():
            values = _ids(event.get('talkId'))
            if any(v in doomed_set for v in values):
                event['talkId'] = [r for r in (resolve(v) for v in values) if r]
        order = [int(v) for v in doc.get('order', []) if int(v) not in doomed_set]
        return self._save(project, doc, before, order=order, talk_rows=changed, deleted_talks=doomed, confirm=confirm, dry_run=dry_run,
                          summary={'deleted': doomed, 'relinked': sorted(int(k) for k in changed)})

    def update_event(self, mod, event_id, fields, confirm=None, dry_run=False):
        project, doc = self._load(mod)
        event_id = _int(event_id, '事件编号')
        row = self._event_row(doc, event_id)
        unknown = set(fields or {}) - EVENT_FIELDS
        if unknown:
            raise AgentError('不支持修改的事件字段：' + '、'.join(sorted(unknown)) + '。可改：' + '、'.join(sorted(EVENT_FIELDS)))
        before = self._snapshot(doc)
        for key, value in (fields or {}).items():
            row[key] = (self._speaker(doc, value) if value not in (0, '0', None, '') else 0) if key == 'npc' else value
        return self._save(project, doc, before, confirm=confirm, dry_run=dry_run, summary={'eventId': event_id, 'fields': sorted(fields or {})})

    def delete_event(self, mod, event_id, confirm=None, dry_run=False):
        """Delete an event of this mod. The editor's save removes lines owned only by it."""
        project, doc = self._load(mod)
        event_id = _int(event_id, '事件编号')
        self._event_row(doc, event_id)
        if not self._is_local(doc, 'events', event_id):
            raise AgentError(f'事件 {event_id} 是原版事件，不能删除。')
        before = self._snapshot(doc)
        del doc['events'][str(event_id)]
        return self._save(project, doc, before, confirm=confirm, dry_run=dry_run, summary={'deletedEvent': event_id})

    def update_rows(self, mod, name, rows=None, confirm=None, dry_run=False, delete=None):
        """Upsert rows of any workshop table (items, persons' growth, shop…) through the table editor's save,
        and delete this mod's own rows. Phone messages go through the message editor's own checks."""
        project = self._project(mod)
        rows = rows or {}
        doomed = {str(_int(v, '要删除的编号')) for v in (delete or [])}
        if not isinstance(rows, dict) or not rows and not doomed:
            raise AgentError('rows 应为 {编号: 记录} 对象；删除请用 delete 传编号列表。')
        data = self._call(self.store.table, project['id'], name)
        current = data.get('rows', {})
        local = {str(v) for v in data.get('localIds', [])}
        missing = doomed - local
        if missing:
            raise AgentError('只能删除本模组自己的记录：' + '、'.join(sorted(missing)) + ' 不是本模组新增或修改的记录。')
        merged = {k: v for k, v in current.items() if k in local and k not in doomed}
        for key, row in rows.items():
            if not isinstance(row, dict):
                raise AgentError(f'记录 {key} 应为对象。')
            base = copy.deepcopy(current.get(str(key), {}))
            base.update(row)
            base['id'] = int(key) if str(key).isdigit() else key
            merged[str(key)] = base
        table = data.get('name', name)
        payload = {'projectId': project['id'], 'name': table, 'revision': data.get('revision'), 'rows': merged, 'scope': 'local'}
        if confirm:
            payload['_confirmedSaveWarnings'] = list(confirm)
        if dry_run:
            return {'dryRun': True, 'table': table, 'rows': sorted(rows), 'deleted': sorted(doomed)}
        if table == 'PhoneMsgCfg':
            import messages
            editor = server.read_json(server.safe_path(self._call(self.store.project, project['id']).path, messages.STATE), {'titles': {}, 'previewDelays': {}})
            payload = {'projectId': project['id'], 'revision': data.get('revision'), 'rows': merged, 'editor': editor,
                       **({'_confirmedSaveWarnings': list(confirm)} if confirm else {})}
            save = lambda value: messages.save(self.store, value, server)
        else:
            save = self.store.table_save
        try:
            result = save_review.perform(save, payload, server.ApiError)
        except server.ApiError as error:
            if error.code == 'save_warnings':
                raise AgentError('保存前需要确认以下警告；确认无误后，把 warnings 原样传回 confirm 再执行一次。',
                                 warnings=getattr(error, 'warnings', []), code='save_warnings') from None
            raise AgentError(error.message, code=error.code) from None
        return {'saved': True, 'table': table, 'rows': sorted(rows), 'deleted': sorted(doomed), 'revision': result.get('revision'),
                'warnings': result.get('warnings', [])}

    def describe_table(self, mod, name=None):
        """Without a name: the configuration tables the game reads, with Chinese labels.
        With a name: every field's meaning, type, default and the table its ids refer to."""
        catalog = self.store.catalog()
        schemas = catalog.get('schemas', {}) if isinstance(catalog.get('schemas'), dict) else {}
        if not name:
            rows = [{'name': k, 'label': v.get('label'), 'category': v.get('category')} for k, v in schemas.items() if isinstance(v, dict)]
            rows.sort(key=lambda r: (str(r['category'] or ''), r['name']))
            return {'tables': rows, 'note': '对话、选项、事件请用剧情工具；其他表用 read_table 读、update_rows 改。'}
        project = self._project(mod)
        data = self._call(self.store.table, project['id'], name)
        schema = data.get('schema') or {}
        fields = [{k: f.get(k) for k in ('name', 'label', 'type', 'description', 'default', 'required', 'range', 'editorType') if f.get(k) not in (None, '', False)}
                  for f in schema.get('fields', []) if isinstance(f, dict) and not f.get('hidden')]
        return {'table': data.get('name', name), 'label': schema.get('label'), 'category': schema.get('category'), 'fields': fields,
                'ownRows': len(data.get('localIds', [])), 'totalRows': len(data.get('rows', {})),
                'note': 'editorType 为 Condition/Effect 的字段按 list_commands 的模板填写；range 表示该字段填另一张表的编号。'}

    def create_mod(self, name, copy_from=None):
        """A new empty local mod, or a local copy of an existing one (subscribed mods included)."""
        if not str(name or '').strip():
            raise AgentError('请填写模组名称。')
        if copy_from:
            source = self._project(copy_from)
            created = self._call(self.store.duplicate, source['id'], str(name).strip())
        else:
            created = self._call(self.store.create, str(name).strip())
        return {'created': True, 'mod': {'id': created.get('id'), 'name': created.get('name')}}

    def import_asset(self, mod, kind, file_path, name=None, person=None, face=0, cloth=0, grade=1):
        """Import a local image or audio file into the mod: backgrounds, CGs, character portraits, music, sounds."""
        import base64
        project = self._project(mod)
        path = Path(str(file_path or '')).expanduser()
        if not path.is_file():
            raise AgentError(f'找不到文件：{file_path}')
        data = base64.b64encode(path.read_bytes()).decode('ascii')
        revision = self._call(self.store.revision, self._call(self.store.project, project['id']))
        label = str(name or path.stem)
        if kind in ('music', 'sound'):
            result = self._call(self.store.audio_import, {'projectId': project['id'], 'revision': revision, 'data': data, 'fileName': path.name,
                                                          'name': label, 'type': 1 if kind == 'music' else 2})
            return {'imported': True, 'kind': kind, 'id': result.get('id'), 'reused': bool(result.get('reused'))}
        if kind not in ('background', 'cg', 'portrait'):
            raise AgentError('kind 只能是 background、cg、portrait、music 或 sound。')
        payload = {'projectId': project['id'], 'revision': revision, 'data': data, 'kind': kind, 'name': label}
        if kind == 'portrait':
            doc = self.store.load(project['id'])
            payload.update(personId=self._speaker(doc, person) if person not in (None, '') else None, faceId=int(face or 0),
                           cloth=int(cloth or 0), grade=int(grade or 1))
        result = self._call(self.store.import_image, payload)
        return {'imported': True, 'kind': kind, 'id': result.get('id'), **({'personId': result['personId']} if 'personId' in result else {}),
                'size': [result.get('width'), result.get('height')]}

    def check_mod(self, mod):
        """JSON syntax problems and story links that lead nowhere."""
        import config_doctor
        project, doc = self._load(mod)
        report, _changes = self._call(config_doctor.inspect, self.store, project['id'], server)
        issues = [{'file': i.get('path'), 'problem': i.get('message')} for i in report.get('issues', [])]
        talks, options, local = doc['talks'], doc.get('options', {}), {str(v) for v in doc.get('localIds', {}).get('talks', [])}
        for key in local:
            row = talks.get(key) or {}
            for field in ('nextTalk', 'nextTalk2'):
                for target in _ids(row.get(field)):
                    if str(target) not in talks:
                        issues.append({'line': int(key), 'problem': f'{field} 指向不存在的对话 {target}'})
            for oid in _ids(row.get('option')):
                if str(oid) not in options:
                    issues.append({'line': int(key), 'problem': f'选项 {oid} 不存在'})
                else:
                    for target in _ids(options[str(oid)].get('talkId')):
                        if str(target) not in talks:
                            issues.append({'line': int(key), 'problem': f'选项 {oid} 跳到不存在的对话 {target}'})
            for speaker in _ids(row.get('roleIds')):
                if speaker > 0 and str(speaker) not in doc.get('persons', {}):
                    issues.append({'line': int(key), 'problem': f'说话人 {speaker} 不存在'})
        owners = doc.get('talkOwners', {})
        try:
            import external_dialogues
            filed = {str(i) for f in external_dialogues.load(self.store, project['id'], server)['folders'].values() for i in f.get('talkIds', [])}
        except server.ApiError:
            filed = set()
        orphans = sorted(int(k) for k in local if not owners.get(k) and k not in filed and str(k) in talks)
        if orphans:
            issues.append({'lines': orphans[:50], 'problem': f'{len(orphans)} 句对话不属于任何事件或事件外对话夹，游戏里不会播放（可能是删掉选项后留下的）'})
        for key in {str(v) for v in doc.get('localIds', {}).get('events', [])}:
            event = doc['events'].get(key) or {}
            if not _ids(event.get('talkId')):
                issues.append({'event': int(key), 'problem': '事件没有首句对话'})
            for target in _ids(event.get('talkId')):
                if str(target) not in talks:
                    issues.append({'event': int(key), 'problem': f'首句对话 {target} 不存在'})
        return {'ok': not issues and not doc.get('warnings'), 'issues': issues[:200], 'issueCount': len(issues), 'loadWarnings': doc.get('warnings', [])}

    def json_file(self, mod, path=None, text=None, confirm_overwrite=False):
        """Last resort for anything the other tools do not cover: list, read, or replace one of the mod's JSON files."""
        project = self._project(mod)
        if not path:
            return self._call(self.store.json_files, project['id'])
        if text is None:
            source = self._call(self.store.json_source, {'projectId': project['id'], 'path': path})
            return {'path': source['path'], 'text': source['text'], 'revision': source['revision'], 'valid': source['analysis'].get('valid')}
        if not confirm_overwrite:
            raise AgentError('写入会整体替换这个文件。确认内容完整无误后，传 confirm_overwrite=true 再执行。', code='confirm_required')
        source = self._call(self.store.json_source, {'projectId': project['id'], 'path': path})
        result = self._call(self.store.json_save, {'projectId': project['id'], 'path': path, 'text': str(text), 'revision': source['revision'], 'bom': source.get('bom')})
        return {'saved': True, 'path': result['path'], 'valid': result['analysis'].get('valid')}

    # ---------- event-less dialogue folders (gifts, idle chats, minigame openings, CG memories…) ----------
    def external_dialogues(self, mod):
        import external_dialogues
        project = self._project(mod)
        data = self._call(external_dialogues.load, self.store, project['id'], server)
        folders = []
        for key, folder in data['folders'].items():
            first = next(iter(folder.get('talkIds', [])), None)
            folders.append({'folder': key, 'name': folder.get('name'), 'lines': len(folder.get('talkIds', [])), 'firstLine': first,
                            'firstText': (data['talks'].get(str(first)) or {}).get('content', '')[:60] if first else '',
                            'uses': [{'kind': u.get('kind'), 'recordId': u.get('recordId'), **{k: u[k] for k in ('npc', 'item', 'level', 'answer', 'gender') if k in u}}
                                     for u in folder.get('uses', [])]})
        return {'folders': folders, 'unfiledLines': len(set(data['talks']) - {str(i) for f in data['folders'].values() for i in f.get('talkIds', [])})}

    def dialogue_uses(self):
        import external_usages
        return [{'kind': d['kind'], 'label': d['label'], 'help': d.get('help'), 'needs': self._use_needs(d)}
                for d in external_usages.DEFINITIONS if not d.get('disabled')]

    @staticmethod
    def _use_needs(d):
        if d['shape'] == 'gift':
            return 'npc（收礼人）、item（礼物编号）、giftMode（0 交付礼物并播放，1 仅播放）'
        if d['shape'] == 'mini':
            return 'npc（已绑定小游戏的人物）、level（1–5 关）'
        if d['shape'] == 'answer':
            return 'recordId（输入题编号）、answer（精确匹配的答案）'
        if d.get('create'):
            return 'recordId（已有配置编号，不填则新建）；params 可写：' + '、'.join(d['fields'])
        return 'recordId（已有配置编号）' + ('；params 可写：' + '、'.join(d['fields']) if d['fields'] else '')

    def create_external_dialogue(self, mod, name, lines, uses=None, confirm=None, dry_run=False):
        """A dialogue folder outside events, optionally bound to where the game plays it (a gift, an idle chat…)."""
        import external_dialogues, external_usages
        project, doc = self._load(mod)
        if project.get('readOnly'):
            raise AgentError('订阅模组只读，不能修改。')
        if not str(name or '').strip():
            raise AgentError('请填写对话夹名称。')
        data = self._call(external_dialogues.load, self.store, project['id'], server)
        block = self._new_event_id(project, doc)
        first, talks, options, order, cues = self._build_lines(doc, block, lines, project_id=project['id'])
        if options:
            raise AgentError('事件外对话暂不支持选项分支，请写成连续对话。')
        folder_id = 'ai-' + uuid.uuid4().hex[:12]
        bound = []
        for use in uses or []:
            if not isinstance(use, dict) or use.get('kind') not in external_usages.KINDS or external_usages.KINDS[use['kind']].get('disabled'):
                raise AgentError('用途 kind 无效。可用 list_assets(kind="dialogue_uses") 查看。')
            item = {'id': uuid.uuid4().hex, 'kind': use['kind'], 'entryId': first, 'gender': use.get('gender', 'both')}
            for key in ('recordId', 'item', 'level', 'giftMode', 'answer'):
                if use.get(key) not in (None, ''):
                    item[key] = use[key]
            if use.get('npc') not in (None, ''):
                item['npc'] = self._speaker(doc, use['npc'])
            if use.get('params'):
                item['params'] = use['params']
            bound.append(item)
        folders = {**data['folders'], folder_id: {'name': str(name).strip(), 'talkIds': order, 'uses': bound, 'sequence': False}}
        payload = {'projectId': project['id'], 'revision': data['revision'], 'talks': {**data['talks'], **talks}, 'folders': folders}
        if confirm:
            payload['_confirmedSaveWarnings'] = list(confirm)
        if dry_run:
            return {'dryRun': True, 'folder': folder_id, 'lineIds': order, 'uses': [u['kind'] for u in bound]}
        try:
            result = save_review.perform(lambda value: external_dialogues.save(self.store, value, server), payload, server.ApiError)
        except server.ApiError as error:
            if error.code == 'save_warnings':
                raise AgentError('保存前需要确认以下警告；确认无误后，把 warnings 原样传回 confirm 再执行一次。',
                                 warnings=getattr(error, 'warnings', []), code='save_warnings') from None
            raise AgentError(error.message, code=error.code) from None
        if cues['sfx'] or cues['music']:
            project2, doc2 = self._load(mod)
            before = self._snapshot(doc2)
            self._apply_cues(doc2, order, cues)
            self._save(project2, doc2, before)
        saved = result['folders'].get(folder_id, {})
        return {'saved': True, 'folder': folder_id, 'lineIds': order,
                'uses': [{'kind': u.get('kind'), 'recordId': u.get('recordId')} for u in saved.get('uses', [])], 'warnings': result.get('warnings', [])}

    def backup(self, mod):
        project = self._project(mod)
        result = self._call(self.store.backups.create, {'projectId': project['id'], 'kind': 'manual', 'requestId': uuid.uuid4().hex})
        return {'backup': result.get('path'), 'createdAt': result.get('createdAt')}
