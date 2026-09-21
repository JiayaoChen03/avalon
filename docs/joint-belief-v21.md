# Joint Belief v2.1: action reliability and vote-only policy experiment

This is a new adapter/policy revision, not a new belief model. The production
Game, legal private knowledge, Agent, v1/v2 inference and world prompt are frozen.
The obsolete full-plan decision protocol is replaced in the evaluation client
by a phase-specific action menu; both A arms share this revised protocol. The
old and new live results are separate experiments, never pooled.

All commands run from the repository root. The preparatory command refuses to
overwrite an existing output directory. Network access requires both `--live`
and a newly authorized matching budget. Historical budget allowances are not
inherited. `50` below is an example ceiling, not an authorization.

```bash
# Audit the exact report named in the task and the later run separately.
.venv/bin/python -m avalon.eval.v2.v21_runner --mode audit --run-dir results/joint_belief_v2_1/audit-next
.venv/bin/python -m avalon.eval.v2.v21_runner --mode fixtures --run-dir results/joint_belief_v2_1/audit-next

# Freeze code, configuration, 80 source games, source splits and snapshot list.
# Omit --budget-cny for a strictly offline run.
.venv/bin/python -m avalon.eval.v2.v21_runner --mode prepare --run-dir results/joint_belief_v2_1/live-next --budget-cny 50

# Deterministic gates; neither command calls a real API.
.venv/bin/python -m avalon.eval.v2.v21_runner --mode unit --run-dir results/joint_belief_v2_1/live-next
.venv/bin/python -m avalon.eval.v2.v21_runner --mode regression --run-dir results/joint_belief_v2_1/live-next
.venv/bin/python -m avalon.eval.v2.v21_runner --mode fixtures --run-dir results/joint_belief_v2_1/live-next
.venv/bin/python -m avalon.eval.v2.v21_runner --mode offline --run-dir results/joint_belief_v2_1/live-next

# Six predefined A smoke pairs. These spend the explicitly supplied budget.
.venv/bin/python -m avalon.eval.v2.v21_runner --mode smoke --run-dir results/joint_belief_v2_1/live-next --live --budget-cny 50 --workers 8

# Resume same run: reuse accepted smoke decisions, do not call them again.
# A: 40 single-seat + 4 whole-table pairs and 200 fixed snapshots.
# B: frozen v2, 100 vote snapshots + 8 separate exploratory active pairs.
# Eight representative inputs receive two additional independent HTTP requests.
.venv/bin/python -m avalon.eval.v2.v21_runner --mode main --run-dir results/joint_belief_v2_1/live-next --live --budget-cny 50 --workers 8

# Offline, raw-only recomputation and archive. No API calls.
.venv/bin/python -m avalon.eval.v2.v21_runner --mode report-only --run-dir results/joint_belief_v2_1/live-next
```

`--data-from DIR` can reuse an already frozen source corpus; production core
hashes must match. `--tests-from DIR` reuses gates only if the complete evaluated
source fingerprint is identical. Reuse is recorded explicitly, not counted as
another test sample. Source/config/contract/dataset changes require a new run ID.
`--main` is not an option: the implemented form is `--mode main` as above.

Each request reserves its maximum input/output charge before HTTP dispatch in a
durable record. A crash without a final usage record retains the full reservation
on recovery. Transport retries (two) and schema/action corrections (two) have
independent ceilings. Every HTTP attempt is charged and retained. No scripted
fallback or minimum-risk-team substitution is allowed.

Game checkpoints contain accepted decisions and atomic state transitions. A
restart rebuilds a new in-memory Game from the same initial configuration,
private views and public observations, verifies every context/state hash, and
replays accepted actions locally without another HTTP request. Each surviving
Game applies a commit key only once. Simultaneous sealed ballots/cards are still
collected before one production transition. This is deterministic local state
reconstruction, not a claim of provider-side exactly-once billing.

The candidate changes only the vote DecisionContext. Exact public facts include
rejection count, terminal rejection rule, mission score, next leader and AP.
The future-team calculation assumes uniformly selected legal teams under the
current posterior; it is explicitly an approximation, not an exact win rate.
Joint team probabilities are computed from full hypotheses, never products of
marginals. Role goals remain distinct. Approval frequency is descriptive, not a
correctness score. No probability updates, language factors, recursive ToM or
cross-game memories are added.

The action decoder permits one explicitly audited transport normalization: if a
provider echoes `type: "json_object"` alongside the five response fields, that
metadata is removed before validation and recorded as
`provider json_object metadata`. An incorrect value or any other extra field is
still rejected; this does not repair an action or a citation.

Revision r6 makes correction feedback identify the failing field and its legal
constraints. A parameter-free menu option still requires `{}`; repeating its
fixed ballot inside parameters is rejected. Evidence-kind failures return the
matching public IDs so the model can revise its own choice. All corrections
retain the same two-attempt ceiling, original failure record and usage charge.
Revision r7 adds the actual public event kinds for invalid reason/citation
combinations and removes the redundant copy of the full parameter schema from
feedback. A nomination still does not satisfy a vote-history requirement.

Fixed comparisons cluster by source game; active comparisons pair by scenario.
Repeated requests do not add independent scenarios. Tiny and degenerate samples
are labelled `insufficient_sample` / `degenerate_resampling`, not equivalence.
Every planned arm remains in pair_manifest.jsonl even if never started.
