"""Allocate native-compatible IDs and rename typed references in one transaction."""
from __future__ import annotations
import copy
import math
import json
import secrets
import gameplay_features
from pathlib import Path
from platform_support import file_fingerprint

POST = 'KZoneContentCfg'
COMMENT = 'KZoneCommentCfg'
LINKED = {'DIYCfg':'ItemCfg','BirthdayPaintGuessCfg':'PersonCfg','PersonGrowCfg': 'PersonCfg', 'KZoneProfileCfg': 'PersonCfg',
          'ModFaceCfg': 'PersonCfg', 'ActionEvtCfg': 'ActionCfg', 'ShopCfg': 'ItemCfg / BookCfg'}
DERIVED = {'TalkCfg': ('EvtCfg', 1000), 'OptionCfg': ('EvtCfg', 100),
           COMMENT: (POST, 100), 'ModFaceCfg': ('PersonCfg', 1000)}
CHILDREN = {'PersonCfg': ['PersonGrowCfg', 'KZoneProfileCfg', 'BirthdayPaintGuessCfg'], 'ActionCfg': ['ActionEvtCfg'],
            'ItemCfg': ['ShopCfg','DIYCfg'], 'BookCfg': ['ShopCfg']}


def rule(table, ident=None, owner=None):
    if table in DERIVED:
        parent, factor = DERIVED[table]
        owner = int(owner if owner is not None else int(ident or 0) // factor)
        # min/max are what the game accepts; start/end is only where automatic numbering looks first.
        return {'min': 1, 'max': 2147483647, 'start': owner * factor + 1, 'end': min(2147483647, owner * factor + factor - 1),
                'owner': owner, 'parent': parent, 'factor': factor, 'step': 1}
    return {'min': 1, 'max': 2147483647, 'start': 3000000 if table == 'BookCfg' else 1000000,
            'end': 3999999 if table == 'BookCfg' else 1999999, 'step': 1000 if table == 'PhoneMsgCfg' else 1}


class RecordIds:
    def __init__(self, store, backend):
        self.store, self.b = store, backend
        self.cache, self.reserved, self.history = {}, set(), {}

    def keys(self, path):
        stamp = file_fingerprint(path)
        if path not in self.cache or self.cache[path][0] != stamp:
            rows = self.b.read_json(path, {})
            if not isinstance(rows,dict): raise self.b.ApiError('配置表不是有效对象。')
            # Native loaders use dictionary keys; reserve them even when another
            # editor serializes a redundant row.id as a string or stale value.
            self.cache[path] = (stamp, {int(k) for k in rows if str(k).isdigit()})
        return self.cache[path][1]

    def check_exclusions(self):
        from storage_paths import preference_path
        from user_preferences import load
        saved = load(preference_path()).get('idCheckExcludedProjects', [])
        return {v for v in saved if isinstance(v, str)} if isinstance(saved, list) else set()

    def occupied(self, exclude=None, exclude_projects=()):
        catalog = self.store.catalog()
        names = set(catalog.get('tables', {})) | set(catalog.get('schemas', {})) | set(gameplay_features.NAMES)
        names.update(['EvtCfg', 'TalkCfg', 'OptionCfg', 'PersonCfg', POST, COMMENT, 'ModFaceCfg'])
        occupied = {n.removesuffix('.json'): {int(k) for k in self.store.catalog_rows(n.removesuffix('.json')) if str(k).isdigit()} for n in names}
        occupied.setdefault('TalkCfg', set()).update(int(k) for k in catalog.get('baseTalkIds', []) if str(k).isdigit())
        for project in self.store.projects():
            if project.id == exclude or project.id in exclude_projects: continue
            for name, path in self.store.cfg_table_files(project).items():
                try: occupied.setdefault(name[:-5], set()).update(self.keys(path))
                except (self.b.ApiError, OSError): continue  # Only known, readable configurations participate.
        return occupied

    def public(self, project_id):
        with self.store.lock, self.store.catalog_scope():
            project = self.store.project(project_id)
            used = self.occupied()
            # IDs allocated server-side since startup (e.g. by another window's
            # asset import) are not on disk yet; publish them so scaffolds in
            # this window never claim them.
            return {'projectId': project.id, 'revision': self.store.revision(project),
                    'tables': {n: sorted(v) for n, v in used.items() if v}, 'linked': LINKED,
                    'rules': {n: rule(n) for n in used if n not in DERIVED},
                    'reservedIds': sorted(self.reserved)}

    def allocate(self, table, rows=None, owner=None):
        with self.store.catalog_scope(): used = self.occupied()
        blocked = set().union(*used.values(), self.reserved, getattr(self, 'draft_reserved', set()), {int(k) for k in (rows or {}) if str(k).isdigit()})
        if table in ('EvtCfg', POST, 'PersonCfg'):
            for child, (parent, factor) in DERIVED.items():
                if parent == table: blocked.update(i // factor for i in used.get(child, ()))
        if table == 'PhoneMsgCfg':
            blocked.update(i // 1000 * 1000 + 1 for i in used.get(table, ()))
        r = rule(table, owner=owner)
        low, high, step = r['start'], r['end'], r['step']
        if step == 1000: low += 1
        count = (high - low) // step + 1
        if count <= 0: raise self.b.ApiError('所属内容的编号超出可用范围。')
        start = 0 if table == 'TalkCfg' else secrets.randbelow(count)
        for offset in range(count):
            ident = low + (start + offset) % count * step
            if ident not in blocked:
                self.reserved.add(ident)
                return ident
        # The preferred block is full: fall back to the rest of the game's range.
        # Probes stay bounded so a saturated registry raises instead of hanging
        # the request thread in a billions-long scan.
        for ident in range(high + step, min(2147483647, high + step + 100000 * step), step):
            if ident not in blocked:
                self.reserved.add(ident)
                return ident
        raise self.b.ApiError('这一类可用编号已用尽。')

    def validate_created(self, project, changes, allowed_ids=None):
        """Report (never refuse) new IDs that another mod already uses."""
        candidates = {}
        with self.store.catalog_scope():
            for relative, data in changes.items():
                if not relative.startswith('Cfgs/zh-cn/') or not relative.endswith('Cfg.json'): continue
                table = Path(relative).stem
                path = self.b.safe_path(project.path, relative)
                old = self.keys(path) if path.exists() else set()
                new = {int(k) for k in json.loads(data) if str(k).isdigit()} - old
                # Only an explicit manual rename (including its undo/redo) may
                # reuse external IDs. Automatically created records still check.
                new -= set((allowed_ids or {}).get(table, ()))
                # A native override is deliberate; its ID is owned by the game.
                new -= {int(k) for k in self.store.catalog_rows(table) if str(k).isdigit()}
                if new: candidates[table] = new
            if not candidates: return []
            occupied = self.occupied(exclude=project.id, exclude_projects=self.check_exclusions())
            notes = []
            for table, ids in candidates.items():
                conflict = sorted(ids & occupied.get(table, set()))
                if conflict: notes.append(f'{table} 的 ID {"、".join(map(str, conflict[:5]))}{"…" if len(conflict) > 5 else ""} 已被其他模组使用，同时启用时会互相覆盖。')
            return notes

    def collision_report(self, payload):
        """Read source names for advisory conflicts without editing any project."""
        with self.store.lock, self.store.catalog_scope():
            project = self.store.project(payload.get('projectId'))
            table = self.store.table_name(payload.get('table'))
            old, ident = self._id(payload.get('oldId')), self._id(payload.get('newId'))
            related = {child: factor for child, (parent, factor) in DERIVED.items() if parent == table}
            related.update({child: 1 for child in CHILDREN.get(table, ())})
            tables = {table, *related}
            conflicts = []
            excluded = self.check_exclusions()

            def collect(source, name, rows):
                matches = ([ident] if ident in rows else []) if name == table else (
                    [min(found)] if (found := [i for i in rows if i // related[name] == ident]) else [])
                kind = 'id' if name == table else 'related'
                if not matches and name == table == 'PhoneMsgCfg' and old % 1000 == 1:
                    found = [i for i in rows if i // 1000 == ident // 1000]
                    if found: matches, kind = [min(found)], 'related'
                if matches: conflicts.append({**source, 'table': name, 'id': matches[0], 'kind': kind})

            for name in sorted(tables):
                rows = {int(k) for k in self.store.catalog_rows(name) if str(k).isdigit()}
                if name == 'TalkCfg': rows.update(int(k) for k in self.store.catalog().get('baseTalkIds', []) if str(k).isdigit())
                collect({'projectId': None, 'name': '原版游戏', 'source': 'original'}, name, rows)
            for other in self.store.projects():
                if other.id == project.id or other.id in excluded: continue
                for filename, path in self.store.cfg_table_files(other).items():
                    name = filename.removesuffix('.json')
                    if name not in tables: continue
                    try: rows = self.keys(path)
                    except (self.b.ApiError, OSError): continue
                    collect({'projectId': other.id, 'name': other.name,
                             'source': 'workshop' if other.readonly else 'local'}, name, rows)
            return {'id': ident, 'conflicts': conflicts}

    def _id(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit() or not 0 < int(value) <= 2147483647:
            raise self.b.ApiError('ID 必须是 1 至 2147483647 之间的整数。')
        return int(value)

    @staticmethod
    def remap(value, mapping):
        if isinstance(value, list): return [RecordIds.remap(v, mapping) for v in value]
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value): return mapping.get(str(int(value)), value) if value == int(value) else value
        return value

    def rewrite(self, table, rows, mappings):
        result = copy.deepcopy(rows)
        schema = self.store.table_schema(table)
        fields = {f['name']: f for f in schema.get('fields', [])}
        explicit = {'TalkCfg': {'nextTalk':'TalkCfg','nextTalk2':'TalkCfg','option':'OptionCfg','roleIds':'PersonCfg','highlights':'PersonCfg','bg':'BgCfg','audio':'AudioCfg','vocals':'AudioCfg'},
                    'NegotiationCfg':{'talks':'TalkCfg','talks2':'TalkCfg'},
                    'TalkInputMinigameCfg':{'talkId':'TalkCfg','jumps':'TalkCfg'},
                    'LoveDrawCfg':{'talkId':'TalkCfg'}, 'LoveGreetingCfg':{'talkId':'TalkCfg'}, 'NpcActivityCfg':{'talkId':'TalkCfg'},
                    'MinigameActionCfg':{'startTalk':'TalkCfg','winTalk':'TalkCfg','loseTalk':'TalkCfg'},
                    'OptionCfg': {'talkId':'TalkCfg','talkId2':'TalkCfg','nextEvtId':'EvtCfg'},
                    'EvtCfg': {'talkId':'TalkCfg','options':'OptionCfg','npc':'PersonCfg'}, 'ActionCfg':{'evtId':'EvtCfg'}, 'ActionEvtCfg':{'evts':'EvtCfg'}, POST:{'role':'PersonCfg','options':COMMENT},
                    COMMENT:{'roles':'PersonCfg','options':COMMENT,'parent':COMMENT},
                    'KZoneMessageBoardCfg':{'roles':'PersonCfg','reply':'KZoneMessageBoardCfg'},
                    'KZoneProfileCfg':{'icon':'KZoneAvatarCfg','bgm':'AudioCfg'}, 'PersonCfg':{'kzoneHeadId':'KZoneAvatarCfg','clickAudio':'AudioCfg'},
                    'GiftEvtCfg':{'npc':'PersonCfg','item':'ItemCfg / BookCfg','talkId':'TalkCfg'}, 'PhoneMsgCfg':{'role':'PersonCfg','next':'PhoneMsgCfg'}, 'InteractCfg':{'npc':'PersonCfg','talkId':'TalkCfg','map':'MapCfg'}, 'IntentCfg':{'npc':'PersonCfg','before':'IntentCfg','finishTalk':'TalkCfg','failTalk':'TalkCfg'}, 'PersonGrowCfg':{'focusAttrId':'PersonAttrCfg','trait':'TraitsCfg','speciality':'TraitsCfg','state':'PersonStateCfg'},
                    'BgCfg':{'audio':'AudioCfg','gaozhongUrl':'BgCfg'}}
        commands = self.store.catalog().get('commands', {})
        templates = {k: list(commands.get(k, [])) + self.b.read_json(Path(__file__).with_name(k+'-templates.json'), []) for k in ('condition','effect')}
        for row in result.values():
            if not isinstance(row, dict): continue
            for name, value in list(row.items()):
                if name == 'id': continue
                if table == 'TalkCfg' and name == 'studioSocialEffects' and isinstance(value,dict):
                    row[name]={str(self.remap(int(k),mappings.get('EvtCfg',{}))):self.rewrite('EvtCfg',{'0':{'id':0,'effect':v}},mappings)['0']['effect'] for k,v in value.items()}
                    continue
                if table == 'TalkCfg' and name == 'studioLighting' and isinstance(value,dict):
                    row[name]={str(self.remap(int(k),mappings.get('PersonCfg',{}))):v for k,v in value.items()}
                    continue
                if table == 'EvtCfg' and name == 'studioSocial' and isinstance(value,dict):
                    for field,target in [('actionId','ActionCfg'),('unlockedActionId','ActionCfg'),('interactionId','InteractCfg'),('minigameActionId','MinigameActionCfg'),('previousStartTalk','TalkCfg')]:
                        if field in value:value[field]=self.remap(value[field],mappings.get(target,{}))
                    nested=self.rewrite('EvtCfg',{'0':{'id':0,'condition':value.get('conditions',[]),'effect':value.get('effects',[])}},mappings)['0']
                    value.update(conditions=nested['condition'],effects=nested['effect'])
                    if 'entryConditions' in value:value['entryConditions']=self.rewrite('EvtCfg',{'0':{'id':0,'condition':value['entryConditions']}},mappings)['0']['condition']
                    continue
                if table == 'EvtCfg' and name == 'studioGiftBindings' and isinstance(value, list):
                    for binding in value:
                        if isinstance(binding, dict):
                            binding['id'] = self.remap(binding.get('id'), mappings.get('GiftEvtCfg', {}))
                            if 'npc' in binding: binding['npc'] = self.remap(binding['npc'], mappings.get('PersonCfg', {}))
                    continue
                if table == 'GiftEvtCfg' and name in ('talkId', 'item'):
                    mapping = mappings.get('TalkCfg', {}) if name == 'talkId' else {**mappings.get('ItemCfg', {}), **mappings.get('BookCfg', {})}
                    row[name] = self.remap(value, mapping)
                    continue
                f = fields.get(name, {})
                reference = explicit.get(table, {}).get(name) or (f.get('range') or {}).get('table')
                reference = str(reference or '').split('.')[-1]
                pairs = []
                if table in (POST, COMMENT) and name == 'comments': pairs = [(0, COMMENT)]
                elif table == POST and name == 'thumbs': pairs = [(0, 'PersonCfg')]
                elif table == 'TalkCfg' and name == 'roles': pairs = [(0, 'PersonCfg')]
                elif f.get('itemFields'): pairs = [(p['index'], (p.get('range') or {}).get('table')) for p in f['itemFields'] if (p.get('range') or {}).get('table')]
                if pairs and isinstance(value, list):
                    for pair in value:
                        if isinstance(pair, list):
                            for index, target in pairs:
                                if index < len(pair): pair[index] = self.remap(pair[index], mappings.get(target, {}))
                elif reference in mappings:
                    if f.get('listDepth', 0) >= 2 and isinstance(value, list):
                        for pair in value:
                            if isinstance(pair, list) and pair: pair[0] = self.remap(pair[0], mappings[reference])
                    else: row[name] = self.remap(value, mappings[reference])
                if table == 'TalkCfg' and name == 'screenEffect' and isinstance(value,list) and len(value)>1 and value[0]==4015:
                    value[1] = self.remap(value[1], mappings.get('CGCfg', {}))
                if table=='TalkCfg' and name=='screenEffect' and isinstance(value,list) and len(value)>1:
                    if value[0] in (4007,4018):value[1]=self.remap(value[1],mappings.get('BgCfg',{}))
                    if value[0]==4004:value[1]=self.remap(value[1],mappings.get('ItemCfg',{}))
                    if value[0]==4007:value[2:]=[self.remap(v,mappings.get('PersonCfg',{})) for v in value[2:]]
                kind = str(f.get('editorType', '')).lower()
                if kind not in templates:
                    kind = 'effect' if name in ('effect','effects','effect2','usingEffect','reward') else 'condition' if name in ('condition','conditions','cond','check','precondition') else None
                if kind and isinstance(value,list):
                    for command in value:
                        if not isinstance(command,list): continue
                        before = command[:]
                        for template in templates[kind]:
                            if len(before)!=len(template.get('template',[])) or not all(int(i)<len(before) and before[int(i)]==v for i,v in template.get('match',{}).items()): continue
                            for p in template.get('parameters',[]):
                                ref = (p.get('range') or {}).get('table')
                                if ref in mappings and p.get('index',len(command))<len(command): command[p['index']] = self.remap(before[p['index']],mappings[ref])
                        if len(before)>=3:
                            target=None
                            if before[0]==111 or before[0]==50 and before[1] in (1,2,4,20,100) or before[0]==3 and abs(before[1])==1:target='EvtCfg'
                            elif before[0]==40 and before[1] in (1,-1,10):target='ActionCfg'
                            elif before[0]==7 and before[1] in (0,1,-1,101,9001,9002,9003,9004,9005,9006):target='PersonCfg'
                            if target:command[2]=self.remap(before[2],mappings.get(target,{}))
                            if before[0]==7 and before[1]==101:command[3:]=self.remap(before[3:],mappings.get('MapCfg',{}))
        return result

    def editor_changes(self, project, mappings):
        m = lambda table,v:self.remap(v,mappings.get(table,{}))
        result = {}
        for filename in ('editor-state.json','audio-cues.json','deleted-talks.json','social-state.json','character-outfits.json','character-romance.json','space-layouts.json','goal-images.json','message-state.json'):
            relative = 'StudentAgeStudio/'+filename
            path = self.b.safe_path(project.path,relative)
            if not path.exists(): continue
            old = self.b.read_json(path,{})
            if not isinstance(old,dict): raise self.b.ApiError('编辑记录格式异常，不能安全修改编号。')
            data = copy.deepcopy(old)
            if filename=='message-state.json':
                for field in ('titles','previewDelays'):
                    if field in data:data[field]={str(m('PhoneMsgCfg',int(k))):v for k,v in data[field].items()}
            elif filename in ('goal-images.json','space-layouts.json','character-romance.json'):
                data={str(m('PersonCfg',int(k))):v for k,v in data.items()}
                if filename=='character-romance.json':
                    for key,row in data.items():
                        if 'conditions' in row:row['conditions']=self.rewrite('EvtCfg',{'0':{'id':0,'condition':row['conditions']}},mappings)['0']['condition']
            elif filename=='character-outfits.json':
                data={str(m('PersonCfg',int(k))):v for k,v in data.items()}
                for outfits in data.values():
                    for outfit in outfits.values():
                        outfit['backgrounds']=m('BgCfg',outfit.get('backgrounds',[]))
            elif filename=='editor-state.json':
                if 'externalDialogueIds' in data:data['externalDialogueIds']=m('TalkCfg',data['externalDialogueIds'])
                for folder in data.get('externalDialogueFolders',{}).values():
                    if 'giftEventId' in folder:folder['giftEventId']=m('EvtCfg',folder['giftEventId'])
                    if 'talkIds' in folder:folder['talkIds']=m('TalkCfg',folder['talkIds'])
                    from external_usages import KINDS
                    for use in folder.get('uses',[]):
                        definition=KINDS.get(use.get('kind'))
                        if not definition:continue
                        target_table=definition['table']
                        if 'entryId' in use:use['entryId']=m('TalkCfg',use['entryId'])
                        if 'recordId' in use:use['recordId']=m(target_table,use['recordId'])
                        if 'npc' in use:use['npc']=m('PersonCfg',use['npc'])
                        if 'item' in use:use['item']=self.remap(use['item'],{**mappings.get('ItemCfg',{}),**mappings.get('BookCfg',{})})
                        for field in ('params','baseParams'):
                            if field in use:use[field]=self.rewrite(target_table,{'0':use[field]},mappings)['0']
                        target=use.get('_target')
                        if target:
                            target['recordId']=m(target_table,target['recordId'])
                            target['previous']=m('TalkCfg',target['previous'])
                            target['written']=m('TalkCfg',target['written'])
                if 'talkOwners' in data:data['talkOwners']={str(m('TalkCfg',int(k))):m('EvtCfg',v) for k,v in data['talkOwners'].items()}
                if 'order' in data: data['order']=m('TalkCfg',data['order'])
                if 'lighting' in data:data['lighting']={str(m('TalkCfg',int(k))):{str(m('PersonCfg',int(role))):v for role,v in actors.items()} for k,actors in data['lighting'].items()}
                folders={}
                for key,f in data.get('branchFolders',{}).items():
                    parts=key.split(':');parts[0]=str(m('TalkCfg',int(parts[0])))
                    if len(parts)==2 and parts[1].isdigit():parts[1]=str(m('OptionCfg',int(parts[1])))
                    for field in ('parentTalkId','routerId','exitId','endId','talkIds','baseNext','failureNext'):
                        if field in f:f[field]=m('TalkCfg',f[field])
                    if 'optionId' in f:f['optionId']=m('OptionCfg',f['optionId'])
                    c=f.get('continuation',{})
                    for field,table in [('eventId','EvtCfg'),('talkId','TalkCfg'),('targets','TalkCfg')]:
                        if field in c:c[field]=m(table,c[field])
                    folders[':'.join(parts)]=f
                if 'branchFolders' in data:data['branchFolders']=folders
                for p in data.get('premises',{}).values():
                    if 'eventId' in p:p['eventId']=m('EvtCfg',p['eventId'])
                    if 'event' in p:p['event']=m('EvtCfg',p['event'])
                for p in data.get('premises',{}).values():
                    if 'talkId' in p:p['talkId']=m('TalkCfg',p['talkId'])
                for key,table in [('talks','TalkCfg'),('options','OptionCfg'),('events','EvtCfg')]:
                    if key in data.get('pinnedIds',{}):data['pinnedIds'][key]=m(table,data['pinnedIds'][key])
                associations=data.get('assetAssociations',{})
                if 'cg' in associations:
                    associations['cg']={str(m('CGCfg',int(k))):v for k,v in associations['cg'].items()}
                    for v in associations['cg'].values():
                        if 'personIds' in v:v['personIds']=m('PersonCfg',v['personIds'])
            elif filename=='audio-cues.json':
                if 'nativeSnapshot' in data:data['nativeSnapshot']={str(m('TalkCfg',int(k))):m('AudioCfg',v) for k,v in data['nativeSnapshot'].items()}
                if 'nativeAudio' in data:data['nativeAudio']={str(m('TalkCfg',int(k))):m('AudioCfg',v) for k,v in data['nativeAudio'].items()}
                if 'sfx' in data:
                    data['sfx']={str(m('TalkCfg',int(k))):v for k,v in data['sfx'].items()}
                    for entries in data['sfx'].values():
                        for item in entries:item['audioId']=m('AudioCfg',item['audioId'])
                for item in data.get('bgm',[]):
                    item['audioId']=m('AudioCfg',item['audioId']);item['talkIds']=m('TalkCfg',item.get('talkIds',[]))
            elif filename=='deleted-talks.json':
                data={str(m('TalkCfg',int(k))):m('TalkCfg',v) for k,v in data.items()}
            elif filename=='social-state.json':
                disabled={}
                for key,values in data.get('disabledOptions',{}).items():
                    kind,ident=key.split(':');disabled[kind+':'+str(m(POST if kind=='post' else COMMENT,int(ident)))]=m(COMMENT,values)
                if 'disabledOptions' in data:data['disabledOptions']=disabled
            if data!=old:result[relative]=self.b.json_bytes(data)
        return result

    def rename(self, payload):
        with self.store.lock, self.store.catalog_scope():
            project=self.store.project(payload.get('projectId'),writable=True)
            revision=self.store.revision(project)
            if payload.get('revision')!=revision:raise self.b.ApiError('模组已变化，请重新打开编号设置。',409,'conflict')
            table=self.store.table_name(payload.get('table'));old=self._id(payload.get('oldId'));new=self._id(payload.get('newId'))
            if table in LINKED:raise self.b.ApiError('此编号随 '+LINKED[table]+' 同步，请修改所属内容的 ID。')
            files=self.store.cfg_table_files(project)
            originals={name[:-5]:self.b.read_json(path,{}) for name,path in files.items()}
            for name,values in originals.items():
                if not isinstance(values,dict) or any(not str(k).isdigit() or not isinstance(v,dict) for k,v in values.items()):raise self.b.ApiError('配置表格式异常，不能安全修改编号。')
            if str(old) not in originals.get(table,{}):raise self.b.ApiError('只能修改当前模组内已有内容的 ID，请先保存。')
            r=rule(table,old)
            if old==new:return {'ok':True,'revision':revision,'mappings':{},'updatedTables':[]}
            if not 1<=new<=2147483647:raise self.b.ApiError('ID 应为 1 到 2147483647 之间的整数。')
            if table=='PhoneMsgCfg' and old%1000==1 and new%1000!=1:raise self.b.ApiError('短信首句 ID 必须以 001 结尾。')
            rows=copy.deepcopy(originals);mappings={table:{str(old):new}}
            # A number already used inside this mod is never refused: the two records swap
            # places (their derived children move with them) instead of blocking the change.
            swap=str(new) in originals.get(table,{}) and not (table=='PhoneMsgCfg' and old%1000==1)
            if swap:mappings[table][str(new)]=old
            for values in rows.values():
                for k,v in values.items():v['id']=int(k)
            def derive(child,factor):
                merged={**self.store.catalog_rows(child),**rows.get(child,{})} if str(old) in self.store.catalog_rows(table) else rows.get(child,{})
                for key,row in list(merged.items()):
                    if int(key)//factor==old:
                        mappings.setdefault(child,{})[key]=new*factor+int(key)%factor
                        rows.setdefault(child,{})[key]=copy.deepcopy(row)
                    elif swap and int(key)//factor==new and key in rows.get(child,{}):
                        mappings.setdefault(child,{})[key]=old*factor+int(key)%factor
            if table=='EvtCfg':derive('TalkCfg',1000);derive('OptionCfg',100)
            if table==POST:derive(COMMENT,100)
            if table=='PersonCfg':derive('ModFaceCfg',1000)
            for child in CHILDREN.get(table,[]):
                row=rows.get(child,{}).get(str(old))
                if row is None and str(old) in self.store.catalog_rows(table):row=self.store.catalog_rows(child).get(str(old))
                if row is not None:rows.setdefault(child,{})[str(old)]=copy.deepcopy(row);mappings.setdefault(child,{})[str(old)]=new
                if swap and str(new) in rows.get(child,{}):mappings.setdefault(child,{})[str(new)]=old
            if table=='PhoneMsgCfg' and old%1000==1:
                for key in rows.get(table,{}):
                    if int(key)//1000==old//1000:mappings[table][key]=new//1000*1000+int(key)%1000
            if table=='PhoneMsgCfg' and old%1000==1 and old//1000!=new//1000:
                for key in list(rows.get(table,{})):
                    if int(key)//1000==new//1000:mappings[table][key]=old//1000*1000+int(key)%1000
            if any(after>2147483647 for mapping in mappings.values() for after in mapping.values()):
                raise self.b.ApiError('关联记录的编号超出游戏范围。')
            for name,mapping in mappings.items():
                # Anything still in the way trades places with the record moving there.
                for before,after in list(mapping.items()):
                    if str(after) in rows.get(name,{}) and str(after) not in mapping:mapping[str(after)]=int(before)
            changes={}
            for name,values in rows.items():
                revised=self.rewrite(name,values,mappings)
                if name in mappings:
                    revised={str(mappings[name].get(key,int(key))):{**row,'id':mappings[name].get(key,int(key))} for key,row in revised.items()}
                if revised!=originals.get(name,{}):changes['Cfgs/zh-cn/'+name+'.json']=self.b.json_bytes(revised)
            changes.update(self.editor_changes(project,mappings))
            return self.commit(project,changes,revision,mappings)

    def commit(self,project,changes,revision,mappings):
        original={name:(self.b.safe_path(project.path,name).read_bytes() if self.b.safe_path(project.path,name).exists() else b'{}') for name in changes}
        backup=self.store.commit(project,changes,revision,allowed_record_ids={name:set(mapping.values()) for name,mapping in mappings.items()})
        after=self.store.revision(project);token=secrets.token_hex(16)
        self.history[token]={'project':project.id,'revision':after,'changes':original,'mappings':{table:{str(v):int(k) for k,v in m.items()} for table,m in mappings.items()}}
        while len(self.history)>1 and (len(self.history)>30 or sum(len(raw) for entry in self.history.values() for raw in entry['changes'].values())>64*1024*1024):self.history.pop(next(iter(self.history)))
        return {'ok':True,'revision':after,'mappings':mappings,'undoToken':token,'backup':backup,
                'updatedTables':[Path(name).stem for name in changes if name.startswith('Cfgs/')]}

    def undo(self,payload):
        with self.store.lock:
            project=self.store.project(payload.get('projectId'),writable=True);entry=self.history.get(payload.get('token'))
            if not entry or entry['project']!=project.id:raise self.b.ApiError('这次编号修改的撤销记录已不可用。')
            if self.store.revision(project)!=entry['revision']:raise self.b.ApiError('编号修改后已有其他保存，不能直接撤销这次编号修改。',409,'conflict')
            result=self.commit(project,entry['changes'],entry['revision'],entry['mappings'])
            del self.history[payload['token']]
            return result
