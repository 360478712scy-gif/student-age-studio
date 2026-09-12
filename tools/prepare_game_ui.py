#!/usr/bin/env python3
"""Prepare local-only preview art for a source checkout, without redistributing game assets."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'standalone'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--game',required=True);parser.add_argument('--out',default=str(ROOT/'standalone/ui-assets'));args=parser.parse_args()
    game=Path(args.game).expanduser().resolve();out=Path(args.out).expanduser().resolve()
    if not (game/'StudentAge_Data/StreamingAssets/aa/StandaloneWindows64').is_dir():raise SystemExit('请选择包含 StudentAge_Data 的游戏目录。')
    if out==game or out.is_relative_to(game):raise SystemExit('输出必须位于游戏目录之外。')
    import extract_goal_ui,extract_phone_ui
    for kind,module in [('goal',extract_goal_ui),('phone',extract_phone_ui)]:
        print('读取本机游戏界面：'+kind,flush=True);module.resources(game,cache_dir=out/kind)
    subprocess.run([sys.executable,'-B',str(ROOT/'tools/extract_talk_bubble.py'),'--game',str(game),'--out',str(out/'talk')],check=True)
    # The public code does not ship the game's CG mask; this simple editor-owned
    # gradient gives readable captions and uses fonts extracted above on this machine.
    from PIL import Image
    cg=out/'cg';cg.mkdir(parents=True,exist_ok=True)
    body=out/'phone/body.otf';title=out/'goal/title.ttf'
    shutil.copy2(body,cg/'body.otf');shutil.copy2(title if title.exists() else body,cg/'name.otf')
    mask=Image.new('RGBA',(1,256));mask.putdata([(0,0,0,round(i/255*210)) for i in range(256)]);mask.save(cg/'mask.png')
    manifest={'files':['body.otf','name.otf','mask.png'],'reference':[2560,1440],'source':'Local game fonts with editor-generated gradient','maskHeight':600,'body':{'bottom':100,'height':200,'side':100,'fontSize':50},'name':{'bottom':300,'height':57,'fontSize':40}}
    (cg/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('本机界面素材已准备到 '+str(out)+'；请勿提交这些图片或字体。')


if __name__=='__main__':main()
