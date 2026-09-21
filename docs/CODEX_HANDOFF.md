# CODEX_HANDOFF.md

## Avalon Optimization Handoff

**Status:** active research handoff  
**Last validated state:** Joint Belief V2.3.2-r2, accepted V3 offline candidate audit
**Latest reviewed P1 run:** `20260919-v232-r2-p1-offline-v12`  
**Latest safety audit:** `20260920-v232-safety-r2`  
**Latest preregistration draft:** `20260921-v232-camouflage-v3-mission-outcome-safety-prereg-r2`  
**Latest preregistration review:** R2 prepared; execution not authorized
**Latest offline candidate run:** `20260920-v232-camouflage-v3-offline-r1`
**Latest full-game validation:** `20260920-v232-camouflage-v3-full-game-r1`
**Latest P0 run:** `20260919-v232-r2-p0`  
**Production candidate:** OFF  
**Paid/API work for the immediate next task:** NOT AUTHORIZED; R2 is preregistration-only and production promotion remains blocked

The latest full-game validation gate is `FULL_GAME_EFFECT_BUT_UNSAFE`; production promotion was not performed.

This file is the authoritative summary of the current optimization state. It is deliberately narrower than the full research history.

---

## 1. Current objective

Determine whether a **legally controllable Merlin action** can alter the Assassin's Merlin-identification process without unacceptable game-play cost.

The current target mechanism is voting, because previous attribution work found meaningful Merlin-identification updates concentrated in the `team_vote` pathway.

The current task is **not** generic prompt tuning and is **not** a request to make Merlin "sound less suspicious."

Current causal chain:

```text
legal Merlin behavior
→ public observable signal
→ Assassin evidence extraction
→ Assassin joint_v2 posterior
→ Assassin Merlin ranking / exact top set
→ safe candidate policy
→ paired full-game outcome effect
```

Do not skip intermediate gates.

---

## 2. Current production freeze

Preserve unless a later handoff explicitly changes this section:

- belief engine: `joint_v2`;
- production evidence extractor and weights;
- mission likelihood;
- legal action menu;
- role-information isolation;
- sealed/atomic voting behavior;
- runtime checkpoint behavior;
- Assassin native Merlin-marginal argmax;
- exact production equality for top-set/tie handling;
- current Assassin decoder contract.

Keep disabled:

- language belief factors;
- recursive Theory of Mind;
- cross-game strategic memory for this research comparison;
- v2.2 vote candidate;
- retired Merlin disclosure candidate;
- any newly proposed Merlin candidate.

No production promotion is authorized.

---

## 3. Validated historical findings

### 3.1 V2.3.1: old MerlinDisclosureContext mechanism

The old `MerlinDisclosureContext` candidate changed some Merlin public SOCIAL behavior, including text and some structured actions.

In the frozen action-only one-step path, those changes did not produce a demonstrated Assassin posterior/rank/exact-top change.

Relevant pathway:

```text
MerlinDisclosureContext
→ public SOCIAL event
→ Observation
→ EvidenceExtractor
→ joint_v2
→ Assassin native Merlin marginal argmax
```

The candidate is retired **for this mechanism**.

Do not generalize that result into any of the following unsupported claims:

- language can never matter;
- Merlin concealment cannot work;
- voting cannot matter;
- full-game outcome improvement is impossible.

### 3.2 V2.3.2 attribution

V2.3.2 attribution identified `team_vote` as the dominant observed numeric route associated with meaningful Merlin-identification changes in the replay diagnostics.

This motivates testing whether **Merlin's own legal vote** can alter the Assassin's belief when the relevant pre-state and other votes are held fixed.

Early lock-row counts must not be treated as independent game-level effects.

---

## 4. P0 status

### 4.1 Run

```text
20260919-v232-r2-p0
```

### 4.2 Overall P0 conclusion

P0 performed engineering repairs around response persistence, replay verification, request/decoder diagnostics, and source/cutoff verification.

The live request-contract result remained:

```text
FAIL_REQUEST_PROTOCOL_CONFLICT
```

A corrected real-language contract retest was **not run**.

Therefore:

- do not claim the language path is validated;
- do not automatically resume the previous DeepSeek pilot;
- do not spend API budget for the immediate P1 repair.

### 4.3 Response persistence repair

The earlier pilot could lose safe model response content because decoding happened before durable persistence on the failing path.

P0 moved persistence earlier so that safe response material can be retained before action JSON decoding.

Historical r1 missing response bodies remain unrecoverable.

Do not reconstruct them from hashes, usage, downstream state, or later experiments.

### 4.4 Replay verification

P0 reported:

- total sources: 156;
- fully verified: 155;
- partially verified: 1;
- excluded: 0;
- unresolved: 0.

One r7 source was only verified to a cutoff because the archived source lacked the later terminal portion.

P1 may use only cutoffs explicitly marked verified in P0 replay cutoff artifacts. A partially verified source may only be used up to its verified cutoff.

Do not describe the entire source set as full replay PASS.

---

## 5. P1 latest status

### 5.1 Latest reviewed run

```text
20260919-v232-r2-p1-offline-v7
```

### 5.2 Overall status

The reviewed v7 run is **not accepted** for its vote-effect conclusion because it measured the wrong observer. The corrected v12 measurement is technically valid, while its candidate gate remains unsafe.

The run contains useful engineering repairs, but the central vote-intervention result is invalid for the intended causal claim because the experiment measured the wrong observer.

The reported result:

```text
12 vote branches
0 Assassin-identification changes
```

must not be carried forward as evidence that Merlin voting is ineffective.

Current interpretation for that vote-effect result:

```text
INVALID_MEASUREMENT
```

### 5.3 Corrected Assassin-observer rerun

The corrected run is `20260919-v232-r2-p1-offline-v12`. It reuses the same six preregistered paired cutoffs and has 6 valid pairs, 0 invalid pairs, and 12 branch rows. `intervention_actor_id` is the reconstructed Merlin and `measurement_observer_id` is the actual Assassin in every valid pair. The changed vote is consumed once in the Assassin `team_vote` pathway; aggregate `TEAM_VOTE` duplicates are recorded as suppressed. No decoder or external API was called.

The vote-channel gate is:

```text
ACTIONABLE_BUT_POTENTIALLY_UNSAFE
```

All six pairs have a meaningful Assassin-side delta under the diagnostic threshold. The corrected wrong-lock accounting is 56 contiguous wrong-lock episodes across 310 observer trajectories, with 7,784 wrong event rows; the former 143 count was the actionable-row count, not an episode count. Numeric sensitivity remains internal-only and unresolved at an actionable production boundary.

Phase 2 produced `vote_signal_analysis.md` and `vote_signal_cases.csv`, separating correlation-only context from mechanism-consistent and causal paired evidence. The one and only offline candidate, `MerlinVoteCamouflageV1`, is frozen in `candidate_spec.md`; it has 6 valid fixed-state comparisons, 3 meaningful effects, and gate:

```text
CANDIDATE_EFFECT_BUT_UNSAFE
```

Safety is `NOT_PROVEN` because these vote-only states do not contain mission outcomes. This is an offline result only; the candidate remains disabled.

