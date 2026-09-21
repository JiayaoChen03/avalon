# Joint Belief v2.2: r7 diagnosis and a disabled vote prototype

This is an offline diagnostic and one context candidate, not a new belief model.
The only source run is `results/joint_belief_v2_1/20260918-v21-r7-live-75`.
Every r7 observation, including its originally held-out snapshots, is now
development/diagnostic material. Nothing is borrowed from neighboring runs.

## Actual commands

Run from the repository root. The CLI denies socket connections and disables
`Settings.load` and `ChatClient.complete`. It has no `--live` or budget argument.
Defaults in the output config are `live=false`, `budget_cny=null` and the
candidate feature flag is false. An API key is neither needed nor loaded.

```bash
# A new directory; fails instead of overwriting an existing directory.
.venv/bin/python -m avalon.eval.v2.v22_runner --mode prepare \
  --run-dir results/joint_belief_v2_2/next-r7-offline

# 1. Diagnose r7: all planned pairs, failures/repeats/costs, production
# transactions, original-posterior checks, frozen v1/v2 cross-replay.
.venv/bin/python -m avalon.eval.v2.v22_runner --mode diagnose \
  --source-run results/joint_belief_v2_1/20260918-v21-r7-live-75 \
  --run-dir results/joint_belief_v2_2/next-r7-offline --workers 4

# Unit and full repository regression; overlapping test sets are not additive.
.venv/bin/python -m avalon.eval.v2.v22_runner --mode tests \
  --run-dir results/joint_belief_v2_2/next-r7-offline

# 2. Freeze a fresh controlled validation list, generate 12 games, check
# the candidate on 100 diagnostic and 48 new controlled vote snapshots.
.venv/bin/python -m avalon.eval.v2.v22_runner --mode candidate \
  --run-dir results/joint_belief_v2_2/next-r7-offline

# 3. Recompute summary, diagnostic metrics, tables and report without network.
# This reads exported analysis files; it does not play games or request models.
.venv/bin/python -m avalon.eval.v2.v22_runner --mode report-only \
  --run-dir results/joint_belief_v2_2/next-r7-offline
```

The delivered run is `results/joint_belief_v2_2/20260918-v22-r7-offline`.
Its initial audit and immutable prechange snapshot were made before coding.
The complete user attachment arrived while the first diagnostic pass was
running. That pass was stopped and retained under `iterations/`; the final pass
uses the attachment's stronger original-posterior and provenance checks.
Use a fresh output directory to repeat all diagnostics. `--resume` reuses only
completed offline trajectory audits if their diagnostic source hashes match.
The source run is never a valid output path, including nested directories.

## Versions and reuse

`config.json` maps each alias using belief, policy, context, adapter, runtime,
rules, model configuration and scenario manifest hashes:

- `r7_A_ref`: frozen joint_v1, r7 policy_current, base menu context.
- `r7_A_candidate`: frozen joint_v2, same policy_current and base context.
- `r7_B_candidate`: frozen joint_v2 and the existing vote DecisionContext.
- `v22_candidate`: same joint_v2/policy/adapter, only the vote outcome increment.

The production Game, v1/v2 probabilities, evidence factors, world prompt,
v2.1 contract/Session/budget/retry code and production default policy are intact.
Diagnostics reuse `make_version`, the existing scorer, `Game` transitions,
`Session.game_hash`, legal menus, `pairing` and source-game clustered bootstrap.
They do not call the old report generator on its read-only directory.

## Exact diagnostic boundaries

Active records are reconstructed by their original transaction logs. Each
before/after state, legal input, original full-posterior hash and saved marginal
is checked. r7's 80 controlled source games are reconstructed through the same
Game API from recorded actions. Their saved marginals and all available fixed
snapshot full-posterior hashes are checked; other source decisions did not
archive a full posterior at each step, and that absence is explicit.

Beliefs consume only initial `Game.view(observer)` and chronicle public
projections. Individual mission cards in host transaction logs, sealed ballots
before publication, other private knowledge and terminal reveals do not enter
the belief stream. Scoring stops before the first assassination/result event
and all subsequent events. Every delivered observation is replayed a second
time to check idempotence. Scores and full joint checkpoints/factor increments
are kept separately from candidate inputs.

