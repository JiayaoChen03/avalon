# AGENTS.md

## Avalon Project Instructions

This file defines durable repository-level instructions for Codex and other coding agents working on Avalon.

The current experiment state is intentionally **not** maintained here. Read `docs/CODEX_HANDOFF.md` before modifying evaluation code, agent policy, prompts, belief logic, or production behavior.

---

## 1. Project purpose

Avalon is an LLM-agent social-deduction game and research environment.

The current research program focuses on:

- social deduction under asymmetric information;
- probabilistic joint belief over hidden roles;
- Merlin concealment versus Assassin identification;
- strategically useful but legally observable public behavior;
- reproducible evaluation of agent-policy changes;
- preserving the distinction between mechanism evidence and full-game capability gains.

Agent quality improvements must not come from hidden-ground-truth leakage, post hoc scenario selection, silent action repair, or evaluation artifacts.

---

## 2. Mandatory startup procedure

Before starting any non-trivial task:

1. Read this file.
2. Read `docs/CODEX_HANDOFF.md` in full.
3. Inspect the latest run directories explicitly referenced by the handoff.
4. Verify that referenced artifacts exist before relying on them.
5. Check the current git/worktree status.
6. Identify:
   - the production behavior that is frozen;
   - the single mechanism or component allowed to change;
   - the current gate;
   - the currently prohibited actions.
7. If repository state conflicts with the handoff, stop the affected experiment and report the conflict before modifying behavior.

Do not infer the current experiment state from an older report merely because it is more detailed.

---

## 3. Information-boundary rules

These are hard constraints.

### 3.1 Acting agents

An acting agent may receive only information legally available to its role and public history at that point in the game.

Never expose to an acting agent:

- hidden ground truth not authorized by its role;
- another agent's private belief state;
- another agent's private plan or hidden reasoning;
- evaluator labels;
- future events;
- post-game role reveals before they are legally public;
- counterfactual-arm labels;
- experiment-condition labels that would not exist in production.

### 3.2 Ground truth

Ground truth may be used by an offline scorer after actions have been produced.

Ground truth must not alter:

- legal menus;
- model prompts;
- evidence extraction;
- action selection;
- public behavior;
- retry feedback.

### 3.3 Assassin evaluation

Assassin identification must be measured from the Assassin's own legal belief state.

Do not substitute:

- Merlin's self-belief;
- another evil agent's belief;
- a shared evaluator posterior;
- a scorer-side reconstruction that the Assassin could not possess.

When an experiment changes Merlin behavior, explicitly separate:

- `intervention_actor_id`
- `measurement_observer_id`

The measurement observer must be the intended legal observer for the hypothesis being tested.

---

## 4. Frozen production baseline

Unless `docs/CODEX_HANDOFF.md` explicitly authorizes a new experiment, preserve:

- production belief engine: `joint_v2`;
- production evidence logic and weights;
- mission likelihood behavior;
- legal action menus;
- role-information boundaries;
- atomic/sealed vote behavior;
- runtime checkpoint semantics;
- Assassin target selection through native Merlin marginals;
- exact production argmax / exact-equality tie behavior;
- existing production decoder contract.

The following mechanisms remain off unless a specific experiment explicitly enables them:

- language belief factors;
- recursive Theory of Mind;
- cross-game strategic memory for the current research comparison;
- retired or experimental Merlin candidates;
- experimental voting policies.

Do not silently promote an experiment into production.

---

## 5. Experimental discipline

Always distinguish these claim levels:

1. **Engineering correctness** — code, replay, serialization, validation, and tests behave as intended.
2. **Mechanism/channel evidence** — a legally observable intervention changes the intended belief or decision pathway.
3. **Candidate-policy effect** — a specific legal policy reliably changes that pathway under controlled comparisons.
4. **Full-game effect** — the candidate changes paired game outcomes, such as good-side win rate or Merlin survival conditional on reaching assassination.

A result at one level does not establish the next level.

Examples:

- passing regression tests does not prove stronger play;
- changed public text does not prove changed Assassin belief;
- changed Assassin belief does not prove higher good-side win rate;
- higher Merlin survival alone does not prove a better policy if missions are lost earlier.

---

## 6. Counterfactual and replay rules

For any counterfactual comparison:

- start from a verified legal pre-intervention state;
- clone the state before intervention;
- keep all exogenous conditions fixed when the design requires pairing;
- change only the preregistered treatment variable;
- never inject future events from the reference branch into the candidate branch after divergence;
- never fabricate missing events;
- never force-match decisions from already-diverged trajectories by round number or ordinal position;
- preserve missing arms as missing rather than treating them as losses.

