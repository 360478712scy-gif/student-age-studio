"""Idempotent repair of old Studio playback directives when opening a local Mod."""
import copy
import native_audio

def repair(store,project_id):
    with store.lock,store.catalog_scope():
        project=store.project(project_id)
        if project.readonly or project.original_mode:return False
        doc=store.load(project_id)
        if any(k in doc.get('unreadableTables',{}) for k in ('talks','events','options')):return False
        talks=copy.deepcopy(doc['talks']);local=set(map(str,doc['localIds'].get('talks',[]))) & talks.keys()
        cues=copy.deepcopy(doc.get('audioCues') or {'bgm':[],'sfx':{}})
        if cues.get('bgm'):
            native_audio.export(cues,doc['audioCues'],talks,doc['talks'],store.table(project_id,'AudioCfg')['rows'],doc['events'],doc['options'])
        changed=any(talks[k]!=doc['talks'][k] for k in local)
        if not changed:return False
        store.save({'projectId':project_id,'revision':doc['revision'],'talks':talks,'audioCues':cues})
        return True