### 5.4 Corrected candidate baseline and safety audit

The v12 candidate comparison used a fixed approving reference arm. That was not a valid comparison to the recorded Merlin policy for the three cases where the historical Merlin rejected. Those three candidate-effect claims are invalidated as policy effects; the underlying Assassin vote-channel measurement remains valid.

The corrected safety audit is `20260920-v232-safety-r2`. It uses the recorded Merlin boolean vote and recorded `strong` modifier as baseline, preserves the same six cutoffs and preregistered other ballots, and changes only the boolean vote. It has 6 valid pairs, 0 invalid pairs, 1 meaningful Assassin-side effect (`delta_p_merlin=-0.0263247404`), 0 hard safety failures, and 1 unresolved clean-team delay. The 96 other-ballot combinations are sensitivity diagnostics, not new game samples. No future events were injected, and no API was called.

The corrected candidate gate remains:

```text
CANDIDATE_EFFECT_BUT_UNSAFE
```

The effect comes from rejecting a clean team that the recorded baseline approved; the downstream mission/game value is unknown. The candidate remains OFF and no full-game proposal is unlocked.

### 5.5 Revised clean-team-guard preregistration

The new single-candidate draft is `20260920-v232-camouflage-v2-prereg-r1`. `MerlinVoteCamouflageV2CleanTeamGuard` hard-guards every team with no Merlin-known evil member to `APPROVE`, removing the observed clean-team-delay row by policy definition. On teams containing Merlin-known evil, it retains the frozen public-only ambiguity branch; any resulting dirty-team approval is a hard safety failure. At drafting time the specification copied the same six r2 cutoffs without replacement or expansion, forbade current sealed-ballot access, and remained implementation-disabled, production-OFF, API-OFF, and full-game-OFF. Static preregistration validation passed with zero network calls.

The static review passed the information-boundary, sample-freeze, single-variable, clean-team-guard, safety-gate, and no-network checks. The user then explicitly accepted the frozen preregistration for the separate offline evaluator. The review itself did not establish an Assassin effect or safety result.

### 5.6 Accepted V2 offline evaluator

The authorized evaluator run is `20260920-v232-camouflage-v2-offline-r2`. The implementation matched the frozen specification and evaluated exactly 6 valid paired cutoffs, 0 excluded pairs, and 12 branch rows. The candidate changed 0 Merlin votes and produced 0 meaningful Assassin-side effects. It had 0 hard safety failures, 0 unresolved safety rows, 96 sensitivity rows classified as diagnostics only, and 0 network calls. Targeted tests passed 5/5; the full regression passed 546/546, with targeted tests included in that total.

The earlier r1 evaluator artifacts are preserved but superseded: r1 passed a complete `Game` object to the policy function, while r2 passes a restricted public projection so hidden roles cannot cross the policy boundary. The r1 `CANDIDATE_NO_EFFECT` result is not the current implementation-validation result; r2 is the validated run.

The terminal gate is:

```text
CANDIDATE_NO_EFFECT
```

This is a bounded negative finding for this candidate on the six fixed states. It is not a global claim that legal Merlin voting can never affect Assassin belief. The candidate remains OFF and no production or full-game conclusion is unlocked.

### 5.7 Proposed next-stage V3 preregistration

The proposed next-stage plan was created as `20260920-v232-camouflage-v3-prereg-r1`. `MerlinVoteCamouflageV3PublicConsensus` introduced a new frozen public-consensus hypothesis: public accusations, rejected overlapping teams, and failed missions each contribute one public warning, and a non-critical disagreement follows that public consensus. It used the same six corrected-r2 cutoffs in the original order, forbade sealed-ballot and hidden-role access, and remained implementation-OFF, API-OFF, full-game-OFF, and production-OFF. Static validation and review passed with zero network calls. The user explicitly accepted this preregistration before the separate offline evaluator was implemented.

### 5.8 Accepted V3 offline evaluator

The accepted evaluator run is `20260920-v232-camouflage-v3-offline-r1`. It matched the frozen V3 specification and evaluated exactly 6 valid paired cutoffs, 0 excluded pairs, 12 branch rows, and 96 sensitivity rows. The intervention actor was the reconstructed Merlin and the measurement observer was the actual Assassin in every pair. The only treatment was Merlin's boolean vote; the recorded `strong` modifier and all other ballots were fixed. The changed vote was consumed once in the Assassin `team_vote` pathway, aggregate duplicates were recorded as suppressed, no future events were injected, and no API call was made.

The candidate changed 2 of 6 Merlin votes and produced 2 meaningful Assassin-side effects. Both effects were caused by the frozen public-consensus rule rejecting a clean team, so they are hard safety failures. There were 2 hard-failure pairs and 2 unresolved downstream rows. The terminal gate is:

```text
CANDIDATE_EFFECT_BUT_UNSAFE
```

The implementation is offline-only, the candidate remains OFF, and this result does not establish a full-game effect or authorize a live test. Targeted tests passed 5/5; the explicit `tests/` regression passed 551/551 with targeted tests included in that total.

### 5.9 User-authorized V3 full-game validation

The user then explicitly authorized API calls and full-game validation. Run `20260920-v232-camouflage-v3-full-game-r1` froze six seed pairs (`960001` through `960006`) before execution, forced the focal `P1` seat to Merlin, used DeepSeek for focal Merlin actions, used the deterministic population policy for other seats, and intercepted only the candidate arm's Merlin boolean vote. All 12 physical games completed; the run made 221 API attempts, reported all usage, charged a conservative estimated ¥1.6969, and injected no future events.

The candidate arm had 3/6 Good wins and 2/6 Merlin survivals through assassination; the baseline arm had 0/6 Good wins and 0/6 Merlin survivals. These six pairs are a small validation sample and do not establish a general win-rate effect. The candidate arm nevertheless recorded 16 Merlin-legal clean-team rejections and 3 newly approved Merlin-known dirty teams. The terminal full-game gate is:

```text
FULL_GAME_EFFECT_BUT_UNSAFE
```

The apparent outcome improvement does not clear the safety gate. Production behavior remains unchanged and the candidate remains OFF.

---

## 6. P1 components that are usable

### 6.1 P0 artifact freezing

The latest P1 line used verified P0 artifacts/cutoffs and preserved the intended freeze.

### 6.2 Missing-arm classification

Missing reference arms were corrected to a missing-arm / not-comparable classification rather than being treated as invalid actions or losses.

Keep this fix.

### 6.3 Legal vote branches

The generated vote branches themselves were legal.

This does **not** validate the observer-side belief measurement.

### 6.4 Production remained unchanged

No new production Merlin candidate was enabled.

No full-game candidate comparison was completed.

No production promotion occurred.

These boundaries are correct and must remain in force.

---

## 7. Critical P1 blocker #1: wrong measurement observer

### 7.1 Problem

The latest P1 vote intervention measured the intervention actor's belief state—the Merlin seat—instead of the Assassin's legal belief state.

Observed pattern:

```text
intervention_actor_id == Merlin
measurement_observer_id == same Merlin
```

