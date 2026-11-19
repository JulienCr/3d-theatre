import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "blender" / "theatre_stage"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
