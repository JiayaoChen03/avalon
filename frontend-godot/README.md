# Godot 4 Local Playable UI

This directory is the presentation layer for the Python Avalon game.
The current branch is based on the latest `main` Resolve / Action Point engine:
`Game`, `Game.act()`, `Game.legal_actions()`, mission rules, sealed voting,
challenge/reaction windows, team revision, hidden roles, AI agents, and Evil
strategy remain authoritative in Python.

## Requirements

- Godot 4.x
- Python 3.10+
- Python dependencies installed from the repository `requirements.txt`
- A working repository-root `.env` using the same LLM configuration as the terminal version

Godot never reads or stores the LLM API key.

## Run

1. Open `frontend-godot/project.godot` in Godot 4.
2. Press **Run Project**.
3. Godot starts `frontend-godot/backend_launcher.py` automatically; it locates the repository root and launches the localhost backend.
4. Click **START GAME**.

No terminal input is required for gameplay. The bridge binds only to
`127.0.0.1:8765`.

## Implemented MVP flow

- Start game, optional reproducible seed, 5/6 players
- Private Human role reveal and legitimate role knowledge
- Human or AI team proposal
- Public Resolve display sourced directly from `Game.resolve`
- PASS / Social / committed Social / Challenge / Cite / Hold / React
- Challenge response: RESPOND for 1 Resolve or DECLINE for free
- Team lock or one-player paid revision
- Sealed normal / strong voting using `Game.vote(..., strong=...)`
- Good-only SUCCESS restriction and Evil FAIL option
- Aggregate mission outcome; individual mission-card authors are not exposed
- Resolve refresh controlled by the engine after mission resolution, not rejected proposals
- Human Assassin target selection or automatic AI assassination
- Public chronological event log
- Error recovery that preserves authoritative state; interrupted AI transitions enter `AI_RETRY` rather than replaying an accepted Human action
- Game result and Play Again

## Architecture

```text
Godot 4 / GDScript
        |
        | localhost JSON HTTP
        v
avalon.ui_server
        |
        v
avalon.ui_resilient_session
        |
        v
avalon.ui_session        (orchestration / state projection only)
        |
        +-- Game / Game.act / Game.legal_actions   <-- rules + Resolve source of truth
        +-- Agent                                  <-- AI decisions
        +-- EvilStrategyManager                    <-- shared Evil strategy
        +-- ChatClient                             <-- LLM transport
```

The Godot client renders backend state and sends explicit commands. It does not
calculate Resolve costs, decide legal engine actions, resolve votes/missions, or
store private AI state.

## Tests

- `tests/test_ui_session.py` uses a deterministic fake provider and covers role privacy, free PASS, authoritative Resolve, mission refresh behavior, and a complete match driven only by UI commands.
- `tests/test_ui_resilient_session.py` covers the interrupted-AI recovery path so an already accepted Human action is not replayed.

Runtime validation still requires opening the project in a local Godot 4 editor;
the repository connector used to create this branch cannot execute the Godot editor itself.