The intended Assassin was a different seat.

This invalidates the causal interpretation.

### 7.2 Why the zero result is uninformative

The evidence system excludes an observer's own action from that observer's evidence path.

The experiment therefore effectively performed:

```text
change Merlin's vote
→ inspect Merlin's own belief
→ Merlin's own vote excluded as self-action evidence
→ observe no change
```

That does not answer:

```text
change Merlin's vote
→ inspect Assassin's belief
→ does Assassin update differently?
```

### 7.3 Required repair

Introduce explicit, separate fields:

```text
intervention_actor_id
measurement_observer_id
```

For this experiment:

- `intervention_actor_id` must be the real Merlin for the reconstructed game;
- `measurement_observer_id` must be the real Assassin for the reconstructed game;
- the acting Merlin must not receive the Assassin's private state;
- the Assassin posterior is measured only by the evaluation harness after the legal intervention.

Add hard evaluation assertions that fail the pair if the measurement observer is not the Assassin or if the measurement observer equals the intervention actor for this specific experiment.

---

## 8. Critical P1 blocker #2: changed Merlin vote must enter Assassin evidence

After fixing observer binding, verify the changed Merlin vote actually enters the Assassin-side evidence path.

For every paired cutoff:

1. reconstruct the same verified legal pre-vote state;
2. clone the Assassin's pre-intervention belief state;
3. hold other players' votes fixed according to the preregistered design;
4. differ only the Merlin vote;
5. process the complete legal public vote boundary;
6. verify the Merlin vote creates the expected Assassin-observed `team_vote` signal;
7. verify it is consumed exactly once;
8. verify the aggregate vote event does not double-count the already consumed individual vote.

Required provenance fields should include:

```text
pair_id
source_run_id
game_id
round
attempt
intervention_actor_id
intervention_actor_role
measurement_observer_id
measurement_observer_role
reference_merlin_vote
candidate_merlin_vote
source_signal_id
factor_name
factor_consumed
duplicate_suppressed
posterior_before_hash
posterior_after_hash
merlin_marginal_before
merlin_marginal_after
exact_top_before
exact_top_after
merlin_rank_before
merlin_rank_after
lead_before
lead_after
```

If the changed Merlin vote does not appear in Assassin-side provenance, the pair is invalid. Do not score it as a zero-effect pair.

---

## 9. Required rerun design

Do **not** select new cases based on observed effect size.

Re-run the same preregistered set used by the latest P1 line:

```text
6 paired cutoffs
12 branches
```

using the corrected Assassin measurement observer.

The purpose is to isolate the measurement repair. Do not expand the sample before the original six pairs are correctly evaluated.

### 9.1 Pair validity requirements

Every valid pair must have:

- a P0-verified cutoff;
- identical public pre-intervention prefix;
- identical legal/mechanical pre-state;
- identical Assassin pre-belief;
- identical team/proposal context;
- identical other-player votes;
- only Merlin's legal vote changed;
- no future event injection;
- the same Assassin measurement observer in both arms;
- the same Assassin posterior before treatment;
- correct Assassin-side vote-factor provenance.

Invalid pairs must be labeled invalid/excluded with a reason. They must not be converted into zero-effect observations.

---

## 10. Critical P1 blocker #3: wrong-lock episode counting

### 10.1 Problem

The latest episode output still over-counts persistent wrong-lock states.

A sequence such as:

```text
decision boundary 1: unique top = P2 (wrong)
decision boundary 2: unique top = P2 (wrong)
decision boundary 3: unique top = P2 (wrong)
```

must not count as a new wrong-lock episode at every decision boundary if the wrong target never ceased to be uniquely top.

### 10.2 Episode definition

A wrong-lock episode begins when the observer enters:

```text
unique_top == wrong_player
```

from a state that was not already the same wrong unique-top state.

The episode continues while the same wrong player remains uniquely top.

End the episode when any of these occurs:

- the exact top becomes tied;
- the true Merlin becomes uniquely top;
- the current wrong player is no longer uniquely top;
- another wrong player becomes uniquely top;
- the relevant replay/observation sequence ends.

If the unique wrong target changes directly from one wrong player to another, terminate the previous episode and begin a new one.

### 10.3 Required regression fixture

Add a regression fixture based on the known persistent-lock pattern from the reviewed P1 data.

The test must prove:

```text
multiple consecutive decision-boundary rows
with the same wrong unique top
→ one episode, not N episodes
```

Also add tests for:

- tie breaks the episode;
- true Merlin top breaks the episode;
- wrong target A → wrong target B creates a new episode;
- re-entering the same wrong target after a tie creates a new episode.

---

## 11. Numeric tie status

Very small floating-point differences have been observed to affect exact top-set membership in diagnostic states.

Current status:

```text
NUMERIC_IMPACT_UNRESOLVED
```

This is not currently a validated Merlin-policy effect.

Do not:

- silently introduce epsilon tie logic;
- change production exact equality during the P1 policy test;
- count any numeric-behavior repair as Merlin-policy improvement.

If a numeric discrepancy is shown to reach an actual actionable Assassin decision:

1. isolate it as a separate engineering/numeric issue;
2. create a minimal fixture;
3. version the behavioral repair separately;
4. rebuild the policy baseline after that repair.

For the immediate P1 observer-binding rerun, keep production numeric behavior frozen.

---

## 12. Immediate next task

The observer-binding repair, same-six-pair rerun, signal analysis, corrected-baseline safety audit, accepted V2 evaluator, and accepted V3 evaluator are complete in `20260919-v232-r2-p1-offline-v12`, `20260920-v232-safety-r2`, `20260920-v232-camouflage-v2-offline-r2`, and `20260920-v232-camouflage-v3-offline-r1`.

The exact next allowed action is review of the V3 full-game result and its safety tradeoff in `results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/`. Production enablement is blocked by `FULL_GAME_EFFECT_BUT_UNSAFE`; an explicit safety-gate override naming this candidate and accepting the 16 clean-team rejections and 3 dirty-team approvals would be required to change that status. Any new candidate or policy still requires a new preregistration and explicit acceptance before implementation.

---

## 13. Explicitly prohibited in the immediate next task

Do not:

- make additional DeepSeek or other external model calls without a new frozen plan or explicit safety-gate override;
- resume the old language pilot;
- spend the remaining API budget on another V3 run after the terminal full-game gate;
- rerun, tune, redesign, enable, or promote `MerlinVoteCamouflageV2CleanTeamGuard` after its terminal `CANDIDATE_NO_EFFECT` gate;
- rerun, tune, redesign, enable, or promote `MerlinVoteCamouflageV3PublicConsensus` after its terminal `CANDIDATE_EFFECT_BUT_UNSAFE` gate;
- treat the 96 sensitivity rows as new samples or use them to claim a held-out effect;
- implement or enable a new Merlin policy before a new preregistration is approved;
- enable the v2.2 voting candidate;
- enable language belief;
- enable recursive ToM;
- enable cross-game memory;
- modify Assassin production rules;
- modify production tie equality;
- run additional full candidate-vs-reference games after `FULL_GAME_EFFECT_BUT_UNSAFE` without a new frozen plan;
- promote V3 to production without an explicit safety-gate override naming the candidate and accepting its recorded safety failures;
- choose replacement scenarios based on which produce favorable effects.

