# Joint Belief v2 offline suite

This suite extends the existing game loop and observation boundary. It does not
change game rules, Agent prompts, role permissions, resources, or model adapters.
Production defaults retain v1 behavior; explicitly pass
`LikelihoodConfig(mission=MissionLikelihoodConfig(enabled=True, q=.5, gamma=.5))`
to `BeliefEngine` to enable the candidate. The default candidate is tempered and
is not claimed to be a calibrated model of opponent behavior.

The frozen `avalon/eval/frozen_v1/` files are byte copies of the evaluated sources,
verified against `results/joint_belief/20260917-local500/source/`. Their provenance
file lists SHA-256 hashes. Do not edit these references when improving candidates.
The legacy independent baseline retains its historical raw marginals; its product
projection is scoring-only and never an action input.

Run from the repository root:

```bash
.venv/bin/python -m avalon.eval.joint_belief --suite joint_v2 --profile smoke --run-id my-smoke
.venv/bin/python -m avalon.eval.joint_belief --suite joint_v2 --profile offline_full --run-id my-full
.venv/bin/python -m avalon.eval.joint_belief --suite joint_v2 --profile report_only --run-dir results/joint_belief_v2/my-full
```

The historical CLI without `--suite` remains compatible. New run directories must
not already exist. Both execution profiles gate generation on deterministic and
full repository regression tests. Tests write JUnit XML and logs. `offline_full`
pre-registers 100 new replay games (20 development, 20 validation, 60 held-out),
retains the old 20 games as historical diagnostics, runs six passive variants,
then 30 smoke pairs, 200 single-seat main pairs and 20 whole-table diagnostic
pairs. `smoke` uses six new replay games, six smoke pairs, eight single-seat and
two whole-table diagnostic pairs. These sizes are not statistical power claims.
`--workers 1` improves latency interpretability; the default four workers changes
wall-clock timing, not keyed game randomness. Bootstrap defaults to 2,000 draws.

The corpus generator, candidate likelihoods, primary metrics, split assignments,
and held-out strategy combinations are frozen before generation. Correctness
fixtures exercise all policy capabilities, but held-out results do not tune q,
gamma, social weights or policy parameters. Transparent regression policies are
not treated as realistic deception. The new policies share legal social actions
across roles and sample styles independently of identity. Role permissions still
come from production legal views. Coordinated evil play intentionally violates
the candidate's independent-saboteur approximation in some scenarios.

Passive versions receive identical initial views and public streams. Live game
pairs only match initial conditions and semantic random sources; trajectories can
separate after a changed action. The focal original controlled policy already
uses joint clean-team probability. Separate P2 snapshots compare that policy with
a marginal product and with model-based mission failure risk on the *same*
posterior. Alternative policies are not executed as a new win-rate tournament.
Assassin snapshots retain deterministic probability argmax behavior. No recursive
ToM or calibrated Merlin exposure model is implemented.

The complete joint worlds and log probabilities, hard exclusions, origin factors,
raw marginals and canonical state hashes are exported in a compressed JSONL
stream, rather than only Top-K. The report-only mode rebuilds scores' aggregation,
confidence intervals, plots, coverage, episodes and prose from raw CSV/JSONL and
requires a byte-identical summary. Input archives contain offline referee labels;
never load them into a player-facing Agent context.

Mission evidence uses production `good_may_fail`, `evil_may_succeed` and the event's
public failure threshold. Exact count is one draw; Boolean observations marginalize
possible counts. Hard feasibility remains available when good sabotage has no soft
policy model; such cases explicitly skip the unsupported soft likelihood. Frozen
v1 only supports the exact-count production events it originally evaluated; hidden
count and alternative-threshold fixtures test the candidate rather than pretending
historical v1 implemented those interfaces.

This offline suite makes no external model calls; its historical results retain
`not_run` and unavailable live usage. An independent, explicitly authorized
DeepSeek action experiment is available via `avalon.eval.v2.live_runner`; see
[joint-belief-live.md](joint-belief-live.md) for budgets, gates and commands.
There is no implicit paid-mode or scripted-action fallback. The language parser
remains a separate experiment and is not enabled by the live action runner.

Constant mission likelihoods cancel analytically without adding/subtracting a
floating-point log offset. This preserves exact downstream argmax ties while
retaining evidence provenance. A post-test numerical correction can be recorded
with `--correctness-rerun-of <prior-run-directory>`: it requires the same scenario
manifest and byte-identical replay corpus, discloses test reuse, and never pools
the repeated games as additional independent samples. The first evaluated run
remains available in its own directory.
