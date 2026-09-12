"""Command-line preparation uses the same extractor as packaged clients."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"standalone"))
from game_phone_ui import resources
