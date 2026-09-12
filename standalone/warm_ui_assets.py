"""Build every supported original UI/guide cache off the HTTP process.

Failure policy (shared with the other cache passes): an item gets MAX_TRIES attempts in a
row, then the rest is built; the items still failing get RETRY_TRIES more at the end and are
then reported in `failed` so the caller can give them up. Items listed in --skip were given
up earlier and are not attempted at all."""
import argparse,json,time
from pathlib import Path
from storage_paths import game_cache
MAX_TRIES=5
RETRY_TRIES=1


def warm(game,skip=()):
    from preview_ui import resources as preview
    from space_assets import resources as space
    from social_media import emoji_atlas
    from paper_ui import base_papers
    from character_rules import native_rules
    from minigame_assets import image_file
    jobs=[('剧情界面',lambda:preview(game)),('人物空间',lambda:space(game)),('动态表情',lambda:emoji_atlas(game)),('纸条',lambda:base_papers(game)),('礼物',lambda:base_papers(game,'GiftEvtCfg'))]
    from ui_resources import resource_manifest
    jobs.extend(('编辑器界面 '+kind,lambda kind=kind:resource_manifest(kind,game)) for kind in ('phone','goal','talk','cg'))
    rules=native_rules(game)
    paths={r['url'] for r in rules.get('GuideCfg',{}).values() if r.get('url')}
    paths.update('puzzle/'+r['url'] for r in rules.get('PuzzleMinigameCfg',{}).values() if r.get('url'))
    jobs.extend((resource,lambda resource=resource:image_file(game,resource)) for resource in sorted(paths))
    jobs=[(name,fn) for name,fn in jobs if name not in set(skip)]
    def attempt(fn,tries):
        message=''
        for n in range(tries):
            try:fn();return True,''
            except Exception as e:
                message=str(e) or '缓存失败'
                if n+1<tries:time.sleep(min(5,n+1))
        return False,message
    def report(done,total,failed,retrying=False):
        print(json.dumps({'phase':'重试未缓存的界面配图' if retrying else '缓存原版界面与小游戏配图','done':done,'total':total,'retrying':retrying,
                          'warnings':[name+'：'+message for name,message in failed][-12:],'failed':[[name,message] for name,message in failed]},ensure_ascii=False),flush=True)
    deferred=[]
    for i,(name,fn) in enumerate(jobs):
        ok,message=attempt(fn,MAX_TRIES)
        if not ok:deferred.append((name,fn,message))
        report(i+1,len(jobs),[(n,m) for n,_,m in deferred])
    failed=[]
    for i,(name,fn,message) in enumerate(deferred):
        ok,message=attempt(fn,RETRY_TRIES)
        if not ok:failed.append((name,message))
        report(i+1,len(deferred),failed,True)
    report(len(jobs),len(jobs),failed,bool(deferred))
    return failed

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--game',required=True);p.add_argument('--skip',default='[]');args=p.parse_args()
    warm(Path(args.game),json.loads(args.skip))
