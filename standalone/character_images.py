"""Import native companion images without saving or overwriting character drafts."""
from pathlib import PurePosixPath
import io
import secrets
import re
from PIL import Image

SUFFIXES={'head':'_head','half':'_half','comic':'_comic'}

def companion_path(base,kind):
    suffix=SUFFIXES[kind]
    p=PurePosixPath(base.replace('\\','/'))
    return str(p.with_name(p.stem+suffix+p.suffix))

def import_companion(store,payload,api):
    with store.lock:
        project=store.project(payload.get('projectId'),writable=True)
        revision=store.revision(project)
        if revision!=payload.get('revision'):raise api.ApiError('模组已变化，请重新选择图片。',409,'conflict')
        kind=payload.get('kind');base=payload.get('base');source=payload.get('source')
        if kind not in SUFFIXES or not isinstance(base,str) or not isinstance(source,str):raise api.ApiError('人物图片类型无效。')
        def png(resource):
            path=store.asset(project.id,resource)
            if path.stat().st_size>api.MAX_IMAGE:raise api.ApiError('图片超过大小限制。',413)
            with Image.open(path) as im:
                if im.width*im.height>40_000_000:raise api.ApiError('图片像素过大。',413)
                im.load();out=io.BytesIO();im.convert('RGBA').save(out,format='PNG');return out.getvalue()
        # A new bundle is immutable, so cancelling/undoing the draft leaves old portraits intact.
        base_path='Textures/Characters/person_'+secrets.token_hex(8)+'.png'
        changes={base_path:png(base)}
        for name,suffix in SUFFIXES.items():
            if name==kind:continue
            candidate=companion_path(base,name) if base.replace('\\','/').startswith('Mods/') else 'role_'+name+'/'+base.removeprefix('role_full/')
            try:changes[companion_path(base_path,name)]=png(candidate)
            except (api.ApiError,OSError,ValueError):pass
        # Preserve native photo-face companions when repointing the character bundle.
        original=store.asset(project.id,base)
        if base.replace('\\','/').startswith('Mods/'):
            for old in original.parent.iterdir():
                match=re.fullmatch(re.escape(original.stem)+r'(_face[0-9]+)'+re.escape(original.suffix),old.name)
                if match and old.is_file():
                    candidate=str(PurePosixPath(base.replace('\\','/')).with_name(old.name))
                    changes[str(PurePosixPath(base_path).with_name(PurePosixPath(base_path).stem+match[1]+'.png'))]=png(candidate)
        changes[companion_path(base_path,kind)]=png(source)
        store.commit(project,changes,revision)
        url='Mods\\'+project.package+'\\'+base_path.replace('/','\\')
        return {'ok':True,'revision':store.revision(project),'url':url,'image':companion_path(url,kind)}
