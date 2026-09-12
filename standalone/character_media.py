"""Expand character catalog entries into selectable clothing / expression images."""
from storage_paths import game_cache, auxiliary_cache
import json
from pathlib import Path
import re

NAMES=['默认','高兴','生气','伤心','害羞','喜欢','认真','疑惑','惊讶','得意','微笑','坏笑','担心','害怕','难过','咆哮','窘迫','不满','冷笑','无语','苦笑']
def category(text):
    value=str(text).lower()
    if re.search(r'夏|summer|xiaji|xiafu',value):return '夏季校服' if re.search(r'校|school|xiaofu',value) else '日常服'
    if re.search(r'冬|winter|dongji|dongfu',value):return '冬季校服' if re.search(r'校|school|xiaofu',value) else '日常服'
    if re.search(r'日常|便服|casual|richang|bianfu',value):return '日常服'
    return '其他'
def expand(catalog,items,mode,person=''):
    out=[]
    face_map=catalog.store.catalog_rows('PersonFaceCfg')
    if not face_map and mode=='expression':
        if not hasattr(catalog,'_character_faces'):
            from native_portraits import Reader
            catalog._character_faces=Reader(catalog.store.game).configs().get('personfacecfg',{})
        face_map=catalog._character_faces
    for item in items:
        if person and str(item.get('sourceId'))!=str(person):continue
        row=item.get('_row',{});variants={}
        for v in item.get('_variants',[]):
            if mode=='portrait' and v['face']!=0:continue
            variants[(v['grade'],v['cloth'],v['face'])]=v
        if item.get('_nativeRole') is not None:
            for grade,field in [(1,'l2d'),(2,'l2d2')]:
                models=row.get(field) or []
                if not models:continue
                model=models[1 if len(models)>1 and row.get('gender')==2 else 0]
                # Inspect authored layers, ignoring cloth slots that are aliases of another slot.
                files=sorted((game_cache(catalog.store.game) / 'native-models-v1').glob(model+'-*/model.json'))
                layers={}
                if files:
                    try:layers=json.loads(files[-1].read_text()).get('layers',{}).get('Cloth',{})
                    except (OSError,ValueError):pass
                clothes={};seen=set()
                for key,value in layers.items():
                    stamp=json.dumps(value,sort_keys=True)
                    if key.isdigit() and 0<=int(key)<=9 and stamp not in seen:clothes[int(key)]=value;seen.add(stamp)
                if not clothes:clothes={0:{}}
                faces={0:'默认'}
                if mode=='expression':
                    baseline=face_map.get('0',{}).get(model,-1)
                    for key,value in face_map.items():
                        if str(key).isdigit() and 0<int(key)<100 and value.get(model,-1)>=0 and value.get(model)!=baseline:
                            faces[int(key)]=NAMES[int(key)] if int(key)<len(NAMES) else '表情 '+key
                for cloth,params in clothes.items():
                    for face,name in faces.items():
                        key=(grade,cloth,face)
                        if key not in variants or face==0:
                            variants[key]={'grade':grade,'cloth':cloth,'face':face,'faceName':name,'_nativeRole':item['_nativeRole'],'clothingCategory':'日常服' if cloth==0 else '其他'}
        if not variants and item.get('_path'):variants[(1,0,0)]={k:v for k,v in item.items() if k.startswith('_') or k in ('resource',)}|{'grade':1,'cloth':0,'face':0,'faceName':'默认'}
        for (grade,cloth,face),v in variants.items():
            if mode=='portrait' and face:continue
            entry={k:value for k,value in item.items() if k not in ('_path','_root','_fingerprint','_nativeRole','resource')}
            entry.update(v);entry['_variants']=[]
            entry['assetId']=item['assetId']+f':v:{grade}:{cloth}:{face}'
            entry['previewGrade']=grade;entry['previewCloth']=cloth;entry['previewFace']=face
            entry['clothingCategory']=v.get('clothingCategory') or category(str(v.get('resource',''))+' '+str(row.get('note','')))
            entry['expressionName']=v.get('faceName') or (NAMES[face] if face<len(NAMES) else '表情 '+str(face))
            entry['name']=item['name']+' · '+('小学' if grade==1 else '中学')+' · '+(entry['expressionName'] if mode=='expression' else entry['clothingCategory'])
            entry['canImport']=True;entry['available']=bool(v.get('_path'))
            out.append(entry)
    return out
