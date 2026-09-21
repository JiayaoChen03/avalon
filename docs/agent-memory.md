# Persistent characters and the Chronicle

The Chronicle remembers everything. The Agent remembers what matters.

The existing `Game` event stream remains the sole public history. `Chronicle` owns
it; `Game.events` is a detached compatibility snapshot. Each entry receives a
deterministic `R{round}-{global seq:03d}` ID. The round label does not reset `seq`.
IDs are unique within a match; the journal filename identifies the match. Accepted
actions, votes, outcomes, deaths and rebirths all enter this stream.

Normal terminal and GUI sessions append the journal to
`~/.avalon/chronicles/<match-id>.jsonl`. `Game(..., chronicle_path=path)` allows an
explicit path; plain in-memory games remain useful for integrations/tests. New
games reject nonempty journals. Read an existing archive with `Chronicle(path)`;
this reloads history, not a resumable private game. New matches start new identities
and role assignments; continuity applies across lives in the same match.

## Responsibilities

- `avalon/chronicle.py`: append, detached record lookup, read-only agent capability,
  citation validation, and metadata/keyword retrieval, including Chinese bigrams.
- `avalon/memory.py`: eight-event Working Memory, compact relationships, three recent
  Life Memories, five Memory Scars, five commitments and five unresolved accusations.
  Earlier life summaries consolidate into a count and five evidence landmarks.
- `avalon/cognition.py`: joint role hypotheses constrained by rules, deduplicated typed
  evidence updates and separate expressed public stances; see [cognition](agent-cognition.md).
- `avalon/agents.py`: code-derived marginal beliefs and behavioral profiles,
  bounded context building and optional retrieval. Models cannot overwrite probabilities.
  Managed evil keeps its existing strategy manager, plus individual life memory.
- `avalon/engine.py`: atomic action/AP validation and authoritative death/rebirth events.
- `avalon/gui.py` and the Godot handwriting panel: public projections, citation
  attachments and opening original records. Private memory never enters UI state.

## Lifecycle

1. A public action is validated and recorded. Every agent observes it once.
2. Observations update affected beliefs, relationships, bounded working memory and
   salient commitments. A claim is never automatically a confirmed hidden identity.
3. A failed unsafe expedition kills all its members, regardless of their individual secret
   cards. This makes deaths observable without disclosing the saboteur. Recorded
   nominations and accusations are associations, not proof of a killer.
   Every completed exile ballot makes the next mission round safe: failure still
   counts, but causes no expedition deaths. Council exile can kill on any round.
4. Each deceased agent creates an extractive Death Reflection (at most 850 characters
   of summary plus compact structured references/beliefs). No extra LLM call is needed.
   Working Memory clears; important relationships, promises, suspicions, profiles,
   permitted role knowledge and the strongest scars remain.
5. At the next mission round, the engine emits REBIRTH with an incremented life number.
   It uses the same `Player` and `Agent`, invalidates obsolete decision caches, clears
   transient reaction history and loads the same compact memory for future decisions.
6. Each mission is followed by a council: all seats discuss once, the mission leader
   nominates a living character, and all seats submit APPROVE/REJECT/ABSTAIN. A strict
   majority of all seats is necessary. Pending-death characters retain council rights.
   Public exile nominations and votes update personal relationships and bounded scars;
   a successful exile triggers the same death reflection. The GUI holds the result
   before advancing the round and rebirthing, so death is visible before return.
7. Assassination also records death when the target is still alive. Existing victory conditions still end the match;
   if no next round occurs, the character remains awaiting rebirth. Restarting is a
   separate match, not a way to carry postgame revealed roles into another game.

Scars bias the model through memory, not a forced action or target. Their strengths
decay during consolidation. Successful missions weaken old negative associations;
the model can propose cited soft counterevidence or defend someone it previously suspected.
Successful missions alone never eliminate worlds containing evil members.
COMMIT records and explicit written promises are retained as commitments. Unresolved
accusations remain attributed claims with original record IDs.

## Prompt and output boundaries

