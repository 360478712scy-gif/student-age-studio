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
from pathlib import Path

import server
import save_review
from game_locator import GameLocations

NARRATOR, PROTAGONIST = -1, 0
MAX_ID = 2147483647
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
        return view

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

    def _build_lines(self, doc, event_id, specs, then=None):
        """Turn line specs into talk (and option) rows chained in order. Returns (first id, rows, options, order)."""
        if not isinstance(specs, list) or not specs:
            raise AgentError('lines 需要至少一句对话。')
        flat = self._flatten(specs)
        # Numbers follow reading order (a line, then its branches, then the next line), as the editor numbers them.
        numbers = dict(zip(map(id, flat), self._free_ids(doc, 'talks', event_id, 1000, len(flat))))
        options_needed = sum(len(s.get('options') or []) for s in flat if isinstance(s, dict))
        option_ids = self._free_ids(doc, 'options', event_id, 100, options_needed) if options_needed else []
        talks, options = {}, {}
        order = [numbers[id(spec)] for spec in flat]

        def chain(items, continuation):
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
                if spec.get('enter') and speaker not in (NARRATOR,):
                    position = _int(spec['enter'], '登场位置')
                    if position not in (1, 2, 3):
                        raise AgentError('enter 登场位置只能是 1（左）、2（中）、3（右）。')
                    row['roles'] = [[speaker, 1002, 1, position]]
                talks[str(tid)] = row
                branches = spec.get('options') or []
                if branches:
                    row['nextTalk'] = []
                    rejoin = after if spec.get('rejoin', True) else None
                    for option in branches:
                        if not isinstance(option, dict) or not str(option.get('text', '')).strip():
                            raise AgentError('每个选项需要 text（选项文字），可选 lines（选择后的对话）。')
                        oid = option_ids.pop(0)
                        target = chain(option['lines'], rejoin) if option.get('lines') else rejoin
                        options[str(oid)] = {'id': oid, 'content': option['text'], 'talkId': [target] if target else [],
                                             'talkId2': [], 'effect': option.get('effect', []), 'effect2': [], 'check': [],
                                             'precondition': option.get('condition', [])}
                        row['option'].append(oid)
            return ids_here[0] if ids_here else continuation

        first = chain(specs, then)
        return first, talks, options, order

    def _flatten(self, specs):
        out = []
        for spec in specs or []:
            out.append(spec)
            for option in (spec.get('options') or []) if isinstance(spec, dict) else []:
                out += self._flatten(option.get('lines') if isinstance(option, dict) else [])
        return out

    def _save(self, project, doc, before, *, order=None, talk_rows=None, deleted_talks=None, confirm=None, dry_run=False, summary=None):
        payload = {'projectId': project['id'], 'revision': doc['revision']}
        for key in server.TABLES:
            if key == 'talks':
                continue
            if doc.get(key) != before.get(key):
                payload[key] = doc[key]
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
        before = copy.deepcopy({k: doc.get(k) for k in server.TABLES if k != 'talks'})
        ident = _int(event_id, '事件编号') if event_id else self._new_event_id(project, doc)
        if str(ident) in doc['events']:
            raise AgentError(f'事件编号 {ident} 已存在。')
        if ident * 1000 + 999 > MAX_ID:
            raise AgentError('事件编号过大，对话编号（事件号×1000+序号）会超出范围。')
        npc_id = self._speaker(doc, npc) if npc not in (None, 0, '0') else 0
        first, talks, options, order = self._build_lines(doc, ident, lines)
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
        before = copy.deepcopy({k: doc.get(k) for k in server.TABLES if k != 'talks'})
        chain = self._walk(doc, _ids(row.get('talkId')))
        if after is None:
            tail = [t for t in chain if not _ids(doc['talks'][str(t)].get('nextTalk')) and not _ids(doc['talks'][str(t)].get('option'))]
            after = tail[-1] if tail else None
        changed = {}
        if after is None:
            first, talks, options, order = self._build_lines(doc, event_id, lines)
            row['talkId'] = [first]
        else:
            after = _int(after, '插入位置')
            if str(after) not in doc['talks']:
                raise AgentError(f'找不到对话 {after}。')
            anchor = copy.deepcopy(doc['talks'][str(after)])
            if _ids(anchor.get('option')):
                raise AgentError(f'对话 {after} 后面是选项分支，请在分支内的某句之后插入。')
            following = _ids(anchor.get('nextTalk'))
            first, talks, options, order = self._build_lines(doc, event_id, lines, then=following[0] if following else None)
            anchor['nextTalk'] = [first]
            changed[str(after)] = anchor
        doc['options'].update(options)
        current = [int(v) for v in doc.get('order', [])]
        position = current.index(after) + 1 if after in current else len(current)
        new_order = current[:position] + order + current[position:]
        return self._save(project, doc, before, order=new_order, talk_rows={**changed, **talks}, confirm=confirm, dry_run=dry_run,
                          summary={'eventId': event_id, 'lineIds': order})

    def edit_line(self, mod, talk_id, text=None, speaker=None, display_name=None, confirm=None, dry_run=False):
        project, doc = self._load(mod)
        talk_id = _int(talk_id, '对话编号')
        if str(talk_id) not in doc['talks']:
            raise AgentError(f'找不到对话 {talk_id}。')
        before = copy.deepcopy({k: doc.get(k) for k in server.TABLES if k != 'talks'})
        row = copy.deepcopy(doc['talks'][str(talk_id)])
        if text is not None:
            row['content'] = str(text)
        if speaker is not None:
            row['roleIds'] = [self._speaker(doc, speaker)]
        if display_name is not None:
            row['roleName'] = str(display_name) or None
        return self._save(project, doc, before, talk_rows={str(talk_id): row}, confirm=confirm, dry_run=dry_run,
                          summary={'lineId': talk_id})

    def delete_lines(self, mod, talk_ids, confirm=None, dry_run=False):
        """Delete lines and reconnect the chain around them, so the event keeps playing."""
        project, doc = self._load(mod)
        doomed = [_int(t, '对话编号') for t in (talk_ids or [])]
        if not doomed:
            raise AgentError('请指定要删除的对话编号。')
        for tid in doomed:
            if str(tid) not in doc['talks']:
                raise AgentError(f'找不到对话 {tid}。')
        before = copy.deepcopy({k: doc.get(k) for k in server.TABLES if k != 'talks'})
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
        before = copy.deepcopy({k: doc.get(k) for k in server.TABLES if k != 'talks'})
        for key, value in (fields or {}).items():
            row[key] = self._speaker(doc, value) if key == 'npc' and value not in (0, '0', None) else value
        return self._save(project, doc, before, confirm=confirm, dry_run=dry_run, summary={'eventId': event_id, 'fields': sorted(fields or {})})

    def delete_event(self, mod, event_id, confirm=None, dry_run=False):
        """Delete an event of this mod. The editor's save removes lines owned only by it."""
        project, doc = self._load(mod)
        event_id = _int(event_id, '事件编号')
        self._event_row(doc, event_id)
        if not self._is_local(doc, 'events', event_id):
            raise AgentError(f'事件 {event_id} 是原版事件，不能删除。')
        before = copy.deepcopy({k: doc.get(k) for k in server.TABLES if k != 'talks'})
        del doc['events'][str(event_id)]
        return self._save(project, doc, before, confirm=confirm, dry_run=dry_run, summary={'deletedEvent': event_id})

    def update_rows(self, mod, name, rows, confirm=None, dry_run=False):
        """Upsert rows of any workshop table (items, persons' growth, shop…) through the table editor's save."""
        project = self._project(mod)
        if not isinstance(rows, dict) or not rows:
            raise AgentError('rows 应为 {编号: 记录} 对象。')
        data = self._call(self.store.table, project['id'], name)
        current = data.get('rows', {})
        local = {str(v) for v in data.get('localIds', [])}
        merged = {k: v for k, v in current.items() if k in local}
        for key, row in rows.items():
            if not isinstance(row, dict):
                raise AgentError(f'记录 {key} 应为对象。')
            base = copy.deepcopy(current.get(str(key), {}))
            base.update(row)
            base['id'] = int(key) if str(key).isdigit() else key
            merged[str(key)] = base
        payload = {'projectId': project['id'], 'name': data.get('name', name), 'revision': data.get('revision'), 'rows': merged, 'scope': 'local'}
        if confirm:
            payload['_confirmedSaveWarnings'] = list(confirm)
        if dry_run:
            return {'dryRun': True, 'table': payload['name'], 'rows': sorted(rows)}
        try:
            result = save_review.perform(self.store.table_save, payload, server.ApiError)
        except server.ApiError as error:
            if error.code == 'save_warnings':
                raise AgentError('保存前需要确认以下警告；确认无误后，把 warnings 原样传回 confirm 再执行一次。',
                                 warnings=getattr(error, 'warnings', []), code='save_warnings') from None
            raise AgentError(error.message, code=error.code) from None
        return {'saved': True, 'table': payload['name'], 'rows': sorted(rows), 'revision': result.get('revision')}

    def backup(self, mod):
        project = self._project(mod)
        import uuid
        result = self._call(self.store.backups.create, {'projectId': project['id'], 'kind': 'manual', 'requestId': uuid.uuid4().hex})
        return {'backup': result.get('path'), 'createdAt': result.get('createdAt')}
