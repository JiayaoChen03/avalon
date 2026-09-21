# Local joint-belief evaluation

Run from the repository root. Install the local evaluation dependencies once:

```sh
python -m pip install -e '.[eval]'
```

The complete offline evaluation is one command:

```sh
python -m avalon.eval.joint_belief \
  --games 500 \
  --variants baseline,joint_belief \
  --seed 1000 \
  --output-dir results/joint_belief
```

If using this repository's virtual environment, substitute `.venv/bin/python`
for `python`. No API key, `.env` configuration, network service or live model is
used. `--model controlled-v1 --temperature 0` is the default. Results are written
to a new timestamped directory. Existing runs are never overwritten.

The command runs these gates in order:

1. Deterministic pytest correctness and harness tests, with `unit_tests.xml` and
   `unit_tests.log`. A failure stops all evaluation phases.
2. Generate 20 completed games with a static-knowledge reference controller, save
   them, then replay each observer's public observations through both variants.
   Neither evaluated variant influences these games. Equal-stream and duplicate
   delivery checks must pass before the tournament.
3. Run 20 paired smoke trials. Any invalid action, incomplete game or belief
   exception blocks the larger tournament.
4. Run the requested larger tournament. `--games 500` means **500 pairs / 1,000
   physical tournament games**, in addition to the smoke and reference games.

Passing a gate means the machinery is sound enough to proceed. It does not mean
the new belief architecture is effective.

`--workers 4` parallelizes independent seed pairs locally. Default `--workers 1`
reduces timing noise. `--players 6` exercises the other supported role-count and
quest-size configuration. Use `--replay-games`, `--smoke-games` and
`--bootstrap-resamples` to change sample sizes. `--mode replay` runs correctness
and passive replay only. All options appear under `--help`.

## What changes between paired games

Only P1's belief architecture changes. Its role is randomly assigned by the
existing seeded `make_players`; each pair has identical role assignments, game
seed, initial leader, direction, rules, cards, Resolve resources, model,
temperature and opponents. All opponents have the frozen baseline beliefs and
the same controlled decision policy. All actions go through the existing `Game`
methods, including council, death/rebirth and assassination.

The common `complete(context)` mock policy minimizes the probability of a dirty
team, uses a fixed vote-risk threshold, and ranks assassination targets by its
own Merlin marginal. The baseline estimates team risk using independence; joint
belief queries the exact event in its native posterior. The mock receives no
variant label, truth table, sealed ballots, other agents' knowledge or post-game
reveal. Random draws use seed plus semantic decision coordinates, not a mutable
call-count-dependent stream. Pair order is counterbalanced for latency.

This deliberately measures the effect of belief architecture under a fixed local
policy, rather than comparing two different model policies. Production Agent,
Game, prompts and evil-strategy behavior are untouched. The local runner does
not activate the shared evil strategy manager or language interpretations.
Those production integration paths are covered by correctness tests, not by a
claim about live-model tournament strength.

## Baseline provenance and joint scores

`avalon.eval.beliefs.BaselineBeliefs` preserves the deterministic numerical belief
logic in `avalon/agents.py` at Git commit `74fd078`: independent Evil/Merlin
estimates, social-card deltas, vote clues, quest deltas and private-fact clamps.
Model-authored replacement belief maps are disabled for both variants in local
mode. The numerical golden-sequence test protects this port. Git has no committed
version of the intervening alignment-world prototype.

The baseline has no native joint posterior. For **scoring only**, its independent
estimates are lifted onto legal role assignments: an unknown seat's Assassin and
ordinary Evil masses are each half its Evil estimate, Merlin mass is its Merlin
estimate, and ordinary Good mass is the remainder. Multiply seat masses, restrict
to public role counts and initial authorized private knowledge, then normalize.
No quest constraints are added to this projection. It never changes the native
marginals, team-risk estimates or policy decisions. The joint variant uses the
unmodified production `avalon.cognition.BeliefEngine`.

This distinction is recorded in `joint_representation`. Projected baseline joint
metrics are diagnostics, not evidence that the old agent represented correlated
role assignments internally. A product distribution with no legal support is
reported as a collapse and missing joint scores; it is never reset to uniform.

## Completed-game replay input

To reuse an exact frozen corpus, including a prior run's corpus:

```sh
python -m avalon.eval.joint_belief --mode replay \
  --replay-file results/joint_belief/RUN_ID/replays.jsonl \
  --seed 1000 --output-dir results/joint_belief
```

Each JSONL line is one envelope:

```json
{
  "schema_version": 1,
  "game_id": "a-unique-completed-game-id",
  "seed": 42,
  "direction": "clockwise",
  "players": [
    {"id": "P1", "name": "One", "role": "GOOD"},
    {"id": "P2", "name": "Two", "role": "MERLIN"},
    {"id": "P3", "name": "Three", "role": "ASSASSIN"},
    {"id": "P4", "name": "Four", "role": "EVIL"},
    {"id": "P5", "name": "Five", "role": "GOOD"}
  ],
  "events": []
}
```

