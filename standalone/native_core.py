"""Cubism Core bridge: evaluate actual MOC3 geometry, with no game process."""
import ctypes as c
import sys
from pathlib import Path
class V2(c.Structure): _fields_=[('x',c.c_float),('y',c.c_float)]
class V4(c.Structure): _fields_=[('x',c.c_float),('y',c.c_float),('z',c.c_float),('w',c.c_float)]
P=c.POINTER
class Model:
 def __init__(self,moc,game=None):
  library=Path(game)/'StudentAge_Data/Plugins/x86_64/Live2DCubismCore.dll' if sys.platform=='win32' and game else Path(__file__).parent/'native/libLive2DCubismCore.dylib'
  self.lib=c.CDLL(str(library))
  def fn(name,result,args=[c.c_void_p]):
   f=getattr(self.lib,'csm'+name);f.restype=result;f.argtypes=args;setattr(self,name,f);return f
  fn('ReviveMocInPlace',c.c_void_p,[c.c_void_p,c.c_uint]);fn('GetSizeofModel',c.c_uint);fn('InitializeModelInPlace',c.c_void_p,[c.c_void_p,c.c_void_p,c.c_uint]);fn('UpdateModel',None)
  raw=bytes(moc);self.mocbuf=c.create_string_buffer(len(raw)+64);ptr=(c.addressof(self.mocbuf)+63)&~63;c.memmove(ptr,raw,len(raw));self.moc=self.ReviveMocInPlace(ptr,len(raw))
  if not self.moc:raise ValueError('人物模型格式不受支持')
  size=self.GetSizeofModel(self.moc);self.modelbuf=c.create_string_buffer(size+16);ptr=(c.addressof(self.modelbuf)+15)&~15;self.model=self.InitializeModelInPlace(self.moc,ptr,size)
  if not self.model:raise ValueError('无法初始化人物模型')
  fn('GetParameterCount',c.c_int);fn('GetParameterIds',P(c.c_char_p));fn('GetParameterValues',P(c.c_float));fn('GetParameterDefaultValues',P(c.c_float))
  self.names=[self.GetParameterIds(self.model)[i].decode() for i in range(self.GetParameterCount(self.model))];self.defaults=list(self.GetParameterDefaultValues(self.model)[:len(self.names)])
  fn('GetPartCount',c.c_int);fn('GetPartIds',P(c.c_char_p));fn('GetPartOpacities',P(c.c_float))
  fn('GetDrawableCount',c.c_int)
  for name,typ in [('Ids',c.c_char_p),('ConstantFlags',c.c_ubyte),('DynamicFlags',c.c_ubyte),('TextureIndices',c.c_int),('RenderOrders',c.c_int),('Opacities',c.c_float),('MaskCounts',c.c_int),('Masks',P(c.c_int)),('VertexCounts',c.c_int),('VertexPositions',P(V2)),('VertexUvs',P(V2)),('IndexCounts',c.c_int),('Indices',P(c.c_ushort)),('MultiplyColors',V4),('ScreenColors',V4)]:fn('GetDrawable'+name,P(typ))
 def evaluate(self,parameters):
  values=self.GetParameterValues(self.model)
  for i,name in enumerate(self.names):values[i]=parameters.get(name,self.defaults[i])
  self.UpdateModel(self.model);n=self.GetDrawableCount(self.model)
  arrays={name:getattr(self,'GetDrawable'+name)(self.model) for name in ['Ids','ConstantFlags','DynamicFlags','TextureIndices','RenderOrders','Opacities','MaskCounts','Masks','VertexCounts','VertexPositions','VertexUvs','IndexCounts','Indices','MultiplyColors','ScreenColors']}
  rows=[]
  for i in range(n):
   nv=arrays['VertexCounts'][i];verts=arrays['VertexPositions'][i];uv=arrays['VertexUvs'][i];mul=arrays['MultiplyColors'][i];scr=arrays['ScreenColors'][i]
   rows.append(dict(id=arrays['Ids'][i].decode(),flags=arrays['ConstantFlags'][i],visible=bool(arrays['DynamicFlags'][i]&1),texture=arrays['TextureIndices'][i],order=arrays['RenderOrders'][i],opacity=arrays['Opacities'][i],masks=list(arrays['Masks'][i][:arrays['MaskCounts'][i]]),vertices=[[verts[j].x,verts[j].y,uv[j].x,uv[j].y] for j in range(nv)],indices=list(arrays['Indices'][i][:arrays['IndexCounts'][i]]),multiply=[mul.x,mul.y,mul.z,mul.w],screen=[scr.x,scr.y,scr.z,scr.w]))
  return rows
