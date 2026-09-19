"""Idempotent repair of old Studio playback directives when opening a local Mod."""
import copy
import native_audio

def repair(store,project_id):
    with store.lock,store.catalog_scope():
        project=store.project(project_id)
        if project.readonly or project.original_mode:return False
        # No managed music means there is nothing this migration can change.
        # Do not materialize the complete dialogue table before a warm segment open.
        cues=store.audio_cues(project,{})
        if not cues.get('bgm'):return False
        revision=store.revision(project)
        cache=getattr(store,'_playback_repair_revisions',None)
        if cache is None:cache=store._playback_repair_revisions={}
        key=str(project.path)
        if cache.get(key)==revision:return False
        doc=store.load(project_id)
        if any(k in doc.get('unreadableTables',{}) for k in ('talks','events','options')):return False
        talks=copy.deepcopy(doc['talks']);local=set(map(str,doc['localIds'].get('talks',[]))) & talks.keys()
        cues=copy.deepcopy(doc.get('audioCues') or {'bgm':[],'sfx':{}})
        if cues.get('bgm'):
            native_audio.export(cues,doc['audioCues'],talks,doc['talks'],store.table(project_id,'AudioCfg')['rows'],doc['events'],doc['options'])
        changed=any(talks[k]!=doc['talks'][k] for k in local)
        if not changed:
            if store.revision(project)==doc['revision']:cache[key]=doc['revision']
            while len(cache)>32:cache.pop(next(iter(cache)))
            return False
        store.save({'projectId':project_id,'revision':doc['revision'],'talks':talks,'audioCues':cues})
        return True