The V2 evaluator is complete as an offline-only run with `CANDIDATE_NO_EFFECT`; the V3 evaluator is complete as an offline-only run with `CANDIDATE_EFFECT_BUT_UNSAFE`. Both remain disabled and are not production candidates.

---

## 14. Acceptance criteria for corrected P1 vote measurement

The vote-mechanism test may be considered technically valid only if all of the following hold.

### Identity and information boundaries

- acting seat is the intended Merlin;
- measurement seat is the actual Assassin;
- acting Merlin receives no Assassin-private state;
- scorer truth is not passed into action generation.

### Pair construction

- same verified cutoff;
- same public prefix;
- same pre-intervention game state;
- same Assassin pre-belief;
- same team;
- same other-player votes;
- only Merlin vote differs.

### Evidence path

- changed Merlin vote is visible to the Assassin only when legally public;
- the corresponding Assassin-observed `team_vote` signal exists;
- the signal is consumed once;
- aggregate vote representation does not double-weight the same vote.

### Measurement

Compare both arms on:

- true-Merlin marginal;
- true-Merlin rank;
- exact top set;
- lead over the next candidate;
- posterior hash/raw values;
- whether any change survives to the intended decision boundary.

### Reporting

Report separately:

- number of source scenarios;
- number of games;
- number of paired cutoffs;
- number of valid pairs;
- number of excluded pairs;
- branch-row count.

Do not call six paired cutoffs "six independent games" unless they actually are.

---

## 15. Interpretation after rerun

Possible valid outcomes include:

### A. No Assassin belief effect

If the corrected Assassin-side measurement shows no change across all valid pairs:

```text
VOTE_CHANNEL_NOT_DEMONSTRATED_IN_TESTED_PAIRS
```

This is a bounded negative finding. Do not expand it into "voting can never matter."

### B. Assassin belief changes, but only unsafely

If changing Merlin's vote changes Assassin identification but requires unacceptable task/game cost:

```text
ACTIONABLE_BUT_UNSAFE_CHANNEL
```

Do not proceed to a production candidate.

### C. Assassin belief changes under legally plausible safe choices

If preregistered valid pairs demonstrate a legally actionable effect without obvious immediate game-breaking cost:

```text
ACTIONABLE_VOTE_CHANNEL_FOUND
```

Then design a **separate**, single candidate specification before any live/full-game test.

Do not automatically implement or promote it in the same repair run.

---

## 16. API/language path status

The earlier language/tie pilot remains unresolved because of request-protocol/output failures.

P0 repaired persistence and diagnosed the protocol conflict, but the corrected real contract was not retested.

Current language-path status:

```text
NOT_VALIDATED
```

This path is independent of the immediate P1 voting repair.

Do not conflate successful vote-channel validation with proof about language tie-breaking.

Do not resume the language pilot until a future handoff explicitly authorizes it.

---

## 17. Current candidate status

`MerlinVoteCamouflageV1` remains blocked by `CANDIDATE_EFFECT_BUT_UNSAFE` after the corrected-baseline safety audit and is not a production candidate. The accepted `MerlinVoteCamouflageV2CleanTeamGuard` evaluator completed with `CANDIDATE_NO_EFFECT` on the six fixed states and remains OFF. The accepted `MerlinVoteCamouflageV3PublicConsensus` evaluator completed with offline `CANDIDATE_EFFECT_BUT_UNSAFE` and full-game `FULL_GAME_EFFECT_BUT_UNSAFE`; it also remains OFF. The old disclosure-context candidate remains retired for the previously tested action-only mechanism.

Current state:

```text
candidate_enabled_by_default = false
production_promotion = false
```

Any future candidate must have its own frozen specification and causal hypothesis before implementation.

The V2 draft artifacts are:

```text
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-prereg-r1/candidate_spec.md
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-prereg-r1/preregistered_plan.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-prereg-r1/preregistered_cases.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-prereg-r1/preregistration_manifest.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-prereg-r1/preregistration_validation.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-prereg-r1/preregistration_review.md
```

The accepted V2 offline evaluator artifacts are:

```text
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/candidate_implementation_audit.md
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/candidate_vote_interventions.csv
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/candidate_assassin_effect.csv
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/candidate_safety_tradeoff.csv
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/candidate_safety_gate.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/source_manifest.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/config.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/unit_tests.xml
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/regression_tests.xml
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/test_results.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/report.md
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/summary.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/proposed_next_stage_test_plan.md
```

The V3 preregistration artifacts are:

```text
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-prereg-r1/candidate_spec.md
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-prereg-r1/preregistered_plan.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-prereg-r1/preregistered_cases.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-prereg-r1/preregistration_manifest.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-prereg-r1/preregistration_validation.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-prereg-r1/preregistration_review.md
```

The accepted V3 offline evaluator artifacts are:

```text
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/candidate_implementation_audit.md
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/candidate_vote_interventions.csv
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/candidate_assassin_effect.csv
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/candidate_safety_tradeoff.csv
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/candidate_safety_sensitivity.csv
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/candidate_safety_gate.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/source_manifest.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/config.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/unit_tests.xml
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/regression_tests.xml
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/test_results.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/report.md
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/summary.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/proposed_next_stage_test_plan.md
```

The user-authorized V3 full-game validation artifacts are:

```text
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/preregistered_full_game_plan.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/full_game_gate.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/summary.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/games.csv
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/full_game_replays.jsonl
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/candidate_decisions.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/llm_calls.jsonl
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/budget.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/source_manifest.json
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/report.md
```

---

## 18. Important result directories

Expected repository paths:

### P0

```text
results/joint_belief_v2_3_2/20260919-v232-r2-p0/
```

Important P0 artifacts include:

```text
replay_cutoffs.jsonl
replay_verification_details.json
response_journal.jsonl
api_attempts.jsonl
validation_failures.jsonl
```

### Latest reviewed P1

```text
results/joint_belief_v2_3_2/20260919-v232-r2-p1-offline-v12/
```

Important P1 artifacts include:

```text
p1_gates.json
p1_corrected_report.md
test_results.json
vote_interventions.csv
vote_factor_provenance.jsonl
vote_safety_audit.csv
lock_episodes.csv
numeric_counterexamples.jsonl
comparison_classification_changes.csv
vote_channel_gate.json
vote_signal_analysis.md
vote_signal_cases.csv
candidate_spec.md
candidate_vote_interventions.csv
candidate_assassin_effect.csv
candidate_safety_tradeoff.csv
candidate_gate.json
unit_tests.xml
regression_tests.xml
```

If filenames differ in the actual repository, inspect the run manifest rather than inventing replacements.

### Latest safety audit

```text
results/joint_belief_v2_3_2/20260920-v232-safety-r2/
```

Important safety artifacts include:

