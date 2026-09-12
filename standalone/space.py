import save_review
"""Transactional Penguin profiles, avatar registrations and message boards."""
from storage_paths import game_cache, auxiliary_cache
import copy
import math
from headshots import head_paths, crop_head, has_affection
from asset_labels import asset_name

PROFILE = 'KZoneProfileCfg'
BOARD = 'KZoneMessageBoardCfg'
AVATAR = 'KZoneAvatarCfg'
DEFAULT = dict(id=0, name='', desc='', icon=0, marriage=[], hometown='', living='', job='', school='', isVip=0, theme=1, bgm=0, font=101, fontColor=201, fontSize=40)


class SpaceEditor:
    def __init__(self, store, backend):
        self.store, self.b = store, backend

    def local(self, project, name): return self.store.social.local(project, name)
    def merged(self, project, name): return {**self.store.catalog_rows(name), **self.local(project, name)}

    def load(self, project_id):
        with self.store.lock:
            p = self.store.project(project_id)
            people = self.merged(p, 'PersonCfg')
            local_people = self.local(p, 'PersonCfg')
            from character_rules import references
            fonts = references(self.store,p)['KZoneFontCfg']
            layouts = self.b.read_json(p.path/'StudentAgeStudio/space-layouts.json',{})
            if not isinstance(layouts,dict): raise self.b.ApiError('空间位置配置损坏，请保留文件后修复。')
            return {'project':p.public(), 'revision':self.store.revision(p),
                    'profiles':self.local(p, PROFILE), 'messages':self.local(p, BOARD), 'avatars':self.local(p, AVATAR),
                    'referenceProfiles':self.store.catalog_rows(PROFILE), 'referenceMessages':self.store.catalog_rows(BOARD),
                    'referenceAvatars':self.store.catalog_rows(AVATAR), 'themes':self.merged(p, 'KZoneColorCfg'),
                    'audio':{k:{**v, 'displayName':asset_name(v, 'audio')} for k,v in self.merged(p,'AudioCfg').items() if v.get('type') == 1},
                    'people':[{'id':int(k),'name':r['name'],'custom':k in local_people,'kzoneHeadId':r.get('kzoneHeadId',0),'hasAffection':has_affection(r)} for k,r in people.items() if r.get('name')],
                    'posts':self.merged(p,'KZoneContentCfg'), 'fonts':fonts, 'layouts':layouts, 'defaults':copy.deepcopy(DEFAULT)}

    def head(self, project_id, person_id):
        with self.store.lock:
            p = self.store.project(project_id)
            person = self.merged(p, 'PersonCfg').get(str(person_id))
            if not person: raise self.b.ApiError('找不到这个人物。', 404)
            for resource in head_paths(person):
                try: return self.store.project_asset(p, resource)
                except self.b.ApiError: pass
            for field in ('url','url2'):
                values = person.get(field) or []
                for resource in values if isinstance(values,list) else [values]:
                    try:
                        path = self.store.project_asset(p, resource)
                        return crop_head(path,game_cache(self.store.game) / 'headshot-cache')
                    except self.b.ApiError: pass
            raise self.b.ApiError('此人物尚未提供头像或立绘。', 404)

    def save(self, payload):
        with self.store.lock:
            p = self.store.project(payload.get('projectId'), writable=True)
            revision = self.store.revision(p)
            if payload.get('revision') != revision: raise self.b.ApiError('模组已被其他窗口修改，请保留草稿后重新载入。',409,'conflict')
            old_layouts = self.b.read_json(p.path/'StudentAgeStudio/space-layouts.json',{})
            if not isinstance(old_layouts,dict): raise self.b.ApiError('空间位置配置损坏，请保留文件后修复。')
            layouts = copy.deepcopy(payload.get('layouts',old_layouts))
            if not isinstance(layouts,dict): raise self.b.ApiError('空间位置配置无效。')
            for key,layout in layouts.items():
                if not str(key).isdigit() or not isinstance(layout,dict): raise self.b.ApiError('空间位置配置无效。')
                if layout == old_layouts.get(key): continue
                if not isinstance(layout.get('signature',{}),dict): raise self.b.ApiError('签名位置配置无效。')
                for axis in ('x','y'):
                    value=layout.get('signature',{}).get(axis,0)
                    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1: raise self.b.ApiError('签名位置需要在预览范围内。')
                if layout.get('background'): self.store.project_asset(p,layout['background'])
                layouts[key]={**old_layouts.get(key,{}),**layout}
            fields = {'profiles':PROFILE,'messages':BOARD,'avatars':AVATAR}
            old = {key:self.store.preserve_editing_rows(p,name,self.local(p,name)) for key,name in fields.items()}
            rows = {key:self.store.social.merged_incoming(payload.get(key),old[key],name) for key,name in fields.items()}
            rows = {key:self.store.preserve_editing_rows(p,name,rows[key]) for key,name in fields.items()}
            merged = {key:{**self.store.catalog_rows(name),**rows[key]} for key,name in fields.items()}
            people = self.merged(p,'PersonCfg'); themes = self.merged(p,'KZoneColorCfg'); audio = self.merged(p,'AudioCfg')
            with save_review.checking(self.b.ApiError, '企鹅空间资料与留言'):
                for key,row in rows['profiles'].items():
                    if row == old['profiles'].get(key): continue
                    previous = old['profiles'].get(key,self.store.catalog_rows(PROFILE).get(key,{}))
                    if key not in people: raise self.b.ApiError('企鹅空间需要关联已保存的人物。')
                    for field in ('hometown','living','job','school'):
                        if field in row and not isinstance(row[field],str): raise self.b.ApiError('空间资料需要填写文字。')
                    if row.get('marriage') != previous.get('marriage') and (not isinstance(row.get('marriage'),list) or any(not isinstance(v,str) for v in row['marriage'])): raise self.b.ApiError('感情状态需要填写文字。')
                    if row.get('fontSize') != previous.get('fontSize') and (type(row.get('fontSize')) is not int or not 40<=row['fontSize']<=80): raise self.b.ApiError('原版签名字号范围为 40–80。')
                    from character_rules import references
                    fonts=references(self.store,p)['KZoneFontCfg']
                    for field,is_color in [('font',False),('fontColor',True)]:
                        if row.get(field) != previous.get(field) and fonts:
                            font=fonts.get(str(row.get(field)))
                            if not font or bool(font.get('colors')) != is_color: raise self.b.ApiError('请选择有效的签名字体或颜色。')
                    for field in ('name','desc'):
                        if not isinstance(row.get(field),str): raise self.b.ApiError('请填写企鹅昵称和个性签名。')
                    if row.get('isVip') not in (0,1): raise self.b.ApiError('黄钻设置无效。')
                    theme = row.get('theme',1)
                    if not isinstance(theme,int) or str(theme) not in themes: raise self.b.ApiError('请选择有效的个性名片。')
                    # Permit unchanged vanilla themes, including the game's non-VIP themes.
                    if not row['isVip'] and theme != 1 and theme != previous.get('theme',1): raise self.b.ApiError('请先开通黄钻，再选择个性名片。')
                    for field,reference,label in [('icon',merged['avatars'],'头像'),('bgm',audio,'背景音乐')]:
                        value = row.get(field,0)
                        if not isinstance(value,int) or isinstance(value,bool) or (value and str(value) not in reference): raise self.b.ApiError('请选择有效的'+label+'。')
                        if field == 'bgm' and value and reference[str(value)].get('type') != 1: raise self.b.ApiError('空间音乐请选择背景音乐。')
                for key,row in rows['avatars'].items():
                    if row == old['avatars'].get(key): continue
                    if not isinstance(row.get('icon'),str): raise self.b.ApiError('请先选择或导入头像图片。')
                    self.store.project_asset(p,row['icon'])
                removed = set(old['avatars'])-set(rows['avatars'])-set(self.store.catalog_rows(AVATAR))
                if any(str(row.get('icon',0)) in removed for row in merged['profiles'].values()) or any(str(row.get('kzoneHeadId',0)) in removed for row in people.values()): raise self.b.ApiError('头像仍被人物或空间使用，无法删除。')
                removed_messages = set(old['messages'])-set(rows['messages'])-set(self.store.catalog_rows(BOARD))
                for key,row in rows['messages'].items():
                    if row == old['messages'].get(key): continue
                    roles = row.get('roles')
                    if not isinstance(roles,list) or len(roles)!=2 or any(not isinstance(x,int) or isinstance(x,bool) or str(x) not in people for x in roles): raise self.b.ApiError('请选择留言人物和空间主人。')
                    if str(roles[1]) not in merged['profiles']: raise self.b.ApiError('请先为这个人物添加企鹅空间。')
                    if not isinstance(row.get('content',''),str): raise self.b.ApiError('留言内容必须是文字。')
                    if not isinstance(row.get('round',0),int) or row.get('round',0)<0: raise self.b.ApiError('留言时间无效。')
                    cond = row.get('cond',[])
                    if not isinstance(cond,list) or any(not isinstance(c,list) or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in c) for c in cond): raise self.b.ApiError('留言条件格式无效。')
                    reply = row.get('reply',0)
                    if reply:
                        parent = merged['messages'].get(str(reply))
                        if not parent or reply == row['id'] or parent.get('roles',[None,None])[1] != roles[1]: raise self.b.ApiError('留言回复必须属于同一个空间。')
                if any(str(row.get('reply',0)) in removed_messages for row in merged['messages'].values()): raise self.b.ApiError('这条留言仍有回复，请先移除回复。')
            changes = {'Cfgs/zh-cn/'+name+'.json':self.b.json_bytes(rows[key]) for key,name in fields.items()}
            if layouts != old_layouts: changes['StudentAgeStudio/space-layouts.json']=self.b.json_bytes(layouts)
            backup = self.store.commit(p,changes,revision)
            rows = {key:self.local(p, name) for key,name in fields.items()}
            return {'ok':True,**rows,'layouts':layouts,'revision':self.store.revision(p),'backup':backup}
