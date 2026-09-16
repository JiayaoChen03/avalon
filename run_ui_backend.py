"""Launch the localhost UI backend from the repository root.

This file exists so Godot can start Python without relying on the terminal or an
installed console entry point.
"""

from avalon.ui_server import main


if __name__ == "__main__":
    raise SystemExit(main())
