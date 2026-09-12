import Foundation
import Metal
import MetalKit
import AppKit
struct Drawable: Decodable {let id:String;let flags:Int;let visible:Bool;let texture:Int;let order:Int;let opacity:Float;let masks:[Int];let vertices:[[Float]];let indices:[UInt16];let multiply:[Float];let screen:[Float]}
struct Scene:Decodable {let textures:[String];let drawables:[Drawable];let bounds:[Float];let width:Int;let height:Int}
let source="""
#include <metal_stdlib>
using namespace metal;
struct Out {float4 pos [[position]];float2 uv;float2 maskUV;};
vertex Out vs(uint i [[vertex_id]],const device float4 *v [[buffer(0)]],constant float4 &b [[buffer(1)]]) {
 Out o;float2 p=(v[i].xy-b.xy)/b.zw; o.pos=float4(p*2-1,0,1);o.uv=float2(v[i].z,1-v[i].w);o.maskUV=float2(p.x,1-p.y);return o;
}
fragment float4 fs(Out in [[stage_in]],texture2d<float> image [[texture(0)]],texture2d<float> mask [[texture(1)]],constant float4 *settings [[buffer(0)]]) {
 constexpr sampler s(filter::linear,address::clamp_to_edge);float4 color=image.sample(s,in.uv);color.rgb*=settings[1].rgb;color.rgb=color.rgb+settings[2].rgb-color.rgb*settings[2].rgb;
 float a=color.a*settings[0].x;if(settings[0].y>0){float m=mask.sample(s,in.maskUV).a;if(settings[0].z>0)m=1-m;a*=m;}return float4(color.rgb*a,a);
}
"""
do {
 let scene=try JSONDecoder().decode(Scene.self,from:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1])))
 guard let device=MTLCreateSystemDefaultDevice(),let queue=device.makeCommandQueue() else{throw NSError(domain:"Metal",code:1)}
 let lib=try device.makeLibrary(source:source,options:nil)
 var pipelines:[MTLRenderPipelineState]=[]
 for mode in 0...2 {
  let p=MTLRenderPipelineDescriptor();p.vertexFunction=lib.makeFunction(name:"vs");p.fragmentFunction=lib.makeFunction(name:"fs")
  let a=p.colorAttachments[0]!;a.pixelFormat = .rgba8Unorm;a.isBlendingEnabled=true;a.sourceRGBBlendFactor=mode==2 ? .destinationColor:.one;a.destinationRGBBlendFactor=mode==1 ? .one:.oneMinusSourceAlpha;a.sourceAlphaBlendFactor = .one;a.destinationAlphaBlendFactor = .oneMinusSourceAlpha
  pipelines.append(try device.makeRenderPipelineState(descriptor:p))
 }
 let loader=MTKTextureLoader(device:device)
 let textures=try scene.textures.map{try loader.newTexture(URL:URL(fileURLWithPath:$0),options:[.SRGB:false,.origin:MTKTextureLoader.Origin.topLeft])}
 func target()->MTLTexture {let d=MTLTextureDescriptor.texture2DDescriptor(pixelFormat:.rgba8Unorm,width:scene.width,height:scene.height,mipmapped:false);d.usage=[.renderTarget,.shaderRead];d.storageMode = .shared;return device.makeTexture(descriptor:d)!}
 let output=target(),white=target()
 // Original models can contain empty meshes. Keep their indices for mask references,
 // but do not pass an empty Swift array to Metal's non-null bytes argument.
 let vertexBuffers=scene.drawables.map{row->MTLBuffer? in let data=row.vertices.flatMap{$0};return data.isEmpty ? nil:device.makeBuffer(bytes:data,length:data.count*4)}
 let indexBuffers=scene.drawables.map{row->MTLBuffer? in row.indices.isEmpty ? nil:device.makeBuffer(bytes:row.indices,length:row.indices.count*2)}
 let command=queue.makeCommandBuffer()!
 func encoder(_ texture:MTLTexture,_ clear:Bool)->MTLRenderCommandEncoder {let pass=MTLRenderPassDescriptor();pass.colorAttachments[0].texture=texture;pass.colorAttachments[0].loadAction=clear ? .clear:.load;pass.colorAttachments[0].storeAction = .store;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,0);return command.makeRenderCommandEncoder(descriptor:pass)!}
 func draw(_ index:Int,_ enc:MTLRenderCommandEncoder,_ mask:MTLTexture?,_ isMask:Bool=false) {
  guard scene.drawables.indices.contains(index),let vertices=vertexBuffers[index],let indices=indexBuffers[index] else{return}
  let row=scene.drawables[index];if row.texture<0||row.texture>=textures.count{return}
  enc.setRenderPipelineState(pipelines[isMask ? 0:row.flags&1 != 0 ? 1:row.flags&2 != 0 ? 2:0]);enc.setCullMode(.none)
  enc.setVertexBuffer(vertices,offset:0,index:0);var bounds=scene.bounds;enc.setVertexBytes(&bounds,length:16,index:1)
  var settings:[Float]=[isMask ? 1:row.opacity,mask == nil ? 0:1,row.flags&8 != 0 ? 1:0,0]+row.multiply+row.screen
  enc.setFragmentBytes(&settings,length:settings.count*4,index:0);enc.setFragmentTexture(textures[row.texture],index:0);enc.setFragmentTexture(mask ?? white,index:1)
  enc.drawIndexedPrimitives(type:.triangle,indexCount:row.indices.count,indexType:.uint16,indexBuffer:indices,indexBufferOffset:0)
 }
 var masks:[String:MTLTexture]=[:]
 for row in scene.drawables where !row.masks.isEmpty && row.visible && row.opacity>0 {
  let key=row.masks.map(String.init).joined(separator:",");if masks[key] != nil {continue}
  let tex=target(),enc=encoder(tex,true);for i in row.masks {draw(i,enc,nil,true)};enc.endEncoding();masks[key]=tex
 }
 let enc=encoder(output,true)
 for i in scene.drawables.indices.sorted(by:{scene.drawables[$0].order<scene.drawables[$1].order}) {let row=scene.drawables[i];if row.visible&&row.opacity>0 {draw(i,enc,masks[row.masks.map(String.init).joined(separator:",")])}}
 enc.endEncoding();command.commit();command.waitUntilCompleted();if let error=command.error {throw error}
 var pixels=[UInt8](repeating:0,count:scene.width*scene.height*4);output.getBytes(&pixels,bytesPerRow:scene.width*4,from:MTLRegionMake2D(0,0,scene.width,scene.height),mipmapLevel:0)
 let provider=CGDataProvider(data:Data(pixels) as CFData)!
 let image=CGImage(width:scene.width,height:scene.height,bitsPerComponent:8,bitsPerPixel:32,bytesPerRow:scene.width*4,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGBitmapInfo(rawValue:CGImageAlphaInfo.premultipliedLast.rawValue),provider:provider,decode:nil,shouldInterpolate:true,intent:.defaultIntent)!
 let png=NSBitmapImageRep(cgImage:image).representation(using:.png,properties:[:])!;try png.write(to:URL(fileURLWithPath:CommandLine.arguments[2]),options:.atomic)
}catch{fputs("\(error)\n",stderr);exit(1)}
