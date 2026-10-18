"""The tests' path bootstrap: corvus-v2 on sys.path so the corvus package resolves."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