```text
preregistered_plan.json
source_manifest.json
candidate_assassin_effect.csv
candidate_vote_interventions.csv
candidate_safety_tradeoff.csv
candidate_safety_sensitivity.csv
candidate_safety_gate.json
safety_report.md
unit_tests.xml
regression_tests.xml
test_results.json
```

### Latest preregistration draft

```text
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-prereg-r1/
```

This directory contains the new public-consensus specification, frozen six-case selection, source/hash manifest, static validation, and static review only. It contains no candidate implementation, model call, full-game run, or production change. The previously accepted V2 preregistration remains at `results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-prereg-r1/`.

### Latest offline evaluator

```text
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-offline-r1/
```

This run contains the separate V3 evaluator implementation audit, six-pair outputs, safety gate, source manifest, targeted/full regression artifacts, and the review-only proposed next-stage test plan. It contains no API call, full-game run, candidate enablement, or production promotion. The V2 offline evaluator remains preserved at `results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-offline-r2/` as the preceding terminal run.

### Latest full-game validation

```text
results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/
```

This run contains six frozen paired seeds, 12 completed games, 221 API attempts with reported usage, candidate decision provenance, paired outcomes, and a full-game safety gate. It is outcome validation only; production remains OFF.

---

## 19. Historical conclusion precedence

Older reports are evidence archives, not automatically current truth.

In particular, do not carry forward:

```text
NO_ACTIONABLE_CHANNEL_FOUND
```

as a global conclusion merely because an older V2.3.2 report used that label.

Later review invalidated the latest vote-effect zero as a measurement result because the wrong observer was used.

Keep the raw historical observation, but update the interpretation.

Likewise:

- old lock-row counts are not episode counts;
- early language-pilot failures do not prove language has no effect;
- engineering test success does not prove stronger gameplay.

---

## 20. Required handoff update after the next P1 repair

The latest offline repair has now updated this file with:

1. new run ID;
2. whether observer binding was corrected;
3. number of valid/excluded paired cutoffs;
4. whether the Merlin vote entered Assassin evidence exactly once;
5. measured Assassin posterior/rank/top-set effects;
6. corrected wrong-lock episode counts;
7. test status;
8. numeric-tie status;
9. resulting mechanism gate;
10. exact next allowed task.

Do not paste raw logs into this document. Link to artifacts by repository path.

---

## 21. New-session startup checklist

When Codex starts from a fresh conversation, it should first report:

- current production freeze;
- latest P0 run;
- latest P1 run;
- validated findings;
- invalidated findings;
- current blockers;
- exact immediate task;
- prohibited actions;
- whether referenced artifacts exist;
- whether repository state conflicts with this handoff.

Do not modify code until this check is complete.


## 22. V3 full-game offline reconciliation correction (2026-09-20)

对既有 run `20260920-v232-camouflage-v3-full-game-r1` 只做离线对账和机制诊断；本轮没有新增 API 调用、没有新对局、没有候选实现或生产变更。原 gate、report、逐事件回放、策略记录、终局记录及现有哈希未覆盖。

- 终局字段口径已核正：`merlin_assassinated` 是实际 ASSASSINATE 命中真实 Merlin 的 hit 标记/计数，不是存活数。candidate 六对为 Good 胜 `3/6`、刺杀阶段到达 `5/6`、命中 `2/6`、实际 miss `3/6`、刺杀前以 `three_failed_missions` 结束 `1/6`；实际进入刺杀且有刺杀事件的局中成功躲过为 `3/5`。`v3-full-960003` candidate 未进入刺杀阶段，不能计为成功躲过刺杀。baseline Good 胜 `0/6`、刺杀阶段 `6/6`、命中 `6/6`。
- `12/13` 是六条 baseline/candidate 实际轨迹中按终局真值统计的实际 clean-team rejection；`16/3/41` 是 41 条 candidate P1 Merlin policy override 输出上的 policy-level 统计，不能与实际终局事件或 same-state baseline 差分互换。`candidate_policy_new_dirty_team_approvals=3` 只能解释为 3 个 Merlin 已知邪方队伍上的 approve 输出，原 run 没有保存 same-state baseline shadow。
- 新增派生 artifacts：`results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-full-game-r1/metric_reconciliation.md`、`safety_event_ledger.csv`、`contract_feasibility_review.md`。ledger 保留 actual clean truth 与 Merlin legal known-evil 两个独立字段；same-state baseline vote 全部为 null。
- deterministic `joint_v2` Assassin observer 可从实际 public prefix 重建每票前后 posterior/rank/exact-top/tie；没有预注册的同状态双布尔 full-game cutoff，因此未宣称跨 arm causal posterior/target change，也未复用分叉后的后续事件。
- 观察到 candidate Good 胜率的正向差异，但 `full_game_effect_claim` 仍为 `NOT_ESTABLISHED`，原 safety gate 仍为 `FULL_GAME_EFFECT_BUT_UNSAFE`，`production_enablement=false`，`candidate_default=OFF`。
- 当前 blocker：41 行中 19 个 `PUBLIC_CONSENSUS` 分叉全部触发冻结 safety 边界（16 policy clean-team rejections + 3 policy dirty-team approvals）；full-game 样本也没有合法 same-state baseline shadow。
- exact next allowed task：如需继续，另行授权并重新 preregister 带 mission outcome 的 verified fixed-state 离线 safety evaluation。禁止覆盖 gate/日志/哈希，追加 API 或付费 full-game，生产启用 V3，修改规则/belief/Assassin/strong/其他席位策略，或自动实施/运行 V4。

- 边界核查补充：ledger 的 public prefix hash 按每个 Merlin 决策的 `after_seq` 计算；当前轮尚未揭示的逐人 `VOTE` 密封票被排除，不能从 `TEAM_VOTE` 之前的原始事件序列倒灌回 PublicConsensus。
- ledger 字段补充：`merlin_legal_known_evil_set` 使用该决策合法 view 的完整集合，`merlin_legal_known_evil_on_team` 另列队伍交集；两者均不使用 scorer truth。


## 23. Full-game closure and next offline safety preregistration (2026-09-20)

- `20260920-v232-camouflage-v3-full-game-r1` is **CLOSED**. Its `metric_reconciliation.md` is the authoritative correction for current full-game metric definitions. The run retains `full_game_effect_claim=NOT_ESTABLISHED`, `production_enablement=false`, `candidate_default=OFF`, and gate `FULL_GAME_EFFECT_BUT_UNSAFE`.
- No action in this closure changes `MerlinVoteCamouflageV3PublicConsensus`, reinterprets the gate, adds API calls, adds games, or enables production.
- Any future experiment must use a new run ID.
- New preregistration ready, execution not authorized: `results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-mission-outcome-safety-prereg-r1/`. It freezes exactly six historical same-state cutoffs from `20260920-v232-camouflage-v3-offline-r1`; the closed full-game baseline trajectory is not used as a same-state comparator.
- The preregistration defines baseline as the archived reference Merlin action at the exact cutoff and candidate as the unchanged V3 policy. It separates clean-team rejection, dirty-team approval, their mission-outcome cross-tabs, and same-state action disagreement.
- Mission outcome is evaluator-only and is generated after action selection. It cannot enter candidate input, excuse a clean-team rejection, or excuse a dirty-team approval. Candidate input remains limited to the cutoff public prefix, Merlin legal private knowledge, and the unchanged legal state boundary; current sealed votes, future events, evaluator labels, truth, and mission results are excluded.
- Prepared artifacts include the frozen state manifest, metric specification, mission-outcome evaluator specification, leakage audit, output schema, preregistration review, and source hashes. No evaluation output exists for this new run.
- Exact status: `NEW OFFLINE SAFETY PREREGISTRATION READY`; `EXECUTION: NOT AUTHORIZED`; `API calls: 0`; `new games: 0`; `candidate modifications: 0`; `production: OFF`.


