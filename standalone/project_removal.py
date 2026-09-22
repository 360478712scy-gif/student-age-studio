"""Explicit two-click removal with a recoverable folder.

Subscribed workshop mods are only hidden from this editor's list. Their Steam files stay.
"""
import os
import secrets
import shutil
import time


def _release_open_files(store, project):
    segments=getattr(store,'talk_segments',None)
    if not segments:return
    root=str(project.path.resolve())
    for token,generation in list(getattr(segments,'generations',{}).items()):
        if str(generation.identity.get('path',''))==root:
            segments.generations.pop(token,None)
            try:generation.close()
            except Exception:pass


def _hide_subscribed(store, project):
    prefs=store.project_preferences
    saved,ignored=prefs.prepare({'ignoredProjectIds':[*prefs.ignored,project.id],'defaultProjectId':prefs.saved.get('defaultProjectId','') if prefs.saved.get('defaultProjectId')!=project.id else ''})
    prefs.apply(saved,ignored)
    return {'ok':True,'hidden':True,'name':project.name,'projects':[p.public() for p in store.projects()]}


def remove(store,payload,api):
    with store.lock:
        project=store.project(payload.get('projectId'),writable=False)
        if project.original_mode:raise api.ApiError('原版资源编辑模组不能在这里删除。')
        pending=getattr(store,'_pending_removals',{})
        now=time.monotonic();pending={k:v for k,v in pending.items() if v[2]>now};store._pending_removals=pending
        token=payload.get('confirmation')
        if not token:
            token=secrets.token_urlsafe(24);pending[token]=(project.id,store.revision(project),now+120,project.readonly)
            return {'confirmation':token,'name':project.name,'expiresIn':120,'subscribed':project.readonly}
        entry=pending.pop(token,None)
        if not entry or entry[0]!=project.id:raise api.ApiError('删除确认已失效，请重新点击删除。',409)
        if entry[1]!=store.revision(project):raise api.ApiError('模组已被修改，请重新确认删除。',409,'conflict')
        if project.readonly or entry[3]:return _hide_subscribed(store, project)
        destination=store.mods.parent/'StudentAgeStudioRemovedMods'/(project.path.name+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4))
        destination.parent.mkdir(parents=True,exist_ok=True)
        source=project.path.resolve()
        if source.is_symlink() or not api.inside(destination,destination.parent) or api.inside(destination,source):raise api.ApiError('模组目录无效。')
        _release_open_files(store, project)
        try:
            os.rename(source, destination)
        except OSError:
            try:shutil.move(str(source),str(destination))
            except OSError as error:raise api.ApiError('这个模组正在被占用，暂时移不走。请先关闭正在使用它的游戏或窗口后再删除。',409) from error
        if source.exists():raise api.ApiError('模组文件夹仍在原处，没有从列表移除。',409)
        store.extra_mods=[p for p in store.extra_mods if p.resolve()!=source]
        store._project_paths.pop(project.id,None)
        store._project_metadata.pop(str(source),None)
        store._project_metadata.pop(str(project.path),None)
        return {'ok':True,'recoveryPath':str(destination),'projects':[p.public() for p in store.projects()]}
