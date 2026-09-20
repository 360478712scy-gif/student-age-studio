"""Native InteractCfg dialogue workbench; no synthetic events."""
import save_review
import copy
from event_ownership import interaction_talks

def legacy_rows(doc):
    rows={};events={}
    used=set(doc.get('interactions',{}))
    for key,event in doc.get('events',{}).items():
        social=event.get('studioSocial') or {}
        if social.get('kind') not in ('talk','loveTalk'):continue
        ident=str(social.get('interactionId') or event['id'])
        if not social.get('interactionId'):
            while ident in used:ident=str(int(ident)+1)
        used.add(ident);old=copy.deepcopy(doc.get('interactions',{}).get(ident,{}))
        conditions=[r for r in event.get('condition',[]) if r not in social.get('entryConditions',[])]
        old.update(id=int(ident),npc=event.get('npc',0),name=event.get('title',''),text=social.get('text') or old.get('text',''),map=[event['mapId']] if event.get('mapId') else old.get('map',[]),talkId=(event.get('talkId') or [0])[0],cond=conditions,effect=copy.deepcopy(event.get('effect',[])))
        rows[ident]=old;events[ident]=key
    return rows,events

def load(store,project_id,api):
    with store.lock,store.catalog_scope():
        project=store.project(project_id)
        doc=store.load(project_id)
        table=store.table(project_id,'InteractCfg')
        doc['talks']={**store.table(project_id,'TalkCfg')['rows'],**doc['talks']}
        for ident in doc.get('deletedIds',[]):doc['talks'].pop(str(ident),None)
        legacy,legacy_events=legacy_rows(doc)
        commands=store.workshop_info(project_id)['commands']
        names={'MapCfg','PersonCfg','BgCfg','ModFaceCfg'}
        for templates in commands.values():
            if isinstance(templates,list):names.update(p['range']['table'] for t in templates for p in t.get('parameters',[]) if p.get('range',{}).get('table'))
        refs={name:store.table(project_id,name)['rows'] for name in names}
        return {'doc':doc,'table':table,'legacyRows':legacy,'legacyEvents':legacy_events,'refs':refs,'commands':commands,'revision':store.revision(project)}

def save(store,payload,api):
    with store.lock,store.catalog_scope():
        project=store.project(payload.get('projectId'),writable=True)
        current=store.load(project.id)
        save_review.revision(payload, current['revision'], api.ApiError, '模组已变化，请重新读取闲聊。')
        incoming=api.validate_map(payload.get('rows',{}),'InteractCfg.json')
        talks=api.validate_map(payload.get('talks',{}),'TalkCfg.json')
        # Only submitted changed records are merged. Unedited records/files stay untouched.
        interactions=copy.deepcopy(current['interactions']);all_talks=copy.deepcopy(current['talks'])
        deleted={str(v) for v in payload.get('deleted',[])}
        # Editing a later line can change the chain without changing InteractCfg.
        # Compare ownership before/after across all interactions, including shared chains.
        previous_owned=interaction_talks(interactions,all_talks,current.get('options',{}))
        for key in deleted:interactions.pop(key,None)
        interactions.update(incoming);all_talks.update(talks)
        legacy,legacy_events=legacy_rows(current)
        migrating={event for ident,event in legacy_events.items() if ident in incoming}
        for line in all_talks.values():
            owned=line.get('studioSocialEffects',{})
            for event in migrating:
                for effect in owned.get(event,[]):
                    if effect in line.get('effect',[]):line['effect'].remove(effect)
                owned.pop(event,None)
        for key,chat in interactions.items():
            owned=interaction_talks({key:chat},all_talks,current.get('options',{}))
            if key not in incoming and not owned.intersection(talks):continue
            npc=int(chat.get('npc') or 0)
            for tid in owned:
                old_chat=current['interactions'].get(key,{})
                cast_changed=chat.get('npc')!=old_chat.get('npc') or chat.get('talkId')!=old_chat.get('talkId')
                if tid not in talks and not cast_changed and legacy_events.get(key) not in migrating:continue
                line=copy.deepcopy(all_talks[tid])
                # NewTalkView accepts the authored cast, including phone anchors
                # and narration. Do not coerce it back to the interaction owner.
                if 'roleIds' not in line: line['roleIds']=[0]
                line['roles']=[r for r in (line.get('roles') or []) if isinstance(r,list) and len(r)>1]
                first=tid==str(chat.get('talkId'))
                if first and npc:
                    entered={r[0] for r in line['roles'] if r[1] in (1001,1002,1003)}
                    line['roles']=[r for r in [[0,1002,1,1,0],[npc,1002,1,2,0]] if r[0] not in entered]+line['roles']
                # bg=0 inherits the native clicked location, including its grade-specific variant.
                line.setdefault('bg',0)  # Preserve an explicitly authored scene; 0 uses the clicked location.
                all_talks[tid]=line
        next_owned=interaction_talks(interactions,all_talks,current.get('options',{}))
        # Event-owned shared dialogue remains governed by its event.
        removed=(previous_owned-next_owned-set(current.get('talkOwners',{}))) | (set(talks)-next_owned-set(current['talks']))
        for key in removed:all_talks.pop(key,None)
        request={'projectId':project.id,'revision':payload['revision'],'interactions':interactions}
        if all_talks!=current['talks'] or removed:request.update(talks=all_talks,deletedIds=list(map(int,removed)),replacements={k:[] for k in removed})
        if migrating:request.update(events={k:v for k,v in current['events'].items() if k not in migrating},_idleChatMigration=list(migrating))
        result=store.save(request)
        return {**result,'revision':store.revision(project)}