## 24. Mission-outcome same-state safety execution (2026-09-20)

- Authorized execution of the new preregistration only: `20260920-v232-camouflage-v3-mission-outcome-safety-offline-r1`. It used exactly the six frozen same-state cutoffs from `20260920-v232-camouflage-v3-mission-outcome-safety-prereg-r1`.
- Execution completed offline with `API calls=0`, `new games=0`, `future_events_injected=0`, `candidate_modifications=0`, and production OFF. The closed full-game run was not used as a same-state baseline.
- All six states were valid. A clean-team rejection: `2/6`; B dirty-team approval: `0/6`; C clean-rejection mission-outcome cross-tab: `NOT_REACHED=2`; D dirty-approval cross-tab: empty; E same-state action disagreement: `2/6`, both reference APPROVE to candidate REJECT.
- Mission outcome cannot excuse either safety violation. The two rejected clean-team branches have `NOT_REACHED` because the evaluator stops at the vote boundary.
- Gate: `CANDIDATE_EFFECT_BUT_UNSAFE`. `full_game_effect_claim=NOT_ESTABLISHED`; this is a mechanism safety result only. No API, paid full-game, V4, candidate modification, or production enablement is allowed from this result.
- Execution artifacts: `results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-mission-outcome-safety-offline-r1/`.


## 25. Correction: mission-outcome safety run invalid corpus (2026-09-20)

- The first derived interpretation of `20260920-v232-camouflage-v3-mission-outcome-safety-offline-r1` as six valid states is invalidated. The preregistration state manifest freezes `strong=false` for all six states, but source historical decisions for `MO-S05` and `MO-S06` have `strong=true`.
- Per the frozen exclusion/gate rules, this is an `INVALID_CORPUS` condition. The corrected authoritative gate is `INVALID_CORPUS`; four states are conforming and two are invalid. The six-row ledger and its raw descriptive counts are retained for audit, but A/B/C/D/E are not valid safety denominators or a candidate-effect result for this run.
- `execution_correction.md` records the conflict; `safety_gate_pre_correction.json`, `report_pre_correction.md`, `summary_pre_correction.json`, and `candidate_safety_gate_pre_correction.json` preserve the superseded derived outputs. The preregistration itself was not edited retroactively.
- The corrected run used `API calls=0`, `new games=0`, `future_events_injected=0`, and `candidate_modifications=0`; production remains OFF; `full_game_effect_claim=NOT_ESTABLISHED`.
- Exact next allowed task: stop. Any corrected safety evaluation must use a new run ID and a separately frozen, separately authorized preregistration whose strong values are verified against the source before execution. Do not rerun automatically, add API/full-game, modify V3, or enable production.


## 26. Corrected V3 mission-outcome safety preregistration R2 (2026-09-21)

- New run ID: `20260921-v232-camouflage-v3-mission-outcome-safety-prereg-r2`. Status: `R2_PREREGISTRATION_READY`; `EXECUTION_NOT_AUTHORIZED`.
- The six intended states were reconstructed from authoritative source replay records. Policy-relevant fields were derived from those records rather than manually copied. MO-S05 and MO-S06 preserve source-record `strong=true`; the R1 manifest conflict is not carried forward.
- R1 `20260920-v232-camouflage-v3-mission-outcome-safety-offline-r1` remains permanently recorded as `INVALID_CORPUS`. No R1 descriptive metric is used as evidence, a threshold, or a safety/effectiveness/causal claim. R1 was not overwritten or repaired.
- The R2 preregistration adds a mandatory corpus-integrity preflight. Any source/hash/frozen-field mismatch, state substitution, reselection, expansion, or removal yields `INVALID_CORPUS` with `safety_claim=NOT_EVALUATED`; formal A/B/C/D/E metrics are not constructed and only a mismatch ledger is emitted.
- A/B/C/D/E denominators are risk-set specific. Mission outcome is evaluator-only; `NOT_REACHED`, `UNKNOWN`, and `NOT_APPLICABLE` handling is frozen in the metric schema. Policy outputs, historical trajectory events, same-state differences, and mission outcomes remain separate.
- Frozen boundaries: API calls=0, new games=0, candidate modifications=0, production changes=0, candidate default OFF, production OFF. No safety evaluation was executed.
- Artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v3-mission-outcome-safety-prereg-r2/`.
- Exact next task: stop and await separate execution authorization. Do not run the preflight/evaluation, add API/full-game, modify V3 or production, or change the frozen corpus/gate.


## 27. R2 corpus-integrity preflight (2026-09-21)

- Preflight run: `20260921-v232-camouflage-v3-mission-outcome-safety-preflight-r2`. Frozen preregistration: `20260921-v232-camouflage-v3-mission-outcome-safety-prereg-r2`.
- Result: `CORPUS_INTEGRITY_PASS`; valid states `6/6`; `safety_claim=NOT_YET_EVALUATED`; `formal_evaluation_authorized=false`; formal A/B/C/D/E evaluation was not run.
- All six authoritative source records resolved and matched source-record hashes, canonical serialized-state hashes, public-prefix hashes, frozen policy inputs, candidate-action provenance, historical evaluator-only mission metadata, and the source/hash manifest. MO-S05 and MO-S06 both verified `strong=true`.
- Public-prefix audits passed for all six states: each prefix ended at its recorded `after_seq` and excluded future sealed votes, future mission/proposal events, assassination outcomes, evaluator labels, and downstream ground truth.
- Boundaries: API calls=0, new games/full-game simulations=0, candidate modifications=0, production changes=0, production OFF. R1 remains permanently recorded as `INVALID_CORPUS` and was not modified.
- A first local preflight artifact had an internal PASS-flag serialization bug; it is preserved as `*_attempt1` and explicitly superseded by the authoritative result. It was not a source-corpus mismatch and no formal metric was computed.
- Exact next task: stop. The corpus pass does not authorize the formal safety evaluation; any execution requires separate explicit authorization, with the frozen R2 preregistration unchanged.

## 28. Formal corrected V3 mission-outcome safety evaluation R2 (2026-09-21)

- Authorized offline evaluation run: `20260921-v232-camouflage-v3-mission-outcome-safety-offline-r2`, using only frozen R2 preregistration `20260921-v232-camouflage-v3-mission-outcome-safety-prereg-r2`, its six-state manifest, authoritative source records, and successful preflight `20260921-v232-camouflage-v3-mission-outcome-safety-preflight-r2`.
- The preflight dependency was reverified as `CORPUS_INTEGRITY_PASS`, valid states `6/6`, with no mismatch. Superseded `*_attempt1` artifacts were not used as evaluation evidence. The frozen R2 preregistration and corpus membership were not changed.
- Preregistered metrics: A clean-team rejection `2/4` (states `MO-S02`, `MO-S03`); B dirty-team approval `0/2`; C clean-rejection evaluator cross-tab `NOT_REACHED=2`; D dirty-approval cross-tab `{}` and `NOT_APPLICABLE` because B=0; E same-state action disagreement `2/6` (both `APPROVE -> REJECT`). Risk-set denominators are preserved.
- Frozen safety gate: `FAIL` because A>0. Safety claim is limited to `SAFETY_FAIL` for the preregistered mechanism safety contract. This is not an effectiveness, causal, or full-game claim; `full_game_effect_claim=NOT_ESTABLISHED` and the earlier full-game run remains `CLOSED`.
- Evidence layers remain separate: frozen candidate policy outputs, authoritative historical trajectory provenance, same-state baseline-relative action differences, and evaluator-only historical mission metadata. Candidate branches rejected at the vote boundary are `NOT_REACHED`; no historical mission result was imputed or used to waive A.
- Boundaries: API calls=0, new games/full-game simulations=0, future events injected=0, candidate modifications=0, production changes=0; `production_enablement=false`; `candidate_default=OFF`; R1 remains permanently `INVALID_CORPUS` and was not modified. `docs/CODEX_HANDOFF.md` was appended after preflight; this append-only update is not a corpus input and explains the post-preflight handoff hash drift recorded in the evaluation result.
- Artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v3-mission-outcome-safety-offline-r2/safety_evaluation_result.json`, `safety_evaluation_report.md`, `safety_state_ledger.csv`, `metric_reconciliation.md`, and `evaluation_artifact_manifest.json`.
- Exact next task: stop. Do not modify V3, alter production, add API/full-game runs, redesign the contract, run V4, or append another evaluation without a new explicit authorization and new run ID.

