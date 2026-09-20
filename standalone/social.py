"""KZone authoring backed by the game's post/comment tables and account rules."""
from __future__ import annotations
import save_review

import copy
import math
import re
import urllib.parse
from pathlib import Path, PurePosixPath

POST = 'KZoneContentCfg'
COMMENT = 'KZoneCommentCfg'
STATE = 'StudentAgeStudio/social-state.json'
POST_DEFAULT = {'id': 0, 'role': 0, 'content': '', 'imgs': [], 'thumbs': [], 'comments': [], 'options': [], 'cond': [], 'thumbCnt': 0, 'title': '', 'visitCnt': 0}
COMMENT_DEFAULT = {'id': 0, 'roles': [0], 'parent': 0, 'content': '', 'comments': [], 'options': [], 'effect': [], 'condition': [], 'personality': []}


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


class SocialEditor:
    def __init__(self, store, backend):
        self.store, self.b = store, backend

    def local(self, project, table, warnings=None):
        rows = self.b.read_json(self.b.safe_path(project.path, 'Cfgs/zh-cn/' + table + '.json'), {})
        if not isinstance(rows, dict):
            raise self.b.ApiError(table + ' 配置不是编号表。', 422)
        for key, row in rows.items():
            if (self.b.valid_id(key) or key == '0') and isinstance(row, dict) and row.get('id') != int(key):
                row['id'] = int(key)
                if warnings is not None:
                    warnings.append(table + ' 已在编辑副本中修复行编号，保存时备份原文件。')
        self.b.validate_map(rows, table, allow_zero=True)
        import original_mode
        return original_mode.visible_rows(self.store, project, table, rows, warnings)

    def merged(self, project, table):
        return {**self.store.catalog_rows(table), **self.local(project, table)}

    def state(self, project):
        state = self.b.read_json(self.b.safe_path(project.path, STATE), {})
        if not isinstance(state, dict) or not isinstance(state.get('disabledOptions', {}), dict):
            raise self.b.ApiError('企鹅动态的编辑记录格式无效，请恢复备份。', 422)
        state.setdefault('disabledOptions', {})
        return state

    def accounts(self, project, token=None):
        tables = {name: self.merged(project, name) for name in ('PersonCfg', 'KZoneProfileCfg', 'KZoneAvatarCfg', POST, COMMENT)}
        try: tables['KZoneMessageBoardCfg'] = self.merged(project, 'KZoneMessageBoardCfg')
        except self.b.ApiError: tables['KZoneMessageBoardCfg'] = self.store.catalog_rows('KZoneMessageBoardCfg')
        people, profiles, avatars = (tables[n] for n in ('PersonCfg', 'KZoneProfileCfg', 'KZoneAvatarCfg'))
        # A PersonCfg row alone does not establish a Penguin account. Include social
        # profiles, assigned avatars, and participants actually used by social data.
        ids = {0} | {int(key) for key in profiles} | {int(key) for key, row in people.items() if integer(row.get('kzoneHeadId')) and str(row['kzoneHeadId']) in avatars}
        for row in tables[POST].values():
            if integer(row.get('role')): ids.add(row['role'])
            for pair in row.get('thumbs') or []:
                if isinstance(pair, list) and pair and integer(pair[0]): ids.add(pair[0])
        for name in (COMMENT, 'KZoneMessageBoardCfg'):
            for row in tables[name].values():
                ids.update(value for value in row.get('roles') or [] if integer(value) and value >= 0)
        local_people = self.local(project, 'PersonCfg')
        local_profiles = self.local(project, 'KZoneProfileCfg')
        hidden = self.b.read_json(project.path/'StudentAgeStudio/goal-images.json', {})
        result = []
        for ident in sorted(ids):
            if str(ident) in hidden: continue
            key = str(ident)
            person, profile = people.get(key), profiles.get(key, {})
            if not person or not str(person.get('name') or '').strip(): continue  # Omit placeholder patch rows, not named social-only accounts.
            path = ''
            avatar = avatars.get(str(profile.get('icon')), {}) or avatars.get(str(person.get('kzoneHeadId')), {})
            path = avatar.get('icon') or ''
            if not path:
                urls = person.get('url') or person.get('url2') or []
                if isinstance(urls, list) and urls and isinstance(urls[0], str):
                    raw = urls[0].replace('\\', '/')
                    if raw.lower().startswith('mods/'):
                        p = PurePosixPath(raw)
                        path = str(p.with_name(p.stem + '_head' + p.suffix))
                    else: path = 'role_head/' + raw
            available = False
            if path:
                try:
                    self.store.project_asset(project, path)
                    available = True
                except self.b.ApiError: pass
            query = {'projectId': project.id, 'path': path}
            if token: query['token'] = token
            result.append({'id': ident, 'name': person.get('name') or ('白雨' if ident == 0 else '未命名账号'),
                           'personName': person.get('name') or '', 'profileName': profile.get('name') or '',
                           'source': 'mod' if key in local_people or key in local_profiles else 'original',
                           'avatarPath': path, 'avatarUrl': '/api/social-image?' + urllib.parse.urlencode(query) if path else '',
                           'avatarAvailable': available, 'description': profile.get('desc') or ''})
        return result

    def load(self, project_id, token=None):
        with self.store.lock:
            project = self.store.project(project_id)
            revision = self.store.revision(project)
            warnings = []
            posts, comments = self.local(project, POST, warnings), self.local(project, COMMENT, warnings)
            commands = self.store.workshop_info(project_id)['commands']
            reference_names = {'ConditionTypeCfg', 'PersonStateCfg', 'PersonCfg', 'PersonAttrCfg', 'EvtCfg', 'KZoneProfileCfg', 'KZoneAvatarCfg', 'KZoneColorCfg', POST, COMMENT}
            for templates in commands.values():
                if not isinstance(templates, list): continue
                for template in templates:
                    for parameter in template.get('parameters', []):
                        name = parameter.get('range', {}).get('table')
                        if name and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*Cfg', name): reference_names.add(name)
            refs, local_ids = {}, {}
            for name in sorted(reference_names):
                try:
                    local = self.local(project, name)
                    refs[name] = {**self.store.catalog_rows(name), **local}
                    local_ids[name] = list(local)
                except self.b.ApiError as error:
                    refs[name] = copy.deepcopy(self.store.catalog_rows(name))
                    local_ids[name] = []
                    warnings.append(error.message)
            accounts = self.accounts(project, token)
            editor = self.state(project)
            if revision != self.store.revision(project):
                raise self.b.ApiError('读取时模组发生了变化，请重新打开。', 409, 'conflict')
            return {'project': project.public(), 'revision': revision, 'posts': posts, 'comments': comments,
                    'referencePosts': copy.deepcopy(self.store.catalog_rows(POST)), 'referenceComments': copy.deepcopy(self.store.catalog_rows(COMMENT)),
                    'accounts': accounts, 'refs': refs, 'localIds': local_ids, 'commands': commands,
                    'defaults': {'post': copy.deepcopy(POST_DEFAULT), 'comment': copy.deepcopy(COMMENT_DEFAULT)},
                    'editor': editor, 'warnings': list(dict.fromkeys(warnings)),
                    'semantics': {'playerRole': 0, 'commentSuffixMin': 1, 'commentSuffixMax': 99,
                                  'emptyPostConditions': 'effect-only', 'replyParent': 'root-comment',
                                  'commentEffects': 'on-appearance', 'onePlayerChoicePerTarget': True}}

    def merged_incoming(self, incoming, previous, name):
        self.b.validate_map(incoming, name, allow_zero=True)
        return {key: {**copy.deepcopy(previous.get(key, {})), **copy.deepcopy(row)} for key, row in incoming.items()}

    def validate(self, project, posts, comments, previous_posts, previous_comments, editor):
        b, store = self.b, self.store
        base_posts, base_comments = store.catalog_rows(POST), store.catalog_rows(COMMENT)
        all_posts, all_comments = {**base_posts, **posts}, {**base_comments, **comments}
        old_posts, old_comments = {**base_posts, **previous_posts}, {**base_comments, **previous_comments}
        removed_comments = set(previous_comments) - set(comments) - set(base_comments)
        accounts = {str(row['id']) for row in self.accounts(project)}
        people = self.merged(project, 'PersonCfg')
        modified_posts = {key for key, row in posts.items() if row != previous_posts.get(key)}
        modified_comments = {key for key, row in comments.items() if row != previous_comments.get(key)}
        affected = set(modified_posts) | {str(int(key) // 100) for key in modified_comments}
        affected.update(set(previous_posts) - set(posts))
        affected.update(str(int(key) // 100) for key in set(previous_comments) - set(comments))
        if removed_comments:
            for kind, table in (('post', all_posts), ('comment', all_comments)):
                for key, row in table.items():
                    targets = [pair[0] for pair in row.get('comments') or [] if isinstance(pair, list) and pair] + (row.get('options') or []) + [row.get('parent', 0)]
                    if any(str(target) in removed_comments for target in targets):
                        affected.add(key if kind == 'post' else str(int(key) // 100))
        def field_changed(row, previous, field): return field not in previous or row.get(field) != previous.get(field)
        def commands(row, field):
            value = row.get(field) or []
            if not isinstance(value, list) or any(not isinstance(command, list) or not command or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in command) for command in value):
                raise b.ApiError('条件或效果格式无效，请重新选择。')
        for key in modified_posts:
            row, previous = posts[key], old_posts.get(key, {})
            if key not in previous_posts and key not in base_posts and not 1 <= int(key) <= 2147483647:
                raise b.ApiError('新动态编号必须在 1 至 2147483647 之间。')
            if field_changed(row, previous, 'role') and (not integer(row.get('role')) or str(row['role']) not in accounts):
                raise b.ApiError('请选择有效的企鹅空间发布账号。')
            if not isinstance(row.get('content'), str): raise b.ApiError('请输入动态内容。')
            if not isinstance(row.get('imgs', []), list) or any(not isinstance(path, str) for path in row.get('imgs', [])):
                raise b.ApiError('动态配图格式无效。')
            commands(row, 'cond')
            if field_changed(row, previous, 'thumbs'):
                for pair in row.get('thumbs') or []:
                    if not isinstance(pair, list) or not 1 <= len(pair) <= 2 or not integer(pair[0]) or str(pair[0]) not in people or (len(pair) == 2 and (not integer(pair[1]) or pair[1] < 0)):
                        raise b.ApiError('点赞账号或出现时间无效。')
        for key in modified_comments:
            row, previous = comments[key], old_comments.get(key, {})
            owner = str(int(key) // 100)
            if (owner not in all_posts or not 1 <= int(key) % 100 <= 99) and key not in old_comments:
                raise b.ApiError('评论必须属于一条已存在的动态，每条动态最多可有 99 条评论和可选回复。')
            roles = row.get('roles')
            if field_changed(row, previous, 'roles'):
                if not isinstance(roles, list) or not 1 <= len(roles) <= 2 or not integer(roles[0]) or str(roles[0]) not in accounts or (len(roles) == 2 and (not integer(roles[1]) or (roles[1] != -1 and str(roles[1]) not in accounts))):
                    raise b.ApiError('请选择有效的企鹅空间评论账号和回复对象。')
            if not isinstance(row.get('content'), str): raise b.ApiError('请输入评论内容。')
            commands(row, 'condition'); commands(row, 'effect')
            parent = row.get('parent', 0)
            if not integer(parent) or parent < 0: raise b.ApiError('回复的根评论无效。')
            if parent and field_changed(row, previous, 'parent'):
                parent_row = all_comments.get(str(parent))
                if not parent_row or parent // 100 != int(owner) or parent == int(key) or parent_row.get('parent', 0):
                    raise b.ApiError('回复必须归属于当前动态的根评论，不能将回复设为根评论。')
        disabled = editor.get('disabledOptions', {})
        for key, values in disabled.items():
            match = re.fullmatch(r'(post|comment):([0-9]+)', key)
            if not match or not isinstance(values, list): raise b.ApiError('暂存的白雨评论记录无效。')
            table = all_posts if match[1] == 'post' else all_comments
            if match[2] not in table:
                if not values: continue
                raise b.ApiError('暂存的白雨评论找不到对应动态或评论。')
            affected.add(match[2] if match[1] == 'post' else str(int(match[2]) // 100))
        # Validate changed post graphs as a unit, so deletion cannot leave dangling
        # child links or resurrect a disabled player response through auto-comments.
        for owner in affected:
            graph = {}
            rows = [('post', owner, all_posts[owner])] if owner in all_posts else []
            rows += [('comment', key, row) for key, row in all_comments.items() if int(key) // 100 == int(owner)]
            for kind, key, row in rows:
                previous = (old_posts if kind == 'post' else old_comments).get(key, {})
                if kind == 'comment' and str(row.get('parent', 0)) in removed_comments:
                    raise b.ApiError('删除根评论时需要一并移除或重新关联它的回复。')
                automatic, optional = row.get('comments') or [], row.get('options') or []
                hidden = disabled.get(kind + ':' + key, [])
                if not isinstance(automatic, list) or not isinstance(optional, list): raise b.ApiError('评论列表格式无效。')
                if optional != (previous.get('options') or []) and len(optional)>2:
                    raise b.ApiError('同一次白雨回复最多提供两个选项，可以在后续回复中继续创建子分支。')
                if not isinstance(automatic, list) or not isinstance(optional, list): raise b.ApiError('评论列表格式无效。')
                graph_key = kind + ':' + key
                targets, auto_ids = [], []
                for pair in automatic:
                    if not isinstance(pair, list) or not 1 <= len(pair) <= 2 or not integer(pair[0]) or (len(pair) == 2 and (not integer(pair[1]) or pair[1] < -1)):
                        raise b.ApiError('自动评论或出现时间无效。')
                    auto_ids.append(pair[0])
                if any(not integer(ident) for ident in optional + hidden): raise b.ApiError('白雨可选评论无效。')
                if len(set(optional + hidden)) != len(optional + hidden) or set(auto_ids) & set(optional + hidden):
                    raise b.ApiError('同一条评论不能同时自动发布和作为白雨的可选评论。')
                for ident in auto_ids + optional + hidden:
                    child = all_comments.get(str(ident))
                    existing = [pair[0] for pair in previous.get('comments') or [] if isinstance(pair, list) and pair] + (previous.get('options') or [])
                    if not child or ident // 100 != int(owner):
                        if ident in existing and str(ident) not in removed_comments: continue
                        raise b.ApiError('评论引用缺失，或属于另一条动态。')
                    if ident in optional + hidden and (child.get('roles') or [None])[0] != 0:
                        # Existing third-party option data is kept unchanged; new
                        # player-choice links always use the protagonist.
                        if ident not in (previous.get('options') or []): raise b.ApiError('白雨可选评论必须由白雨发出。')
                    if (kind == 'post' and child.get('parent', 0)) or (kind == 'comment' and child.get('parent', 0) != (row.get('parent', 0) or int(key))):
                        # Some original configurations deliberately use unusual
                        # placement. Do not prevent a text-only edit of that data.
                        if ident not in existing: raise b.ApiError('评论的根评论与它所在的回复位置不一致。')
                    targets.append('comment:' + str(ident))
                graph[graph_key] = targets
            visiting, visited = set(), set()
            def visit(node):
                if node in visiting: raise b.ApiError('评论回复不能形成循环。')
                if node in visited: return
                visiting.add(node)
                for child in graph.get(node, []): visit(child)
                visiting.remove(node); visited.add(node)
            for node in graph: visit(node)
            reachable, queue = set(), ['post:' + owner]
            while queue:
                node = queue.pop()
                if node in reachable: continue
                reachable.add(node); queue.extend(graph.get(node, []))
            if any('comment:' + key not in reachable for key in set(comments) - set(old_comments) if int(key) // 100 == int(owner)):
                raise b.ApiError('新评论尚未连接到动态，请通过动态或评论下方的评论按钮添加。')
            if owner in previous_posts and owner not in all_posts and any(int(key) // 100 == int(owner) for key in comments):
                raise b.ApiError('删除动态时需要一并删除它的评论。')

    def deletion_references(self, project, removed, posts, comments):
        if not removed: return []
        references = []
        for filename, path in self.store.cfg_table_files(project).items():
            name = filename.removesuffix('.json')
            rows = posts if name == POST else comments if name == COMMENT else self.b.read_json(path, {})
            if not isinstance(rows, dict): continue
            fields = {'effect', 'effects', 'effect2', 'condition', 'conditions', 'cond', 'check'}
            for field in self.store.table_schema(name).get('fields', []):
                if str(field.get('editorType', '')).lower() in {'effect', 'condition'}: fields.add(field.get('name'))
            for key, row in rows.items():
                if not isinstance(row, dict): continue
                for field in fields:
                    value = row.get(field)
                    if not isinstance(value, list): continue
                    for command in value:
                        if not isinstance(command, list) or len(command) < 3: continue
                        if command[0] == 23 and command[1] in (1, -1) and isinstance(command[2], (int, float)) and not isinstance(command[2], bool) and math.isfinite(command[2]) and command[2] == int(command[2]) and str(int(command[2])) in removed:
                            references.append(name + ' · ' + str(row.get('name') or row.get('title') or row.get('content') or key)[:40])
        return list(dict.fromkeys(references))[:12]

    def save(self, payload):
        with self.store.lock:
            project = self.store.project(payload.get('projectId'))
            if project.readonly: raise self.b.ApiError('订阅模组只能预览，请先复制为本地模组再编辑。', 403)
            revision = self.store.revision(project)
            save_review.revision(payload, revision, self.b.ApiError, '模组已被其他窗口修改，已保留当前草稿；请重新载入后保存。')
            previous_posts, previous_comments = [self.store.preserve_editing_rows(project,n,self.local(project,n)) for n in (POST,COMMENT)]
            posts = self.merged_incoming(payload.get('posts'), previous_posts, POST)
            comments = self.merged_incoming(payload.get('comments'), previous_comments, COMMENT)
            posts = self.store.preserve_editing_rows(project, POST, posts)
            comments = self.store.preserve_editing_rows(project, COMMENT, comments)
            if not isinstance(payload.get('editor', {}), dict): raise self.b.ApiError('企鹅动态编辑记录格式无效。')
            editor = {**self.state(project), **copy.deepcopy(payload.get('editor', {}))}
            if not isinstance(editor.get('disabledOptions'), dict): raise self.b.ApiError('白雨评论的暂存记录格式无效。')
            with save_review.checking(self.b.ApiError, '企鹅动态与评论'):
                self.validate(project, posts, comments, previous_posts, previous_comments, editor)
            removed = set(previous_posts) - set(posts) - set(self.store.catalog_rows(POST))
            references = self.deletion_references(project, removed, posts, comments)
            if references: save_review.warn(self.b.ApiError, '以下内容仍引用此动态，保存删除后相关功能可能失效：' + '；'.join(references), 409, 'referenced')
            changes = {'Cfgs/zh-cn/' + POST + '.json': self.b.json_bytes(posts),
                       'Cfgs/zh-cn/' + COMMENT + '.json': self.b.json_bytes(comments), STATE: self.b.json_bytes(editor)}
            backup = self.store.commit(project, changes, revision)
            return {'ok': True, 'revision': self.store.revision(project), 'backup': backup, 'posts': self.local(project, POST),
                    'comments': self.local(project, COMMENT), 'editor': editor, 'updatedTables': [POST, COMMENT]}
