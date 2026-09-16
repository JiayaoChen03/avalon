"""Godot-local launcher that imports the repository Python package safely."""

from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from avalon.ui_server import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
