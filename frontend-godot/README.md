# Godot 4 Local Playable UI

This directory is the presentation layer for the existing Python Avalon backend.
The Python engine remains authoritative for hidden roles, proposals, votes,
mission resolution, assassination, AI agents, public events, and Evil strategy.

## Requirements

- Godot 4.x
- Python 3.10+
- Python dependencies installed from the repository `requirements.txt`
- A working `.env` at repository root using the same LLM configuration as the terminal version

Godot never reads or stores the LLM API key.

## Run

1. Open `frontend-godot/project.godot` in Godot 4.
2. Press **Run Project**.
3. The Godot client starts `../run_ui_backend.py` automatically.
4. Click **START GAME**.

No terminal input is required for gameplay.

The local bridge binds only to `127.0.0.1:8765`.

## Implemented MVP flow

- Start game, optional reproducible seed, 5/6 players
- Private human role reveal
- Human or AI team proposal
- Public Resolve display (3 per mission round)
- PASS / Social / committed Social / Challenge / Cite / Hold / React
- Human team lock or one-player revision
- Sealed normal / strong voting
- Good-only SUCCESS restriction and Evil FAIL option
- Aggregate mission results without revealing card authors
- Resolve refresh after mission resolution, not rejected proposals
- Assassin target selection when the human is Assassin
- AI assassination otherwise
- Public chronological event log
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
avalon.ui_session
        |
        +-- existing Game engine
        +-- existing Agent logic
        +-- existing EvilStrategyManager
        +-- existing LLM transport
```

The UI renders backend-provided state and sends explicit commands. Major game
rules are not implemented in GDScript.

## Tests

`tests/test_ui_session.py` uses a deterministic fake LLM client so the UI state
machine can be exercised without network/API calls. It includes a full-match
path driven only by the same commands exposed to Godot.