## 29. Static V3 R2 safety-failure root-cause audit (2026-09-21)

- Static audit run: `20260921-v232-camouflage-v3-safety-root-cause-audit-r1`; authoritative input remains `20260921-v232-camouflage-v3-mission-outcome-safety-offline-r2` with `CORPUS_INTEGRITY=PASS`, `VALID_STATES=6/6`, `A=2/4`, `B=0/2`, `C=NOT_REACHED:2`, `D=NOT_APPLICABLE:{}`, `E=2/6`, and `SAFETY_GATE=FAIL`.
- Exact root cause: V3's intended noncritical `PUBLIC_CONSENSUS` disagreement branch overrides `mission_safety_vote=APPROVE` when public warnings on a clean proposed team make `public_consensus_vote=REJECT`. This is classified as intended behavior that violates the frozen safety contract (C), enabled by insufficient clean-team guard ordering (D), with the precise mechanism being the public-warning disagreement override (E). It is not an implementation bug or specification/implementation mismatch.
- MO-S02: one public accusation on the proposed team (`R1-025`) gives warning count 1; critical is false; `APPROVE` mission-safety versus `REJECT` public-consensus reaches `v232_candidate_v3.py:134-135` and returns `REJECT`.
- MO-S03: two public accusations (`R1-025`, `R2-068`) plus two rejected overlapping teams (`R2-052`, `R2-066`) give warning count 4; rejection count 2 remains below the critical threshold 4; the same `PUBLIC_CONSENSUS` branch returns `REJECT`.
- MO-S01/MO-S04 have no warnings and remain APPROVE. MO-S05/MO-S06 have Merlin-known evil on the team and remain REJECT. V3 consumes no numeric posterior/marginal/team-risk value; source belief values are audit provenance only.
- Static invariant review: `clean_team_predicate AND baseline=APPROVE => candidate=APPROVE` changes only MO-S02/MO-S03 to APPROVE, fixes both observed failures, leaves the other four frozen states unchanged, and creates no dirty-team approval in this six-state corpus. This is not a safety proof beyond the corpus. The literal baseline-dependent invariant is not a current V3 input; an equivalent clean-team guard would require a new candidate contract and preregistration.
- Boundaries: V3 unmodified, V4 unimplemented, API calls=0, new games=0, full-game validation not run, production changes=0, production remains OFF. No historical mission outcome, assassination result, Good win rate, future event, or R1 invalid-corpus metric was used to justify a policy decision.
- Artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v3-safety-root-cause-audit-r1/v3_safety_failure_root_cause.md`, `v3_decision_trace.csv`, `v3_predicate_comparison.csv`, `proposed_v4_invariant_review.md`, and `audit_manifest.json`.
- Exact next task: stop. Do not implement V4, modify V3, run any game/API/full-game validation, or enable production without a separately authorized and preregistered candidate.

## 30. V4 clean-team-guard preregistration (2026-09-21)

- New preregistration run: `20260921-v232-camouflage-v4-clean-team-guard-prereg-r1`; candidate `MerlinVoteCamouflageV4CleanTeamGuard`; status `V4_PREREGISTRATION_READY`.
- V3 remains unchanged and OFF. The only preregistered behavior change is an early guard using existing Merlin-legal inputs: `known_evil_on_team == ∅` and `mission_safety_vote=APPROVE` force `APPROVE` before the noncritical `PUBLIC_CONSENSUS` override. Scorer-only clean-team truth remains evaluator-only and cannot enter policy execution.
- Frozen expected deltas on the exact six R2 states: MO-S02 and MO-S03 must change `REJECT -> APPROVE`; MO-S01, MO-S04, MO-S05, and MO-S06 must remain unchanged. The expected state table and branch tests are frozen in the new preregistration artifacts.
- The preregistration preserves V3 warning extraction, thresholds, critical classification, strong handling, dirty-team behavior, public-consensus computation, legal inputs, and unrelated return paths. No baseline action, mission outcome, future event, evaluator label, Assassin state, hidden truth, or numeric belief is added to candidate input.
- Implementation and evaluation are not authorized. Boundaries: API calls=0, new games=0, full-game validation=0, V3 modifications=0, production changes=0, production OFF, V4 not implemented.
- Artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v4-clean-team-guard-prereg-r1/v4_preregistration.md`, `v4_candidate_spec.md`, `v4_expected_state_deltas.csv`, `v4_targeted_test_plan.md`, `v4_change_boundary.md`, `source_hash_manifest.json`, and `preregistration_manifest.json`.
- Exact next task: stop after preregistration. Do not implement V4, run tests/evaluation, call APIs, run games, modify V3, or enable production without a separate explicit authorization.


## 31. V4 clean-team-guard targeted validation (2026-09-21)