Historical replay data may be used for mechanism diagnostics only when its provenance and replay status are explicit.

Do not call historical diagnostic data "new held-out evidence."

---

## 7. Evidence and posterior rules

For every belief-changing experiment, preserve provenance sufficient to reconstruct:

- public source event;
- signal ID;
- factor origin;
- factor name;
- factor likelihood;
- whether the factor is constant on live support;
- whether the factor was consumed;
- whether duplicate suppression occurred;
- posterior before and after;
- exact top set before and after;
- raw floating-point deltas where relevant.

An observer's own action is not automatically evidence to that same observer.

When validating a cross-agent effect, confirm that the changed action actually enters the intended observer's evidence pathway.

Do not interpret a factor as discriminative merely because its numeric value differs from 1.0. It must differ across relevant live hypotheses after conditioning.

---

## 8. Numeric tie handling

Production currently uses exact numeric comparison.

Diagnostic epsilon values may be used for auditing only.

Do not silently replace production equality with tolerance-based equality.

If floating-point order or constant-factor renormalization changes exact top-set membership:

1. preserve the original behavior;
2. create a minimal reproducible fixture;
3. classify whether the effect reaches an actionable production boundary;
4. version any behavioral fix separately;
5. do not attribute benefits from a numeric bug fix to an agent-policy candidate.

---

## 9. LLM/API rules

External model calls are allowed only when the current handoff explicitly authorizes them.

If API work is authorized:

- use the existing transport/client stack;
- preserve the production request protocol unless the experiment explicitly concerns that protocol;
- persist safe response material before action decoding when required by the current evaluation harness;
- persist usage accounting for accepted and rejected outputs;
- count retries and failed attempts against the experiment budget;
- do not silently switch model/provider;
- do not fabricate usage when provider usage is missing;
- fail closed when the budget ledger cannot be trusted.

A previous experiment's API authorization does not automatically carry forward.

---

## 10. Model-output validation

Never silently repair an invalid model action into a valid action.

Allowed behavior:

- reject;
- provide bounded validation feedback;
- retry when the active protocol permits it;
- preserve the failed attempt for audit when required.

Do not invent a replacement action after retry exhaustion.

Do not infer missing historical response content from hashes, downstream state, or later reports.

---

## 11. Test interpretation

Every changed evaluation mechanism must include targeted regression tests.

When reporting tests:

- distinguish executed test count from unique test-ID count;
- do not add overlapping targeted and full-regression suites as if they were independent coverage;
- preserve failed historical validation runs instead of overwriting them;
- bind test artifacts to a run ID and code state when possible.

A green test suite is evidence of engineering consistency, not capability improvement.

---

## 12. Result and artifact rules

Every research run should have a unique run directory.

Recommended artifacts include, as relevant:

- config / frozen-boundary manifest;
- source manifest and hashes;
- replay verification;
- intervention inventory;
- factor provenance;
- posterior/tie diagnostics;
- validity and exclusion reasons;
- API attempt journal;
- usage/cost summary;
- gate file;
- final report;
- test results.

Reports must distinguish:

- scenarios;
- games;
- observers;
- paired cutoffs;
- branch rows;
- model logical requests;
- actual request attempts.

Do not use row counts as independent sample counts without justification.

---

## 13. Updating the handoff

At the end of a substantial research task, update `docs/CODEX_HANDOFF.md` with only:

- newly validated facts;
- invalidated prior conclusions;
- latest run IDs;
- current blockers;
- current frozen boundaries;
- exact next allowed task;
- exact prohibited tasks;
- important artifact paths.

Do not paste conversation history into the handoff.

Do not convert an unresolved issue into a positive or negative finding merely to simplify the handoff.

---

## 14. Authority and conflict order

For current research execution, use this precedence:

1. current repository code and legally generated artifacts;
2. `docs/CODEX_HANDOFF.md`;
3. this `AGENTS.md`;
4. latest validated run report;
5. older run reports and historical diagnostics;
6. conversation summaries or informal notes.

If two sources conflict, do not silently reconcile them. Report the conflict and determine which artifact is actually valid for the current gate.

---

## 15. Production promotion rule

No candidate becomes production-default merely because:

- it changes behavior;
- it lowers a diagnostic Merlin probability;
- it survives a small pilot;
- it passes tests.

Production promotion requires an explicit decision after the relevant causal gates and outcome validation have passed.

Default state for research candidates: **OFF**.
