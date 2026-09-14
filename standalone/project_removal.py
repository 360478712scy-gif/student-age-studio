"""Explicit two-click removal with a recoverable folder, never delete subscribed content."""
import secrets
import shutil
import time


def remove(store,payload,api):
    with store.lock:
        project=store.project(payload.get('projectId'),writable=True)
        if project.original_mode:raise api.ApiError('原版资源编辑模组不能在这里删除。')
        pending=getattr(store,'_pending_removals',{})
        now=time.monotonic();pending={k:v for k,v in pending.items() if v[2]>now};store._pending_removals=pending
        token=payload.get('confirmation')
        if not token:
            token=secrets.token_urlsafe(24);pending[token]=(project.id,store.revision(project),now+120)
            return {'confirmation':token,'name':project.name,'expiresIn':120}
        entry=pending.pop(token,None)
        if not entry or entry[0]!=project.id:raise api.ApiError('删除确认已失效，请重新点击删除。',409)
        if entry[1]!=store.revision(project):raise api.ApiError('模组已被修改，请重新确认删除。',409,'conflict')
        destination=store.mods.parent/'StudentAgeStudioRemovedMods'/(project.path.name+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4))
        destination.parent.mkdir(parents=True,exist_ok=True)
        if project.path.is_symlink() or not api.inside(destination,destination.parent) or api.inside(destination,project.path):raise api.ApiError('模组目录无效。')
        shutil.move(str(project.path),str(destination))
        store._project_paths.pop(project.id,None)
        return {'ok':True,'recoveryPath':str(destination),'projects':[p.public() for p in store.projects()]}