Replace `events` with the completed game's original `game.events` records, from
START through terminal RESULT/REVEAL, including the original contiguous sequence
numbers. Empty, incomplete, contradictory-role or reordered logs are rejected.
Saved private views are never trusted: the host rebuilds each initial legal view
using Game, then sends detached public projections to each observer. The host's
truth map is used only by the scorer. Each public event is delivered twice in
replay to audit deduplication; only the first delivery is timed/scored.

`--model fixture-v1 --responses path.json` uses controlled action responses from a
JSON object keyed by `P1:round:attempt:phase`, with a phase-only fallback key. Each
value is the same response object consumed by the local runner (e.g.
`"vote": {"approve": true, "strong": false}`). Missing or invalid responses fail
the game, are counted, and block phase promotion. Both variants use the same
fixture. Arbitrary external model names are rejected; live-provider tournaments
are not implemented or silently enabled.

`--likelihood-config path.json` accepts the production `LikelihoodConfig` fields
`language`, `behavioral` and `confidence`, with all their required named values.
The resolved values are saved. Do not tune on the reported evaluation seeds.

## Metrics and uncertainty

- `games.csv` has one row per physical reference, smoke or tournament game.
  Aggregate tournament results exclude reference/smoke rows. Overall win rate is
  P1's win rate; Good/Evil and per-role rates condition on P1's assigned role.
  Table faction win rates are separate. Failure rows are retained.
- `belief_trace.csv` records the initial posterior and a common superset of every
  numerical belief update, with observer, role, round, proposal, event ID,
  variant, phase, change indicator and per-player Evil/Merlin probabilities.
  Replay records every observer; gameplay records the evaluated P1. Checkpoints
  where an architecture makes no update still appear for aligned comparisons.
- Brier and binary log loss average over **other seats**, avoiding self-role
  certainty. Unknown-target metrics use the initially unknown alignments.
  Replay includes separate ordinary-GOOD observer comparisons to expose effects
  otherwise diluted by Merlin/Evil private knowledge.
- Joint log loss is distinct from binary log loss. True-world ranks use midranks
  for ties, and initial legal-world-count + 1 for an eliminated truth. Entropy is
  in nats. A `1e-15` floor applies to logs only; probabilities retain exact zeros.
- Final scores and round curves stop before ASSASSINATE/RESULT evidence. Trace
  rows after those boundaries have `decision_available=0`. Role reveals and
  sealed mission submissions never enter belief engines.
- Slot-weighted proposed-team composition includes revisions and rejected teams.
  Evil inclusion in Good-led teams is Evil slots / all slots in those teams;
  dirty-team rate separately counts teams containing at least one Evil.
- Merlin assassination rate is hits / all games. Assassin identification accuracy
  is hits / actual opportunities; its denominator can change with treatment.
  Undefined denominators produce missing values, not fabricated zeros.
- Paired percentile bootstrap resamples whole seed pairs for gameplay and whole
  frozen games for replay. Seats and updates stay inside the game cluster. The
  same sampled indices are used for both treatments. For rates, both numerators
  and denominators are resampled. Missing scalar scores use a common pair subset.
- `summary.json` includes absolute/relative deltas, 95% intervals, denominators,
  eligible cluster counts and the number of valid bootstrap replicates. With only
  one eligible cluster, inferential intervals are unavailable. Intervals are
  exploratory, unadjusted for multiple comparisons. Read the uncertainty rather
  than declaring victory from a larger raw mean.
- Diagnostics flag entropy falling with truth probability, confidently wrong
  worlds/marginals, distribution collapse, near-zero truth mass, duplicate
  evidence, private-data isolation failures and major belief-latency increases.
  Real model token/cost data are unavailable in this local mode; mock calls and
  context bytes are measured without pretending they are provider tokens.

## Outputs

Every run directory contains `config.json`, `unit_tests.xml`, `games.csv`,
`belief_trace.csv`, `summary.json`, `report.md` and six PNG plots in `plots/`.
It also contains the frozen `replays.jsonl`, replay audit records, test log,
resolved likelihood/response files and `source/` snapshots. The config records
timestamp, Git commit and dirty status, Python/package versions, seed lists,
role/rule controls, source SHA-256 hashes and a reproduction command. Archiving
source matters because the new belief system may be uncommitted.

Effectiveness requires agreement across calibration, true-world scores, team
composition and relevant role/game outcomes. Lower entropy, passing tests, or a
larger win-rate mean alone is insufficient. Treat these results as controlled
local evidence and retain the explicit live-model limitation.
