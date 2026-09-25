import re,colorsys,sys
src=''.join(open(f).read() for f in ['glass-palette.css','glass-theme.css','frosted-glass.css'])
fb={}
for m in re.finditer(r'var\(--glass-tone-(\d+),\s*([^()]+?(?:\([^)]*\))?)\s*\)',src):
    n=int(m.group(1));fb.setdefault(n,m.group(2).strip())
def parse(c):
    c=c.strip()
    if c.startswith('#'):
        h=c[1:]
        if len(h) in (3,4):h=''.join(x*2 for x in h)
        r,g,b=(int(h[i:i+2],16) for i in (0,2,4));a=int(h[6:8],16)/255 if len(h)==8 else 1
        return r,g,b,a
    m=re.match(r'rgba?\(\s*([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)(?:[,/ ]+([\d.]+))?',c)
    if m:return float(m[1]),float(m[2]),float(m[3]),float(m[4]) if m[4] else 1
    if c=='transparent':return 0,0,0,0
    if c in('#fff','white'):return 255,255,255,1
    return None
# Paper & celadon palette. Neutrals take a warm hue; saturated blues become a deep celadon teal.
ACCENT_H=172/360
def remap(r,g,b,a):
    h,l,s=colorsys.rgb_to_hls(r/255,g/255,b/255)
    chroma=(max(r,g,b)-min(r,g,b))/255
    if chroma>0.04 and (h<0.06 or h>0.93):   # reds (danger, its washes) keep their hue
        return r,g,b,a
    if chroma>0.07 and s>0.45 and 0.47<h<0.75:  # blue accents and washes -> celadon
        if l>0.82:   nl,ns=l,0.42             # pale selection wash
        elif l>0.6:  nl,ns=l*0.92,0.40        # mid tints / focus lines
        else:        nl,ns=min(l,0.46)*0.60+0.03,0.60  # accent ink: >=4.5:1 on paper
        return (*[round(x*255) for x in colorsys.hls_to_rgb(ACCENT_H,nl,ns)],a)
    if chroma>0.25:                          # other saturated colours (greens, golds) unchanged
        return r,g,b,a
    if l>0.9:   nl,ns=0.925+(l-0.9)*0.55,0.36  # paper
    elif l>0.55: nl,ns=l,0.12                  # warm greys
    else:       nl,ns=l*0.95,0.10              # ink
    return (*[round(x*255) for x in colorsys.hls_to_rgb(40/360,nl,ns)],a)
out=[]
for n in sorted(fb):
    p=parse(fb[n])
    if p is None: print('skip',n,fb[n],file=sys.stderr);continue
    R,G,B,A=remap(*p)
    out.append(f'--glass-tone-{n}:rgba({R},{G},{B},{A:.3f})')
print('/* 纸本 · 工作室: warm paper, ink text, celadon accent. Generated from the light glass fallbacks by atelier_tones.py. */')
print('html[data-theme="glass-atelier"]{color-scheme:light;'+';'.join(out)+';}')
print(len(out),'tones',file=sys.stderr)
