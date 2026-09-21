"""Explicit GUI-test entrypoint: replace only the external model response.

Invoked as AVALON_PYTHON by tests/gui_test_python.sh. The first argument is the
normal bootstrap path that Godot supplies; the remaining arguments are unchanged.
There is no test-mode switch or fallback in the production backend or UI.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from avalon.gui import GameSession
from avalon import gui_server
from test_gui import UIModelClient

gui_server.GameSession = lambda: GameSession(UIModelClient)
gui_server.main(sys.argv[2:])
