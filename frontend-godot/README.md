# Avalon local Godot UI

Open `project.godot` in **Godot 4** and use **Run Project** (F5). The local project
metadata and validation use **Godot 4.8.dev6**. On this Mac,
you can also double-click **Play Avalon.app** in the repository root. The launcher
finds `Godot.app` in Applications or your Applications/Downloads folder.
Keep the launcher beside the source checkout; this is not a standalone export.

The game launches its Python backend automatically. No terminal input is used
during play. Choose 5 or 6 players, optionally enter an integer seed, then click
**开始游戏**. The interface is in Simplified Chinese; Resolve is displayed as **决心**.
You are always P1. Use **我的身份** to revisit your private knowledge.
Click player seats to draft a team or choose an assassination target. All other
choices appear in the bottom panel. Scroll that panel in a smaller window if needed.

The central **圆桌手稿** reader sits between two compact columns of player seats.
It opens on **手稿**, showing short accepted handwritten statements. Filter by character,
search text or record IDs, and use **回到最新** to clear filters and follow new records.
Both tabs preserve a deliberate reading position when new replies arrive; readers at
the end keep following. These controls remain usable during AI calls. **编年史**
preserves public actions with stable record IDs. Click a citation, a record ID, or a
response's **回应** link to open the original record, even from a past life or outside
the current filter. Human social actions can include a
short written sentence and an optional citation. Player seats display the current
life number. Failed expedition members return in the next mission round.

Model text is rendered literally, including inside evidence previews. No reasoning,
private beliefs, role information, or tactical state is exposed. Silence creates an
action record without a fabricated handwritten statement. Search, filters and tab
choice survive refreshes and menu navigation, and reset at the start of a new match.

## Requirements

- Godot 4 (tested with the installed 4.8.dev6 build); desktop OpenGL compatibility
  renderer, no art or export templates required.
- Python 3.10+ and this repository's Python dependencies. The included `.venv`
  is preferred automatically. Otherwise the launcher uses `python3` (`python`
  on Windows); `AVALON_PYTHON` can specify an executable path.
- The existing `.env` model configuration, as documented in the root README.
  A real model service is required. Missing configuration appears in the UI.
  AI failures pause at the same decision and offer **重试 AI 行动**; the
  application never substitutes fabricated actions or an offline bot.

Only the UI has a new presentation layer; `Game`, `Agent`, and
`EvilStrategyManager` retain control of rules and decisions. This source workflow
has been exercised on macOS; a packaged Windows/Linux application is not included.

## Structure and transport

- `scenes/main.tscn`, `scripts/main.gd`: one phase-driven table and compact forms.
- `scripts/player_seat.gd`: reusable player seat with public Resolve and status.
- `scripts/text_zh.gd`: Chinese display names for the original engine enums.
- `scripts/dialogue_panel.gd`: public dialogue and event-history tabs.
- `scripts/backend_client.gd`: process lifecycle and asynchronous HTTP requests.
- `backend_bootstrap.py`: finds the Python package independently of working directory.
- `avalon/gui.py`: resumable presentation gates and human commands around the engine.
- `avalon/gui_server.py`: one serial session on a random loopback port.

The backend writes a per-launch handshake file with a random bearer token to
Godot's user-data folder (owner-only permissions). No API key leaves Python.
Every command carries a state revision and request ID; retries cannot double-spend
Resolve. A lost response can be retried, and errors return the current state.
The Godot window owns the child process and stops it on exit; the backend also
watches its parent. There are no remote listeners, accounts, resumed games, or multiplayer features.
Normal play appends a durable public Chronicle to `~/.avalon/chronicles/`; private
agent state currently persists through lives within the running match.

Human ballots and mission cards stay in private Python storage until resolution.
All team ballots publish together. Missions publish aggregate counts only.
UI snapshots are built from the Human's role-limited view plus an explicit public
event projection. An explicit allowlist exposes accepted `public_writing` (with the legacy `statement`
alias), stable IDs, and citation records to the handwriting panel. Rationale text,
private plans, beliefs, strategy, and the engine's postgame role dump remain excluded.
Localization changes display labels only; all command IDs and card enums are unchanged.

