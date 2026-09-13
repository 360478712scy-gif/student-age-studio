"""Extract Unity's original Live2D models and evaluate their expression animations without starting the game."""
from storage_paths import game_cache, auxiliary_cache
import gc
import json
import hashlib
import os
import subprocess
import sys
import shutil
import zlib
from pathlib import Path
from extract_game_assets import UnityPy,bundle_members,connect_dependencies
from native_core import Model

class Reader:
 _MAX_ENVS=2
 def __init__(self,game):
  self.game=Path(game);self.home=game_cache(self.game);self.cache=self.home/'native-models-v1';self.cache.mkdir(parents=True,exist_ok=True)
  self.bundles=sorted([p for folder in (self.game/'StudentAge_Data/StreamingAssets',self.game/'DLC') for p in folder.rglob('*.bundle')]);self.environments={};self.scripts={};self.config={};self._member_index=None
 def _members(self):
  # Reuse bundle headers when an environment is loaded or reloaded.
  if self._member_index is None:
   members={}
   for p in self.bundles:
    if 'l2d' in p.name:
     try:
      for name in bundle_members(p):members[name]=p
     except (ValueError,OSError):pass
   self._member_index=members
  return self._member_index
 def configs(self):
  if self.config:return self.config
  for path in sorted((p for p in self.bundles if 'cfgs' in p.name),key=lambda p:('dlc' in str(p).lower(),str(p))):
   env=UnityPy.load(str(path))
   for name,obj in env.container.items():
    key=Path(name).stem.lower()
    if key not in ('personcfg','personfacecfg') or not ('zh-cn/' in name.lower()) or obj.type.name!='TextAsset':continue
    data=json.loads(obj.read().m_Script,strict=False)
    if isinstance(data,list):data={str(r['id']):r for r in data}
    self.config.setdefault(key,{}).update(data)
  return self.config
 def environment(self,path):
  if path in self.environments:
   self.environments[path]=self.environments.pop(path)
   return self.environments[path]
  env=UnityPy.load(str(path))
  connect_dependencies(env,self._members());self.environments[path]=env
  while len(self.environments)>self._MAX_ENVS:
   self.environments.pop(next(iter(self.environments)))
   # Script keys contain object identities; evicted environments can release
   # those identities for reuse by a later bundle.
   self.scripts.clear();gc.collect()
  return self.environments[path]
 def model_asset(self,name):
  for path in sorted((p for p in self.bundles if 'l2dmodels' in p.name),key=lambda p:('dlc' not in str(p).lower(),str(p))):
   env=self.environment(path)
   for resource,obj in env.container.items():
    if resource.lower().endswith(('/'+name+'_dlc.prefab','/'+name+'.prefab')):return path,obj
  raise ValueError('找不到原版人物模型：'+name)
 def extract(self,name):
  path,root=self.model_asset(name);key=name+'-'+str(path.stat().st_mtime_ns);folder=self.cache/key;meta=folder/'model.json'
  if meta.exists():
   cached=json.loads(meta.read_text(encoding='utf-8'))
   # Cache folders can be copied to a new editor installation. File names are
   # stable; absolute paths in the old metadata are not.
   cached['moc']=str(folder/'model.moc3')
   cached['textures']=[str(folder/('texture-'+str(i)+'.png')) for i in range(len(cached['textures']))]
   if Path(cached['moc']).is_file() and all(Path(p).is_file() for p in cached['textures']):return cached
  folder.mkdir(parents=True,exist_ok=True);components=[];params={};textures={};controller=None;moc=None
  def script(ptr):
   key=(id(ptr.assetsfile),ptr.path_id)
   if key not in self.scripts:self.scripts[key]=ptr.read().m_ClassName
   return self.scripts[key]
  def visit(go,prefix=''):
   nonlocal controller,moc
   go=go.read() if hasattr(go,'read') else go;transform=None
   for component in go.m_Component:
    obj=component.component.deref()
    if obj.type.name=='Transform':transform=obj.read()
    elif obj.type.name=='Animator':controller=obj.read().m_Controller
    elif obj.type.name=='MonoBehaviour':
     cls=script(obj.read().m_Script);t=obj.read_typetree()
     if cls=='CubismModel':moc=obj.read()._moc
     if cls=='CubismParameter':params[zlib.crc32(prefix.encode())]=go.m_Name
     if cls=='CubismRenderer':textures[go.m_Name]=obj.read()._mainTexture
   if transform:
    for child in transform.m_Children:
     item=child.read().m_GameObject;childname=item.read().m_Name;visit(item,prefix+'/'+childname if prefix else childname)
  visit(root)
  if not moc:raise ValueError('人物缺少 MOC3 数据')
  mocpath=folder/'model.moc3';mocpath.write_bytes(bytes(moc.deref().read_typetree()['_bytes']))
  native=Model(mocpath.read_bytes(),self.game);rows=native.evaluate({});texture_paths={}
  for row in rows:
   ptr=textures.get(row['id'])
   if ptr and row['texture'] not in texture_paths:
    file=folder/('texture-'+str(row['texture'])+'.png');ptr.read().image.save(file);texture_paths[row['texture']]=str(file)
  layers={}
  if controller:
   ctrl=controller.deref().read_typetree();clip_ptrs=controller.read().m_AnimationClips;tos=dict(ctrl['m_TOS'])
   for layer in ctrl['m_Controller']['m_LayerArray']:
    layer=layer['data'];lname=tos.get(layer['m_Binding'],'');machine=ctrl['m_Controller']['m_StateMachineArray'][layer['m_StateMachineIndex']]['data'];state=machine['m_StateConstantArray'][machine.get('m_DefaultState',0)]['data']
    trees=state.get('m_BlendTreeConstantArray',[])
    if not trees:continue
    nodes=[v['data'] for v in trees[0]['data']['m_NodeArray']];first=nodes[0];choices=list(zip(first['m_Blend1dData']['data']['m_ChildThresholdArray'],first['m_ChildIndices'])) if first['m_ChildIndices'] else [(0,0)]
    variants={}
    for weight,node_idx in choices:
     clipid=nodes[node_idx]['m_ClipID']
     if clipid>=len(clip_ptrs):continue
     clip=clip_ptrs[clipid].deref().read_typetree();data=clip['m_MuscleClip']['m_Clip']['data'];stream=data['m_StreamedClip']['curveCount'];dense=data['m_DenseClip'];constants=data.get('m_ConstantClip',{}).get('data',[]);bindings=clip['m_ClipBindingConstant']['genericBindings'];values={}
     # Expression/cloth blend targets are constant curves. Dense first-frame curves cover idle defaults.
     for i,binding in enumerate(bindings):
      param=params.get(binding['path'])
      if not param:continue
      if stream<=i<stream+dense['m_CurveCount']:value=dense['m_SampleArray'][i-stream]
      elif i>=stream+dense['m_CurveCount'] and i-stream-dense['m_CurveCount']<len(constants):value=constants[i-stream-dense['m_CurveCount']]
      else:continue
      values[param]=value
     variants[str(int(weight))]=values
    layers[lname]=variants
  result=dict(moc=str(mocpath),textures=[texture_paths[i] for i in range(max(texture_paths)+1)],layers=layers,source=str(path),name=name)
  meta.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');return result
 def render(self,role,grade,cloth,selected=0,progress=None,gender=1):
  cfg=self.configs();person=cfg['personcfg'].get(str(role));models=person.get('l2d2' if grade else 'l2d',[]) if person else []
  if not models:raise ValueError('此人物使用静态立绘')
  from portraits import portrait_key
  cache_name=portrait_key(role,grade,cloth,gender)
  name=models[1 if len(models)>1 and (gender if role==0 else person.get('gender'))==2 else 0];asset=self.extract(name);native=Model(Path(asset['moc']).read_bytes(),self.game);layers=asset['layers'];faces={}
  for face,row in cfg.get('personfacecfg',{}).items():
   mapped=row.get(name,-1)
   if int(face)<100 and mapped>=0:faces[int(face)]=mapped
  faces.setdefault(0,-1)
  def parameters(face):
   result={};base=layers.get('Base Layer',{});result.update(base.get('0',{}))
   for layer,weight in [('Cloth',cloth),('Hair',0),('Item',0),('Expression',faces.get(face,-1))]:
    variants=layers.get(layer,{})
    if variants:
     key=min(variants,key=lambda k:abs(int(k)-weight));result.update(variants[key])
   return result
  base=native.evaluate(parameters(0));points=[v for r in base if r['visible'] and r['opacity']>.01 for v in r['vertices']]
  if not points:raise ValueError('模型没有可显示的图层')
  x0=min(v[0] for v in points);y0=min(v[1] for v in points);width=max(v[0] for v in points)-x0;height=max(v[1] for v in points)-y0
  # One frame per model/cloth for every expression; retain a small margin for facial motion.
  width*=1.04;height*=1.04;x0-=width*.02;y0-=height*.02
  out=self.home/'portrait-cache';out.mkdir(exist_ok=True);width_px=max(160,min(1024,round(1000*width/height)))
  raster=None
  rendered={}
  available=[]
  status_root=self.home/'native-portrait-status';status_root.mkdir(exist_ok=True)
  status_path=status_root/f'{cache_name}.json'
  source='Windows Raster + Cubism Core' if sys.platform=='win32' else 'macOS Metal + Cubism Core'
  inputs=[p for p in self.bundles if 'l2d' in p.name or 'cfgs' in p.name]
  stamps=[[str(p.relative_to(self.game)),p.stat().st_size,p.stat().st_mtime_ns] for p in inputs]
  signature=hashlib.sha256(json.dumps([1,stamps,layers,faces,role,grade,cloth,gender,width_px,[x0,y0,width,height]],sort_keys=True).encode()).hexdigest()
  metadata=dict(frame={'bounds':[x0,y0,width,height],'model':name},faces=sorted(faces),sameAsDefault=[f for f,v in faces.items() if f and v==faces.get(0)],model=name,source=source,renderSignature=signature,complete=False)
  def status():
   temp=status_path.with_suffix('.tmp');temp.write_text(json.dumps(dict(metadata,available=available)),encoding='utf-8');os.replace(temp,status_path)
  try:previous=json.loads(status_path.read_text(encoding='utf-8'))
  except (OSError,ValueError):previous={}
  compatible=previous.get('model')==name and previous.get('source')==source and previous.get('frame')==metadata['frame']
  # Legacy records have no input signature. Reuse only matching frames with
  # pictures newer than the source bundles; then upgrade their metadata.
  legacy=not previous.get('renderSignature')
  compatible=compatible and (legacy or previous.get('renderSignature')==signature)
  newest=max((stamp[2] for stamp in stamps),default=0)
  for face in previous.get('available',[]) if compatible else []:
   target=out/f'{cache_name}-{face}.png'
   if face in faces and target.is_file() and (not legacy or target.stat().st_mtime_ns>=newest):
    available.append(face);rendered[json.dumps(parameters(face),sort_keys=True)]=target
  available=sorted(set(available))
  if set(available)==set(faces):
   metadata['complete']=True;status();return available
  if sys.platform=='win32':
   from portrait_raster import Raster
   raster=Raster(asset['textures'],[x0,y0,width,height],width_px,1000)
  status()
  for face in sorted(faces,key=lambda f:(f!=0,f!=selected,f)):
   if face in available:continue
   target=out/f'{cache_name}-{face}.png';tmp=out/(target.stem+'.native.json');png=out/(target.stem+'.native.png')
   try:
    signature=json.dumps(parameters(face),sort_keys=True)
    if signature in rendered:shutil.copyfile(rendered[signature],png)
    else:
     drawables=native.evaluate(parameters(face))
     if raster:raster.render(drawables,png)
     else:
      scene=dict(textures=asset['textures'],drawables=drawables,bounds=[x0,y0,width,height],width=width_px,height=1000)
      tmp.write_text(json.dumps(scene),encoding='utf-8')
      subprocess.run([str(Path(__file__).parent/'native/PortraitMetal'),str(tmp),str(png)],check=True,capture_output=True,timeout=30)
    os.replace(png,target)
    rendered[signature]=target
   finally:tmp.unlink(missing_ok=True);png.unlink(missing_ok=True)
   available.append(face)
   status()
   if progress:progress(available,list(faces))
  metadata["complete"]=True;status()
  return available

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--game',required=True);p.add_argument('--role',type=int,default=3);p.add_argument('--grade',type=int,default=1);p.add_argument('--cloth',type=int,default=0);p.add_argument('--face',type=int,default=0);p.add_argument('--gender',type=int,choices=(1,2),default=1);a=p.parse_args()
 from platform_support import lock_file,unlock_file
 home=game_cache(Path(a.game));home.mkdir(exist_ok=True)
 with (home/'native-portraits.lock').open('a+b') as lock:
  lock_file(lock)
  try:print(Reader(a.game).render(a.role,a.grade,a.cloth,a.face,progress=lambda done,all:print(len(done),'/',len(all),flush=True),gender=a.gender))
  finally:unlock_file(lock)