Input comparison retains public prose. A structured-action comparison removes
only prose and ignores team member order; citations, reason codes, targets,
strong votes and AP consequences remain meaningful. Comparisons after a common
information prefix are explicitly descriptive, not equal-information effects.
The mechanical hash is a documented physical/phase/legal-option projection,
distinct from the full transaction hash (which also includes public history).

Proposal identity includes its actual initial TEAM record and attempt;
revisions, lock, approval, execution and mission outcome remain separate.
`hindsight_pivotal` calculations substitute one legal ballot into revealed
source ballots through `Game.vote`. These host-only labels never enter policy.

Active single-seat wins mean the focal alignment wins; whole-table wins mean
GOOD alignment wins. Fixed clean-team scores mean all members have GOOD
alignment, not that the observer's objective was achieved. Approval is not a
correctness score. Incomplete arms remain in the plan, without loss imputation.
For belief metrics, states are averaged within observer, then same-role seats
within source game; source arms, scopes, stages, completion states and focal vs
all-observer cohorts are separate. Bootstrap clusters are source scenarios,
not seats/time points. Tied first is not unique identification.

## The single candidate

`v22_vote.candidate_menu_context(context, full_worlds, enabled=False)` returns
the existing r7 B candidate input exactly when disabled. Enabling affects only
vote inputs. All legal options and the response contract remain byte-compatible
under canonical serialization. No returned LLM action is repaired or replaced.

The pure aid probes each legal ballot with `Game.vote` on a posterior hypothesis
and the public state. It records exact AP cost, reachable pass/reject phases and
terminal rejection. Strong votes spend AP and do not add vote weight in these
production rules; team votes have no abstention option. Rule configurations
that do not match the production Game are rejected as unsupported.

The horizon is the current ballot plus at most one next-proposal ballot, and
at most one executed mission. It is deliberately a bounded proxy, not tree
search. Uniform legal next teams retain r7's assumption. Sensitivity scenarios
use other-approval probabilities 0.25/0.5/0.75, explicitly independent of roles
and worlds. They are not estimates of the opponents' real behavior. This stated
independence is why the same posterior can consistently weight both branches.
There is no unconditional claimed exact pass probability: its unknown bound is
also exported. Mission outcomes use the frozen q=0.5 model and production
thresholds; an evil member need not sabotage.

Actual terminal utility is alignment victory (0/1). Nonterminal leaf utility is
the named score proxy `0.5 + (good - evil)/(2 * number_of_missions)`, complemented
for evil observers. Entering assassination has interval [0,1]. Council/social
continuation, future opponent policy and assassination survival are unsupported.
AP cost is exact, but its utility price defaults to unknown: costly actions have
no net utility number. An explicitly configured shadow price is subtracted once.
These approximations do not represent a calibrated chance of winning.

This prototype supplies an auditable comparison rather than a chosen action.
No live MenuClient integration or action-effect claim is made. The separate
`live_plan.json` requires explicit new authorization and a reviewed context
builder/logging integration before any later paid run, reusing the old runtime.

## Exports and reproduction

`source_audit.json`, `source_input_manifest.json` and
`source_record_inventory.jsonl` record provenance, schema availability and
hashes. `selected_bottleneck.json` records the selected hypothesis, supporting
snapshot IDs, counterexamples and deliberately unmodified alternatives.

`paired_outcomes`, `decision_diagnostics`, `phase_transitions`,
`cross_replay_metrics`, `fixed_vote_situations`, `merlin_failure_paths` and
`belief_action_link` have CSV/JSONL exports. `trajectories/` stores initial legal
views, exact public streams, predecision/round-end/preterminal scores, full joint
checkpoints and factor deltas. Truth annotations belong to host scoring files.

`runtime_diagnostics.json`, `repeatability.json` and
`budget_reconciliation.json` account only for old r7 requests. Unknown usage
retains its full reserve. The difference between off-peak usage estimates and
peak-rate conservative charging is accounted per request. No invoice is read.

`controlled_validation_replays.jsonl` contains newly generated engine games;
they are not LLM samples. `candidate_contexts.jsonl` contains the aid and its
hash/legality checks, with candidate actions and effects explicitly not_run.
`summary.json` and `report.md` distinguish observed/derived results, hypotheses,
model-dependent proxy values, unavailable fields and unrun model effects.