`ROLE_REVEAL`, `VOTE_RESULT`, `ROUND_RESULT`, and `EXILE_RESULT` pause presentation.
Every mission result leads to **任务后议会**, one normal discussion turn per seat,
then **出局提名** by the mission leader and sealed **赞成 / 反对 / 弃票** ballots.
Exile requires a strict majority of all seats; abstentions do not lower the threshold.
All seats retain council rights, including characters awaiting rebirth; only living
characters can be nominated. Resolve is shared with the preceding team discussion.
The exile result shows death before **下一轮 · 安全任务** advances, rebirths, and
refreshes Resolve. Rejected team proposals do not refresh it. The first round is
dangerous; every completed exile vote makes the next mission round safe, whether
or not somebody was exiled. Safe failures still score but do not kill team members.
Council exile still applies. The decisive mission also has a council before the
existing victory/assassination resolution, which remains independent of exile.

## Validation

From the repository root, `python -m unittest discover -s tests` runs the original
engine/AI suite plus `test_gui.py`. The UI boundary tests exercise complete 5- and
6-player matches, all roles, costs, windows, evidence filtering, revision, sealed
ballots, anonymous missions, assassination, stale/duplicate commands, HTTP access,
and failure recovery. Only the external model boundary is replaced in tests.

For a headless Godot rendering check, generate fixtures from the repository root
with `python tests/build_ui_fixtures.py /tmp/avalon-ui-fixtures.json`, then run
`godot --headless --path frontend-godot --script tests/render_smoke.gd -- /tmp/avalon-ui-fixtures.json`
(replace `godot` with your installed executable). This checks phase/form controls,
disabled actions, mission permissions, confirmations, literal dialogue rendering,
tab persistence, translated command payloads, and the 1280 × 720 layout.
It starts no model calls and provides no test/fake-AI option in the playable UI.

For an explicit interactive regression run on macOS/Linux, set `AVALON_PYTHON`
to the absolute path of `tests/gui_test_python.sh` and launch Godot with
`--path frontend-godot --script tests/playable_fixture.gd`. The window is labeled
**测试模型**. This test-only entrypoint runs the same Game, Agents, Evil strategy,
HTTP adapter, and UI, substituting only the external model responses. The ordinary
launcher does not select this entrypoint or modify your `.env` configuration.

Manual smoke checklist: start → private role → draft → discussion → vote → mission
→ result → council discussion → nomination → three-way exile ballot → exile result
→ next safe round and rebirth → assassination (when reached) → winner → Play Again.
Also try HOLD/react, a committed Social action, Challenge/Cite selectors, revision,
a strong ballot, the zero-Resolve controls, and resizing the window.

Verified locally on macOS with Godot 4.8.dev6: the Python regression suite and 36 Godot render
cases passed. An entire mouse-driven match with the explicit test model (seed 157)
reached three successful missions, Human assassination, EVIL WINS, and Play Again
with scores/Resolve reset. Window resizing and the macOS launcher were also checked.
The Chinese interface was checked in a graphical test-model session, including
role reveal, team selection, multiple AI statements, reaction evidence previews,
and switching between dialogue and public history.
The configured real model was exercised through multiple rounds, Social/Commit,
Challenge, Cite, Hold/React, revision, voting, and mission submission. It sometimes returned
repeated invalid plans; those attempts paused without a fabricated move, and retry
was exercised. A complete match against that external service is not claimed.

The memory refactor adds a citation fixture that clicks a real record link and checks
the original literal handwriting. The Python memory tests cover death/reflection/rebirth,
old evidence, role isolation, changing beliefs, and 1,000 lives / 4,000 archived events.

The council update adds safety, nomination, sealed three-way ballots and exile results
to the phase fixtures, including each translated vote button's exact command and
selection-based nomination. Rule tests cover 5/6-seat majority thresholds, abstention,
safe failures, exile/rebirth memory and the decisive mission's council. A configured
real-model short check accepted council discussion, nomination and both good/evil
ballot schemas in five requests (including retrieval/correction). This is a protocol
smoke check, not a full real-model match.
