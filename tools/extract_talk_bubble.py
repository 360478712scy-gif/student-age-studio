"""Prepare talk artwork using the packaged client's extractor."""
import argparse
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'standalone'))
from game_talk_ui import resources, DEFAULT_GAME
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--game',default=str(DEFAULT_GAME));p.add_argument('--out',default=str(ROOT/'standalone/ui-assets/talk'));a=p.parse_args();resources(Path(a.game),Path(a.out))