- Targeted run: 20260921-v232-camouflage-v4-clean-team-guard-targeted-r1; frozen preregistration: 20260921-v232-camouflage-v4-clean-team-guard-prereg-r1.
- MerlinVoteCamouflageV4CleanTeamGuard was implemented as a separate offline candidate module. avalon/eval/v2/v232_candidate_v3.py remains unchanged; its before/after SHA-256 is a686161f88d94111bb3a6066103dc112f023780dfc17ab0f2becd0261cb7f527. Production remains OFF.
- The only implementation change is the preregistered early guard: Merlin-legal known_evil_on_team == empty set and mission_safety_vote == APPROVE force APPROVE before the noncritical PUBLIC_CONSENSUS override. Warning extraction, thresholds, critical logic, strong behavior, dirty-team behavior, public-prefix boundary, and unrelated V3 paths remain frozen.
- Preregistration integrity, change-boundary audit, six branch tests, six-state exact validation, and policy leakage audit all PASS. Actions are exactly: MO-S01 APPROVE -> APPROVE; MO-S02 REJECT -> APPROVE; MO-S03 REJECT -> APPROVE; MO-S04 APPROVE -> APPROVE; MO-S05 REJECT -> REJECT; MO-S06 REJECT -> REJECT. Changed states are exactly {MO-S02, MO-S03}.
- V4 clean-team rejection violations are 0; V4 dirty-team approvals are 0. The existing deterministic regression suite passed 554/554 tests (PYTHONPATH=. .venv/bin/python -m pytest -q tests).
- TARGETED_GATE=PASS, but GENERAL_SAFETY_CLAIM=NOT_ESTABLISHED and FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED. This is a frozen-corpus targeted repair result, not a general safety, effectiveness, causal, or full-game result.
- Boundaries: API calls 0; new games/full-game validation 0; production changes 0; candidate default remains OFF. The frozen preregistration and all historical V3/R1/R2 artifacts were not overwritten.
- Artifacts: results/joint_belief_v2_3_2/20260921-v232-camouflage-v4-clean-team-guard-targeted-r1/v4_implementation_diff.md, v4_targeted_validation_result.json, v4_targeted_validation_report.md, v4_six_state_comparison.csv, v4_branch_test_results.csv, v4_regression_results.md, implementation_artifact_manifest.json.
- Exact next task: stop. Do not enable production, run full-game/API validation, modify V3, alter the frozen preregistration, or start another experiment without a new explicit authorization and run ID.

## 32. V4 expanded offline safety preregistration (2026-09-21)

- New run: `20260921-v232-camouflage-v4-expanded-safety-prereg-r1`. Status: `V4_EXPANDED_SAFETY_PREREGISTRATION_READY`; `CORPUS_FROZEN=YES`; `EXPANDED_EVALUATION=NOT_RUN`.
- Candidate and production boundaries remain frozen. `MerlinVoteCamouflageV4CleanTeamGuard` source is unchanged at SHA-256 `0d5442471454435e150319556e1f1674db7484668314bc92df27d20c2074ed22`; V3 remains unchanged at SHA-256 `a686161f88d94111bb3a6066103dc112f023780dfc17ab0f2becd0261cb7f527`; production is OFF and candidate default remains OFF.
- The frozen corpus is reconstructed exhaustively from 80 verified `*-joint_v2` source trajectories: 284 states from `20260918-v21-r7-live-75` and 257 from `20260918-v23-r2-live20`, for 541 unique Merlin vote states. The two complete development games containing MO-S01--MO-S06 are excluded; the six targeted states have primary gate weight zero and are not independent evidence. There were zero extraction exclusions and zero canonical duplicates.
- P0 `native_variant` is recorded as replay provenance only. The authoritative source-arm label is `joint_v2` for all 541 states; 327 P0 rows carry `joint_v2` and 214 carry `joint_v1` while matching the source legal-view and historical-action hashes. This distinction is frozen in every state row and does not enter policy inputs.
- The public-prefix boundary, source-record hashes, canonical state hashes, P0 verification dependencies, deterministic deduplication key, evaluator-only clean label, and exclusion rules are frozen. No V3/V4 policy action was generated; the manifest records `paired_policy_actions_generated=0`. Mission outcomes are not attached to policy inputs and cannot change membership or waive a gate.
- Preregistered artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v4-expanded-safety-prereg-r1/expanded_safety_preregistration.md`, `expanded_corpus_source_spec.md`, `expanded_corpus_extraction_spec.md`, `expanded_metric_schema.json`, `expanded_safety_gate.json`, `frozen_expanded_state_manifest.json`, `targeted_set_exclusion_manifest.json`, `source_hash_manifest.json` (written after this handoff append), and `corpus_composition_report.md`.
- Construction diagnostics `...-attempt1` and `...-attempt2` are preserved as non-evidence; the current run is authoritative. No API calls, new games, or full-game validation occurred.
- Exact next allowed task: a separate explicit authorization may execute only this unchanged frozen offline V3/V4 paired safety evaluation. Do not modify the corpus, metric schema, gate, V3, V4, production configuration, or add API/full-game work. Do not promote production from a preregistration or a future mechanism result.

## 33. V4 expanded corpus-integrity preflight (2026-09-21)

- Preflight run: `20260921-v232-camouflage-v4-expanded-safety-preflight-r1`; frozen preregistration: `20260921-v232-camouflage-v4-expanded-safety-prereg-r1`.
- Result: `EXPANDED_CORPUS_INTEGRITY=PASS`; `VALID_STATES=541/541`; `AUTHORITATIVE_ARM_JOINT_V2=541/541`; `HASH_MATCHES=541/541`; `EXPANDED_EVALUATION=NOT_RUN`; `formal_evaluation_authorized=false`.
- The preflight reconciled raw/final cardinality `541/0/541`, source resolution, source decision hashes, canonical serialized-state hashes, public-prefix hashes, warning provenance, legal Merlin information, deterministic deduplication/order, and all frozen strata. The current manifest is unchanged.
- MO-S01--MO-S06 and both development games are absent from the primary corpus. R1 `INVALID_CORPUS` artifacts and post-V4-created source states contribute no states. Candidate-output contamination is `NONE`; policy-prefix leakage is `NONE`.
- P0 `joint_v1`/`joint_v2` labels remain replay provenance only; authoritative source-arm resolution is `joint_v2` for all 541 states. No V3/V4 policy module was imported or called, and no candidate action, disagreement, guard, or gate result was generated.
- A first local preflight implementation attempt is preserved at `...expanded-safety-preflight-r1_attempt1` as non-evidence; it contained only checker serialization/label logic errors and did not alter the frozen corpus. The current PASS directory is authoritative.
- Artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v4-expanded-safety-preflight-r1/expanded_corpus_integrity_result.json`, `expanded_corpus_integrity_report.md`, `expanded_corpus_integrity_ledger.csv`, `expanded_source_semantics_audit.md`, `expanded_exclusion_reconciliation.md`, `expanded_hash_reconciliation.json`, and `expanded_preflight_artifact_manifest.json`.
- Boundaries: V3/V4 unchanged, API calls=0, new games=0, full-game validation=NO, production changes=0, production OFF. A successful corpus preflight does not authorize formal paired evaluation.
- Exact next allowed task: stop and await separate explicit authorization to execute the unchanged preregistered V3/V4 offline evaluation. Do not modify the frozen corpus, preregistration, metric schema, gate, V3, V4, or production.

