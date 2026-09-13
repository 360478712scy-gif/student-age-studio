"""Portable off-screen Cubism mesh rasterizer. Used by the Windows background worker."""
from pathlib import Path
import numpy as np
from PIL import Image

_STRIP_H = 256


class Raster:
    def __init__(self, textures, bounds, width, height):
        # Lazy per-texture decode: identical float32 pixels as eager load,
        # but models using a subset never pay for the rest. Cache keeps
        # byte-identical arrays for repeated faces.
        self._texture_paths = list(textures)
        self._textures = {}
        self.bounds = np.asarray(bounds, dtype=np.float32)
        self.width, self.height = width, height

    @property
    def textures(self):
        # Back-compat accessor: materializes all (same values as before).
        for index in range(len(self._texture_paths)):
            self._texture(index)
        return [self._textures[index] for index in range(len(self._texture_paths))]

    def _texture(self, index):
        cached = self._textures.get(index)
        if cached is None:
            with Image.open(self._texture_paths[index]) as image:
                cached = np.asarray(image.convert('RGBA'), dtype=np.float32) / 255
            self._textures[index] = cached
        return cached

    def mesh(self, row):
        if not row['indices'] or not 0 <= row['texture'] < len(self._texture_paths): return None
        vertices = np.asarray(row['vertices'], dtype=np.float32)
        xy = (vertices[:, :2] - self.bounds[:2]) / self.bounds[2:]
        xy[:, 0] *= self.width
        xy[:, 1] = (1 - xy[:, 1]) * self.height
        left, top = np.maximum(np.floor(xy.min(axis=0)), 0).astype(int)
        right, bottom = np.minimum(np.ceil(xy.max(axis=0)), [self.width, self.height]).astype(int)
        if right <= left or bottom <= top: return None
        pixels = np.zeros((bottom-top, right-left, 4), dtype=np.float32)
        texture = self._texture(row['texture'])
        th, tw = texture.shape[:2]
        for tri in np.asarray(row['indices']).reshape(-1, 3):
            a, b, c = xy[tri]
            lo = np.maximum(np.floor(np.minimum(np.minimum(a, b), c)), [left, top]).astype(int)
            hi = np.minimum(np.ceil(np.maximum(np.maximum(a, b), c)), [right, bottom]).astype(int)
            if np.any(hi <= lo): continue
            den = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1])
            if abs(den) < 1e-8: continue
            # Same per-pixel math as before, evaluated in horizontal strips so
            # a large triangle never materializes full-bbox float grids at once.
            # Windows (CPU raster, no Metal GPU) OOMs/thrashes without this;
            # decoded pixels are bit-identical, only peak RAM changes.
            uvs = vertices[tri, 2:]
            xs = np.arange(lo[0], hi[0], dtype=np.float32) + .5
            for y0 in range(lo[1], hi[1], _STRIP_H):
                y1 = min(hi[1], y0 + _STRIP_H)
                xx, yy = np.meshgrid(xs, np.arange(y0, y1, dtype=np.float32) + .5)
                w0 = ((b[1]-c[1])*(xx-c[0]) + (c[0]-b[0])*(yy-c[1])) / den
                w1 = ((c[1]-a[1])*(xx-c[0]) + (a[0]-c[0])*(yy-c[1])) / den
                w2 = 1-w0-w1
                inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
                if not inside.any(): continue
                uv = w0[inside,None]*uvs[0] + w1[inside,None]*uvs[1] + w2[inside,None]*uvs[2]
                u = np.clip(uv[:,0]*tw-.5, 0, tw-1)
                v = np.clip((1-uv[:,1])*th-.5, 0, th-1)
                x, y = u.astype(int), v.astype(int)
                x1, y1b = np.minimum(x+1, tw-1), np.minimum(y+1, th-1)
                fx, fy = (u-x)[:,None], (v-y)[:,None]
                color = (texture[y,x]*(1-fx)+texture[y,x1]*fx)*(1-fy) + (texture[y1b,x]*(1-fx)+texture[y1b,x1]*fx)*fy
                pixels[y0-top:y1-top, lo[0]-left:hi[0]-left][inside] = color
        return (left, top, right, bottom), pixels

    def render(self, rows, target):
        output = np.zeros((self.height, self.width, 4), dtype=np.float32)
        meshes, masks = {}, {}
        def mesh(index):
            if index not in meshes: meshes[index] = self.mesh(rows[index])
            return meshes[index]
        for row in rows:
            key = tuple(row['masks'])
            if not key or key in masks or not row['visible'] or row['opacity'] <= 0: continue
            mask = np.zeros((self.height, self.width), dtype=np.float32)
            for index in key:
                data = mesh(index)
                if data is None: continue
                (x0,y0,x1,y1), pixels = data
                a = pixels[:,:,3]
                region = mask[y0:y1,x0:x1]
                region[:] = a + region*(1-a)
            masks[key] = mask
        for index in sorted(range(len(rows)), key=lambda i:rows[i]['order']):
            row = rows[index]
            if not row['visible'] or row['opacity'] <= 0: continue
            data = mesh(index)
            if data is None: continue
            (x0,y0,x1,y1), pixels = data
            alpha = pixels[:,:,3:4] * row['opacity']
            key = tuple(row['masks'])
            if key:
                mask = masks[key][y0:y1,x0:x1,None]
                alpha = alpha * (1-mask if row['flags'] & 8 else mask)
            rgb = pixels[:,:,:3] * np.asarray(row['multiply'][:3], dtype=np.float32)
            screen = np.asarray(row['screen'][:3], dtype=np.float32)
            rgb = (rgb + screen - rgb*screen) * alpha
            destination = output[y0:y1,x0:x1]
            if row['flags'] & 1: destination[:,:,:3] += rgb
            elif row['flags'] & 2: destination[:,:,:3] *= rgb + (1-alpha)
            else: destination[:,:,:3] = rgb + destination[:,:,:3]*(1-alpha)
            destination[:,:,3:4] = alpha + destination[:,:,3:4]*(1-alpha)
            # Match the native renderer's normalized render target between draws.
            np.clip(destination, 0, 1, out=destination)
            if not any(index in key for key in masks): meshes.pop(index, None)
        alpha = output[:,:,3:4]
        np.divide(output[:,:,:3], alpha, out=output[:,:,:3], where=alpha>0)
        Image.fromarray(np.rint(np.clip(output,0,1)*255).astype(np.uint8)).save(Path(target), format='PNG')