Every decision receives current role-authorized state, up to eight recent events,
up to five focused records, bounded Working Memory, the compact beliefs/profiles,
relationships, three life summaries and five scars. Retrieval adds at most five
records. The system prompt is fixed for a client and never grows with game history.
The full archive, diagnostic call history, earlier plans and other agents' private
state are never serialized into a model request.

Before deciding, host retrieval prioritizes the current tactical target (or a salient
personal relationship), current cited records, unresolved accusations, death records
and scar origins. Within those candidates it favors accusation/defense and mission
outcomes over generic events; recency breaks ties. It cannot prove semantic
contradictions automatically. The model interprets retrieved statements.

If exact evidence is missing, the model may first return:

```json
{"memory_query": ["P1 defending P5", "R1-007"]}
```

At most two 120-character queries run in one retrieval stage. Results are interleaved
and deduplicated to five total records. The next request has
`retrieval_complete=true` and must return an action. Repeated query loops are invalid.
This costs one additional model request; it does not spend Resolve or publish anything.
Retry feedback never becomes memory or history.

The existing action plan envelope and AP policy remain. Its new social object is:

```json
{
  "card": "ACCUSE",
  "target": "P1",
  "reason": "observe",
  "public_writing": "死亡没有让我忘记。你的指控仍需依据。",
  "citations": ["R1-007"]
}
```

Public writing is a printable single line of at most 240 characters, normally 1–3
short Chinese sentences. No chain-of-thought or reasoning field is accepted.
PASS/HOLD/CITE/CHALLENGE may set `social=null`; silence need not generate any prose.
Legacy `statement/rationale/evidence` inputs remain validated for compatibility, but
extra rationale is not shown or sent back as prompt history. Legacy integer references
and new Chronicle IDs resolve to the same entries. Basic human card selections are
also preserved. UI human writing uses the new schema.

All citations are validated before AP is spent or the turn advances. Model citations
must also occur in the supplied public evidence, including retrieval results. Missing
records trigger the existing internal retry mechanism. No evidence is fabricated.
The accepted event stores stable citation IDs; UI state attaches their original public
records. Nested citations are references rather than recursive event payloads.

## Persistence and privacy

Chronicle reads return detached values. Agents get a `ChronicleReader` with no write
operations; model output can update interpretation, never archive contents. The
host may append records but there is no replace/delete operation. Public postgame
role reveals remain in the archive for existing log compatibility; agent retrieval,
agent recent-event context and UI evidence exclude them and mission submission
receipts. Individual mission cards are never archived at all.

This prototype does not add embedding infrastructure or reconstruct the full hidden
game state from a saved journal. Search scans public metadata/text and is deliberately
inspectable. Private memories survive deaths during a running match; process restart
resumption is outside this change.

## Verification and demo

```sh
.venv/bin/python -m unittest discover -s tests -p test_memory.py -v
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python tests/build_ui_fixtures.py /tmp/avalon-ui-fixtures.json
godot --headless --path frontend-godot --script tests/render_smoke.gd -- /tmp/avalon-ui-fixtures.json
```

`test_reborn_agent_can_choose_and_publish_accusation_citing_previous_life` runs real
engine actions: P1 accuses P5, P5 records a commitment, the expedition fails, P5 dies
and returns, the old record is retrieved, and a model response citing it is accepted.
Only the external model boundary is substituted; the game does not contain a scripted
revenge policy. Other checks cover invalid citation atomicity, disk reload,
immutable history, knowledge isolation, changing beliefs, strategic silence and
1,000 lives / 4,000 archived events with bounded request size.

In the GUI, choose **编年史** to review old records. An accusation's `[R…]` link opens
the original handwriting; the citation render fixture exercises that click. Normal
play still uses the configured external model, whose choices can include silence,
reconsideration or accusations rather than guaranteed revenge.

A local pressure check measured 6,975 dynamic-context characters at 20 lives / 80
records and 7,178 at 1,000 lives / 4,000 records, with three life summaries and five
retrieved records in both cases. These are serialized character counts, not tokenizer
measurements. A configured-model smoke check also accepted a reborn agent's PASS
after structured-output correction; it does not claim guaranteed revenge behavior
or a complete real-model match.
