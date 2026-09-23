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

## 34. V4 expanded paired offline safety evaluation (2026-09-21)

- Authorized evaluation run: `20260921-v232-camouflage-v4-expanded-safety-offline-r1`; it used only the frozen preregistration `20260921-v232-camouflage-v4-expanded-safety-prereg-r1`, successful preflight `20260921-v232-camouflage-v4-expanded-safety-preflight-r1`, and the unchanged 541-state manifest.
- Paired execution completed on exactly 541 states: V3 actions `541`, V4 actions `541`; no downstream mission outcomes or future information entered either policy. The superseded preflight `*_attempt1` was not used.
- Metrics: A=`328`, A1=`0`; B outside policy guard=`213`, B1=`0`; absolute dirty-team B=`20/213`; C=`196`, C1=`196`, C2=`0`; D guard activations=`328` (`132` unchanged, `196` REJECT→APPROVE); E public-consensus protection=`267` (`196` V3 rejects, `267` V4 approves, `71` unchanged); F V3 dirty approvals=`20`; G V4 dirty approvals=`20`; new dirty approvals V4 vs V3=`0`.
- The frozen gate is `FAIL` because its absolute `B_dirty_team_approval` numerator must be zero and observed V4 numerator is `20`. This is not a new V4 regression: the same 20 approvals are present under V3, but the frozen gate still fails on the absolute safety metric. All clean-team, unexpected-disagreement, critical-path, leakage, and regression conditions pass.
- Deterministic regression suite: `554/554` passed. `POLICY_INFORMATION_LEAKAGE=NONE`. `GENERAL_SAFETY_CLAIM=NOT_ESTABLISHED`; `FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED`; production remains OFF and candidate default remains OFF.
- No API calls, new games, full-game validation, candidate modifications, V3 modifications, production changes, or mission-outcome waivers occurred. V4 is not production-approved by this result.
- Artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v4-expanded-safety-offline-r1/expanded_safety_evaluation_result.json`, `expanded_safety_evaluation_report.md`, `expanded_state_pair_ledger.csv`, `expanded_disagreement_ledger.csv`, `expanded_metric_reconciliation.md`, `expanded_regression_results.md`, and `expanded_evaluation_artifact_manifest.json`.
- Exact next allowed task: stop. Do not modify V4, reinterpret the absolute dirty-team gate, enable production, run full-game/API validation, or change the frozen corpus/preregistration. Any new candidate or contract requires a new run ID and preregistration.

## 35. Static V4 dirty-team approval root-cause audit (2026-09-21)

- Static audit run: `20260921-v232-camouflage-v4-expanded-safety-root-cause-audit-r1`; authoritative input is the unchanged ledger from `20260921-v232-camouflage-v4-expanded-safety-offline-r1` (`541` rows; ledger SHA-256 `d9e27a124e317f56d2d32f8f0fe0c85e0a033f110e6948b52f5ca3ee1ce62b9a`). No paired evaluation was rerun.
- Exact selection `known_evil_on_team != [] AND v4_action=APPROVE` yields `AUDIT_STATES=20`; all 20 also have `v3_action=APPROVE`. Every selected row has `mission_safety_vote=REJECT`, `public_consensus_vote=APPROVE`, `critical=0`, `warning_count=0`, `v3_mode=v4_mode=PUBLIC_CONSENSUS`, and an ineligible/unfired V4 clean-team guard.
- Root-cause partition reconciles exactly: `MISSION_SAFETY_APPROVES_DIRTY_TEAM=0`, `PUBLIC_CONSENSUS_OVERRIDES_DIRTY_REJECT=20`, `STRONG_OR_CRITICAL_OVERRIDE=0`, `POLICY_EVALUATOR_DIRTY_PREDICATE_MISMATCH=0`, `OTHER=0`. `mission_safety_vote` is computed as `not bool(known_evil_on_team)` in both modules, so it always rejects nonempty known-evil teams. The 20 approvals are inherited from the noncritical V3/V4 disagreement branch that returns `public_consensus_vote` when it is APPROVE; V4 did not change dirty-team control flow.
- The 193 dirty-team rejection controls all have `mission_safety_vote=REJECT` and `v4_action=REJECT`: 135 use noncritical `MISSION_SAFETY_DEFAULT` with `public_consensus_vote=REJECT`, and 58 use `CRITICAL_MISSION_SAFETY`. Predicate/guard representations match on all 541 rows.
- Static repairs are counterfactual only: hard dirty invariant `20/20`, mission-safety preservation `20/20`, and exact mechanism-specific branch repair `20/20`; each changes `20/541` frozen actions, `0` clean rows, `20` dirty rows, has zero overlap with the V4 clean-team guard, and leaves `0/213` absolute dirty approvals on this corpus.
- Scope classification: `V5_SCOPE=SYMMETRIC_CAMOUFLAGE_GUARD`; `V5_IMPLEMENTED=NO`. This is mechanism evidence on the frozen corpus only, not a general safety, full-game, or production result.
- Boundaries: V3 modified `NO`, V4 modified `NO`, API calls `0`, new games `0`, full-game validation `NO`, production changes `0`, production `OFF`.
- Artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v4-expanded-safety-root-cause-audit-r1/dirty_team_approval_root_cause.md`, `dirty_team_approval_trace.csv`, `dirty_team_failure_partition.csv`, `dirty_team_rejection_control_comparison.csv`, `v5_static_repair_comparison.md`, `audit_manifest.json`, and `STATUS.txt`.
- Exact next task: stop after this root-cause audit. Do not implement V5, modify V3/V4, rerun the 541-state evaluation, add API/full-game work, change the frozen corpus, or enable production without a new explicit authorization and run ID.

## 36. V5 symmetric safety-guard preregistration (2026-09-21)

- New preregistration run: `20260921-v232-camouflage-v5-symmetric-safety-guard-prereg-r1`; candidate `MerlinVoteCamouflageV5SymmetricSafetyGuard`; status `V5_PREREGISTRATION_READY`; implementation and evaluation are not authorized.
- The preregistered change is exactly one additional constraint layered on V4: `mission_safety_vote=REJECT` forces final REJECT and cannot be overridden by `PUBLIC_CONSENSUS`. The existing V4 clean-team guard remains first and unchanged; `mission_safety_vote` computation and all V4 warning, consensus, critical, strong, role, prefix, provenance, and unrelated return logic remain frozen.
- The static audit freezes exactly 20 expected V4→V5 changes, all `APPROVE→REJECT`, in `v5_expected_state_deltas.csv`. All other 521 V4 actions are expected unchanged; the existing 196 V3→V4 clean-team guard changes must remain preserved; no clean-team or `mission_safety_vote=APPROVE` state may change relative to V4.
- Preregistered expanded gate expectations: clean-team rejection violations `0`; dirty-team approvals `0/213`; expected V4→V5 disagreements `20`; unexpected disagreements `0`; V4 clean-team guard behavior preserved; no leakage; frozen corpus `541/541`; complete deterministic regression required. These are expectations, not observed V5 results.
- Claim boundaries remain `GENERAL_SAFETY_CLAIM=NOT_ESTABLISHED`, `FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED`, and `PRODUCTION=OFF` even if a future offline gate passes.
- Boundaries: V5 implemented `NO`, V4 modified `NO`, V3 modified `NO`, API calls `0`, new games `0`, full-game validation `NO`, production changes `0`, execution `NOT_AUTHORIZED`.
- Artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v5-symmetric-safety-guard-prereg-r1/v5_preregistration.md`, `v5_candidate_spec.md`, `v5_expected_state_deltas.csv`, `v5_targeted_test_plan.md`, `v5_change_boundary.md`, `v5_expanded_gate.json`, `source_hash_manifest.json`, `preregistration_manifest.json`, and `STATUS.txt`.
- Exact next task: stop after preregistration. Do not implement V5, modify V3/V4, call APIs, run games/full-game validation, alter the frozen corpus or gate, or enable production without separate execution authorization and a new run ID.

## 37. V5 symmetric safety-guard implementation and frozen offline validation (2026-09-21)

- Authorized implementation and validation run: `20260921-v232-camouflage-v5-symmetric-safety-offline-r7`, using the unchanged preregistration `20260921-v232-camouflage-v5-symmetric-safety-guard-prereg-r1`. The new module is `avalon/eval/v2/v232_candidate_v5.py`; V3 and V4 remain unmodified and production remains OFF.
- `V5_IMPLEMENTED=YES`; `PREREGISTRATION_INTEGRITY=PASS`; `CHANGE_BOUNDARY=PASS`; `BRANCH_TESTS=PASS`. The source-boundary audit confirms that V5 preserves V4's calculations, clean-team guard, and tail branches, adding only the preregistered `mission_safety_vote is False` symmetric guard and its provenance field.
- Exact dirty regression: all `20/20` preregistered V4 dirty-team approval states changed `APPROVE -> REJECT`; `dirty_unfixed=0`. The frozen six-state V4 development regression is preserved `6/6`; no six-state action changed relative to V4.
- Expanded paired evaluation is complete on the unchanged frozen corpus: `541/541` valid states; V4 dirty-team approvals `20/213`; V5 dirty-team approvals `0/213`; V4→V5 dirty approval fixes `20`; V4→V5 action deltas `20`, expected `20`, unexpected `0`; V3→V4 clean-team fixes preserved `196/196`; clean-APPROVE invariant violations `0`; REJECT-preservation invariant violations `0`; policy-information leakage rows `0`.
- Deterministic regression passed `554/554` tests. `V5_EXPANDED_SAFETY_GATE=PASS`. This establishes only the preregistered historical offline safety contract; `GENERAL_SAFETY_CLAIM=NOT_ESTABLISHED`, `FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED`, and `candidate_default=OFF`.
- Boundaries: API calls `0`; new games `0`; full-game validation `NO`; production changes `0`; V3 modified `NO`; V4 modified `NO`. Earlier validator harness attempts are retained in their separate `r1`–`r6` directories as non-authoritative diagnostics; `r7` is the authoritative completed run.
- Authoritative artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v5-symmetric-safety-offline-r7/v5_targeted_validation_result.json`, `v5_targeted_validation_report.md`, `v5_implementation_diff.md`, `v5_dirty_20_regression.csv`, `v5_six_state_regression.csv`, `v5_expanded_state_pair_ledger.csv`, `v5_expanded_disagreement_ledger.csv`, `v5_expanded_metric_reconciliation.md`, `v5_regression_results.md`, `v5_evaluation_artifact_manifest.json`, and `STATUS.txt`.
- Exact next task: stop after this offline V5 validation. Do not promote V5, modify V3/V4, alter the frozen corpus/preregistration/gate, add API or full-game work, create new games, or enable production without a new explicit authorization and run ID.

## 38. V5 matched full-game effectiveness preregistration (2026-09-21)

- New preregistration run: `20260921-v232-camouflage-v5-full-game-prereg-r1`; status `V5_FULL_GAME_PREREGISTRATION_READY`; execution is `NOT_AUTHORIZED`. No API calls, games, model responses, or full-game trajectories were generated.
- The control arm is resolved from authoritative historical run `20260920-v232-camouflage-v3-full-game-r1`: historical identifier `DeepSeek focal Merlin action policy`, implemented by the baseline arm's direct `LiveClient` focal Merlin path with no V3/V4/V5 vote override. Treatment is the unchanged `MerlinVoteCamouflageV5SymmetricSafetyGuard`; V5 source SHA-256 is frozen in `source_hash_manifest.json`.
- Archived baseline source hashes for `simulation.py`, `live.py`, `v232_full_game.py`, and the historical plan match the current tree. The historical LLM journal records DeepSeek model `deepseek-flash`, system prompt digest `819a222a...`, fingerprint `aeb56401ca74e127821c4f9126dcb669`, and `221` prior API attempts. The prior run did not archive a complete Settings/.env snapshot; timeout, JSON mode, thinking mode, retry settings, and raw prompt material are therefore frozen prospectively in the new source manifest and must be preflight-verified before any future call. The current-tree assembled good/evil prompt diagnostics are `2c8c8607...`/`aa145049...` and differ from the historical focal digest; mismatch must fail closed before the first call.
- Frozen sample: `MATCHED_WORLDS=50`, `ARMS=2`, `PLANNED_FULL_GAMES=100`; world IDs `FG-W001`–`FG-W050`, seeds `970001`–`970050`, P1 forced to Merlin, deterministic role/seat/initial-state assignments, and held-out population profiles. Odd worlds execute `BASELINE` then `V5`; even worlds execute `V5` then `BASELINE`. The world manifest and 100-row schedule passed preregistration integrity checks. Top-level seat/role metadata is explicitly labeled evaluator-only; only each world's initial public state is eligible for policy input.
- Primary endpoint is `GOOD_FULL_GAME_WIN` with paired WW/LL/LW/WL analysis, exact two-sided paired McNemar test, and the frozen Bonferroni-Wilson 95% paired-difference interval. `FULL_GAME_EFFECT_ESTABLISHED` requires all preregistered positive criteria and zero integrity failures; otherwise the result is `FULL_GAME_EFFECT_NOT_ESTABLISHED`; technical failure yields `EXPERIMENT_INVALID`.
- Secondary metrics, mutually exclusive terminal categories, prospective V5 safety telemetry, policy-to-engine consistency, legal-prefix boundaries, retry/accounting rules, and no-rerun technical-failure handling are frozen in the run artifacts. Historical V3 six-pair outcomes remain context only; V4 is not a primary arm.
- Boundaries: `V5_MODIFIED=NO`; `BASELINE_MODIFIED=NO`; API calls `0`; new games `0`; full-game evaluation `NOT_RUN`; production changes `0`; production `OFF`; `GENERAL_SAFETY_CLAIM=NOT_ESTABLISHED`; `FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED`.
- Artifacts: `results/joint_belief_v2_3_2/20260921-v232-camouflage-v5-full-game-prereg-r1/v5_full_game_preregistration.md`, `v5_full_game_world_manifest.json`, `v5_full_game_analysis_plan.md`, `v5_full_game_metric_schema.json`, `v5_full_game_execution_order.csv`, `v5_full_game_validity_rules.md`, `v5_full_game_safety_telemetry_spec.md`, `source_hash_manifest.json`, `preregistration_manifest.json`, `baseline_resolution.md`, and `STATUS.txt`.
- Exact next task: stop after preregistration. Do not execute the 100 games, call APIs, modify V5 or the baseline, reroll worlds, alter the primary gate, add a V4 arm, combine historical outcomes into the new sample, or enable production without a separate explicit execution authorization and pre-call configuration check.

## 39. V5 matched full-game zero-API pre-call integrity preflight (2026-09-22)

- Read-only preflight run: `20260922-v232-camouflage-v5-full-game-precall-r1`; target preregistration: `20260921-v232-camouflage-v5-full-game-prereg-r1`. No API calls, games, model responses, game objects, or trajectories were generated. The frozen preregistration directory was not modified.
- `PREREGISTRATION_INTEGRITY=PASS`: all 10 hashes in the frozen preregistration manifest match, including the eight required preregistration artifacts. `SOURCE_HASH_GATE=PASS`: all 17 current source hashes in the frozen source manifest match; V5 SHA-256 remains `a3bde3f71baa4a6f68108803ef99e6fd2768c81fde016b1f06984f2e669f18c4`, and the archived baseline source hashes still match.
- `PROMPT_HASH_GATE=FAIL`: historical raw assembled prompt material was not archived. The current runtime assembled GOOD/MERLIN prompt hash is `2c8c8607...` versus the frozen historical focal digest `819a222a...`; current EVIL/ASSASSIN is `aa145049...` versus frozen `eb48f1fe...`. Current raw prompt component hashes match their frozen component hashes, but that does not establish historical assembled-prompt equivalence. Expected hashes were not changed.
- `INFERENCE_CONFIG_GATE=FAIL` independently: current runtime model is `deepseek-v4-flash`, while the frozen contract requires `deepseek-flash`. The inspected endpoint, temperature, token limit, JSON mode, thinking mode, timeout, retry count/delay, and extra sampling parameters otherwise match the frozen contract.
- Structural gates passed: `WORLD_MANIFEST_GATE=PASS`, `VALID_WORLDS=50/50`, `PAIRING_GATE=PASS`, `VALID_PAIRS=50/50`, `EXECUTION_ORDER_GATE=PASS`, `TREATMENT_ISOLATION_GATE=PASS`, `PRIMARY_ANALYSIS_GATE=PASS`, `EFFECT_CLAIM_GATE=PASS`, `VALIDITY_RULE_GATE=PASS`, `SAFETY_TELEMETRY_GATE=PASS`, `API_ACCOUNTING_READINESS=PASS`, and `HISTORICAL_SAMPLE_ISOLATION=PASS`.
- Overall status: `PRECALL_INTEGRITY=FAIL`; `EXPERIMENT_EXECUTABLE=NO`; `FULL_GAME_EVALUATION=NOT_RUN`; `EXECUTION_AUTHORIZED=false`; `API_CALLS=0`; `NEW_GAMES=0`; `V5_MODIFIED=NO`; `BASELINE_MODIFIED=NO`; `PRODUCTION_CHANGES=0`; `PRODUCTION=OFF`.
- Artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-precall-r1/v5_full_game_precall_integrity_result.json`, `v5_full_game_precall_integrity_report.md`, `prompt_hash_reconciliation.json`, `source_hash_reconciliation.json`, `world_pair_integrity.csv`, `execution_order_reconciliation.csv`, `treatment_isolation_audit.md`, and `precall_artifact_manifest.json`.
- Exact next task: stop after this failed preflight. Do not call APIs, execute games, update expected prompt hashes, alter the frozen preregistration, or substitute the current model. Any correction requires a separately authorized new preregistration/run ID that resolves the prompt provenance and inference-model mismatch.

## 40. New R2 full-game preregistration with self-contained prompt archive (2026-09-22)

- New preregistration: `20260922-v232-camouflage-v5-full-game-prereg-r2`; status `V5_FULL_GAME_PREREGISTRATION_R2_READY`. R1 `20260921-v232-camouflage-v5-full-game-prereg-r1` and its failed preflight remain immutable. R2 execution is not authorized.
- R1 inheritance is clean: R1 had `API_CALLS=0`, `NEW_GAMES=0`, `MODEL_RESPONSES=0`, and no trajectories or outcomes. R2 reuses the exact 50 R1 world definitions and byte-identical execution-order CSV; canonical per-world definitions match `50/50`, with no outcome-conditioned regeneration. `WORLD_REUSE_FROM_R1=YES`; `OUTCOMES_OBSERVED_BEFORE_WORLD_REUSE=NO`.
- R2 freezes exact runtime model `MODEL_ID=deepseek-v4-flash`, provider `DeepSeek`, endpoint `https://api.deepseek.com`, temperature `0.0`, max tokens `2400`, JSON mode, disabled thinking, 60-second timeout, two retries with 2/4-second backoff capped at 30, null extra sampling parameters, and no tools. The model identifier is exact and is not aliased to R1's historical `deepseek-flash` label.
- Prompt archive is complete and self-contained: `archived_prompts/` contains actual canonical assembled GOOD/MERLIN and EVIL/ASSASSIN system prompts, action/voting components, public/social protocol, cognition/belief protocol, shared instructions, and fixed retry hints. GOOD and MERLIN share byte-identical material; EVIL and ASSASSIN share byte-identical material. `ARCHIVED_PROMPT_HASH_REPRODUCIBILITY=PASS`; runtime recomputation matches the archived assembled hashes before any provider call.
- Source/config manifest includes V5, baseline, engine/rules, non-Merlin/Assassin, cognition/memory, prompt-builder hashes, direct prompt-artifact hashes, world/schedule/analysis/validity/telemetry hashes, and the exact R2 inference contract. V5 SHA-256 remains `a3bde3f71baa4a6f68108803ef99e6fd2768c81fde016b1f06984f2e669f18c4`; `V5_MODIFIED=NO`; `BASELINE_MODIFIED=NO`.
- R2 retains the 50-pair primary endpoint `GOOD_FULL_GAME_WIN`, paired WW/LL/LW/WL analysis, exact paired McNemar test, Bonferroni-Wilson interval, effect-claim gate, validity rules, safety telemetry, information boundaries, and historical-sample exclusions. No V3, MO-S01--MO-S06, 541-state, V4, or V5 safety result enters the new primary sample.
- Boundaries: `MATCHED_WORLDS=50`; `PLANNED_FULL_GAMES=100`; `API_CALLS=0`; `NEW_GAMES=0`; `MODEL_RESPONSES=0`; `FULL_GAME_EVALUATION=NOT_RUN`; `GENERAL_SAFETY_CLAIM=NOT_ESTABLISHED`; `FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED`; `PRODUCTION=OFF`.
- Artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-prereg-r2/v5_full_game_preregistration.md`, `v5_full_game_world_manifest.json`, `v5_full_game_execution_order.csv`, `v5_full_game_analysis_plan.md`, `v5_full_game_metric_schema.json`, `v5_full_game_validity_rules.md`, `v5_full_game_safety_telemetry_spec.md`, `archived_prompts/`, `prompt_archive_manifest.json`, `prompt_canonicalization_spec.md`, `prompt_runtime_assembly_spec.md`, `prompt_hash_reproducibility.json`, `source_hash_manifest.json`, `r1_failure_inheritance_note.md`, and `preregistration_manifest.json`.
- Exact next task: stop after R2 preregistration. Run a new zero-API R2 pre-call integrity check before any game/API execution; do not execute the 100 games, modify V5/baseline, update archived hashes during preflight, or enable production.

## 41. R2 full-game zero-API pre-call integrity preflight (2026-09-22)

- Preflight run: `20260922-v232-camouflage-v5-full-game-precall-r2`; target preregistration: `20260922-v232-camouflage-v5-full-game-prereg-r2`. No API calls, games, Game instances, model responses, or trajectories were generated. R1 and R2 preregistration directories were not modified.
- The R2 frozen material is internally intact: `PREREGISTRATION_INTEGRITY=PASS`, `R1_IMMUTABILITY=PASS`, `SOURCE_HASH_GATE=PASS` (17/17 current source files), `ARCHIVED_PROMPT_HASH_GATE=PASS` (11/11 archive entries), `RUNTIME_PROMPT_EQUIVALENCE=PASS`, `DYNAMIC_CONTEXT_GATE=PASS`, and `INFERENCE_CONFIG_GATE=PASS` for exact local model `deepseek-v4-flash` and the frozen nonsecret settings.
- World and design checks pass: `WORLD_MANIFEST_GATE=PASS`, `VALID_WORLDS=50/50`, byte-identical R1 world reuse `50/50`, `PAIRING_GATE=PASS`, `VALID_PAIRS=50/50`, `EXECUTION_ORDER_GATE=PASS`, `ANALYSIS_PLAN_GATE=PASS`, `VALIDITY_RULE_GATE=PASS`, `API_ACCOUNTING_GATE=PASS`, and `HISTORICAL_SAMPLE_ISOLATION=PASS`.
- The preflight fails closed on the current executable harness. `TREATMENT_ISOLATION_GATE=FAIL` and `EXECUTION_HARNESS_GATE=FAIL` because `avalon/eval/v2/v232_full_game.py` and `tests/eval/test_v232_full_game.py` still import/assert the legacy V3 adapter, run six `960xxx` seeds, and do not consume the R2 V5 candidate, 50-world manifest, or 100-row schedule. `V5_SOURCE_GATE=PASS`; the V5 source remains unchanged and matches the R2 manifest, R1 declaration, and authoritative offline validation.
- `SAFETY_TELEMETRY_GATE=FAIL` and `POLICY_ENGINE_CONSISTENCY_INSTRUMENTATION=FAIL`: the R2 telemetry specification is complete, but the checked-in execution adapter has no runtime fields/comparison for `final_vote`, `clean_team_guard_fired`, `symmetric_guard_fired`, `engine_vote_event_id`, or `policy_engine_consistent`. The engine's sealed `TEAM_VOTE` event and decision `after_seq` hooks exist, but no required V5 comparator is implemented.
- Overall status: `PRECALL_INTEGRITY=FAIL`; `EXPERIMENT_EXECUTABLE=NO`; `FULL_GAME_EVALUATION=NOT_RUN`; `EXECUTION_AUTHORIZED=false`; `API_CALLS=0`; `NEW_GAMES=0`; `MODEL_RESPONSES=0`; `PRODUCTION_CHANGES=0`; `PRODUCTION=OFF`. Passing static archive/world/config checks does not override the failed harness gates.
- An empty planned destination was created/verified at `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-exec-r2/`; it contains no R1 result or execution output. Preflight artifacts are under `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-precall-r2/`, including the result/report, prompt/source/config reconciliations, world/schedule CSVs, treatment and destination audits, and `precall_artifact_manifest.json`.
- Exact next allowed task: stop. Do not repair R2 in place, call APIs, execute games, or reinterpret the failed preflight. A material correction requires separate authorization, a new implementation/preregistration run ID, and a new pre-call check that implements the R2 V5 harness and consistency telemetry.

## 42. New V5 full-game harness implementation (2026-09-22)

- New implementation run: `20260922-v232-camouflage-v5-full-game-harness-r1`. This is an offline engineering run only; no API calls, new games, engine `Game` instances, model responses, or trajectories were generated. R1/R2 preregistration and preflight artifacts, the legacy full-game adapter, V5, baseline sources, frozen worlds, and frozen schedule were not modified.
- Added `avalon/eval/v2/v232_full_game_v5.py`, a separate config-driven adapter. It consumes the external `FG-W001`--`FG-W050` world manifest and the 100-row execution-order CSV, preserves the frozen odd/even counterbalance, resolves `v232_candidate_v5.py` by source filename and candidate identity, keeps baseline ownership external, and requires the only behavioral arm difference to be Merlin voting policy. The future engine/live adapter is lazy and requires a validated plan plus an explicitly supplied executor.
- Added `tests/eval/test_v232_full_game_v5.py`; the deterministic offline harness tests pass `18/18`. Static validation parsed `50/50` worlds and `100/100` schedule rows, resolved both arms, rejected candidate/config and world/arm mismatches, rejected the retired seed namespace, and verified no legacy source selection for V5.
- Static gates: `HARNESS_IMPLEMENTATION=PASS`; `TREATMENT_ISOLATION_STATIC=PASS` with exact behavioral diff `{Merlin voting policy}`; `SAFETY_TELEMETRY_STATIC=PASS` for all 19 required fields; `POLICY_ENGINE_INSTRUMENTATION_STATIC=PASS` with exact host `after_seq` reconciliation, individual engine event IDs, and fail-closed missing/ambiguous matching.
- Source-boundary hashes: V5 remains `a3bde3f71baa4a6f68108803ef99e6fd2768c81fde016b1f06984f2e669f18c4`; the legacy adapter remains `a5633b042dfa2848d8fa30fc19cc32d830b0e85c79c9f13a95340f98ed7dbb8f`. The new module and tests are recorded in `harness_source_hash_manifest.json`.
- The existing suite was collected as `571` tests, while its historical old-suite reference is `554/554`; it was not executed in this implementation run because those tests instantiate engine games, which is prohibited here. No existing expectation was changed.
- Artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-harness-r1/v5_full_game_harness_implementation.md`, `v5_full_game_harness_diff.md`, `legacy_harness_dependency_audit.md`, `harness_static_validation_result.json`, `harness_static_validation_report.md`, `harness_test_results.md`, `treatment_isolation_static_audit.md`, `telemetry_schema.json`, `policy_engine_consistency_spec.md`, and `harness_source_hash_manifest.json`.
- Current status remains `R2_STATUS=PRECALL_INTEGRITY_FAIL`, `EXPERIMENT_EXECUTABLE=NO`, `R3_PREREGISTRATION_READY=NO`, `FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED`, and `PRODUCTION=OFF`. Exact next allowed task: prepare a new R3 matched full-game preregistration that freezes this harness hash, V5/baseline hashes, prompts, model/config, worlds, schedule, analysis, and telemetry; then run a separate zero-API R3 pre-call integrity check. Do not execute the 100 games or call APIs.

## 43. V5 harness regression qualification r1 preserved failure (2026-09-22)

- Qualification run: `20260922-v232-camouflage-v5-full-game-harness-regression-r1`. The complete deterministic suite passed `576/576` (`554/554` historical reference, `18/18` harness tests, and `4/4` other current deterministic tests), with `1,864` test-only engine instances, zero experimental games, zero prospective outcomes, zero API calls, and zero external model responses.
- Integrated resolution, treatment isolation, and telemetry schema passed. The run failed the policy-engine instrumentation gate because a uniquely resolved opposite engine vote raised before recording `policy_engine_consistent=false`. This qualification remains preserved as `HARNESS_REGRESSION_QUALIFICATION=FAIL`; no R3 readiness claim was made.
- Artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-harness-regression-r1/`. The defect was fixed in a separate harness revision; the r1 source hash and evidence remain immutable.

## 44. V5 harness regression qualification r2 (2026-09-22)

- Fresh qualification run: `20260922-v232-camouflage-v5-full-game-harness-regression-r2`; implementation revision: `20260922-v232-camouflage-v5-full-game-harness-r2`; harness SHA-256 `7b5d5cc88b331cd2b7b0824e78fcc9c8f255873baec42ddec270652e46cf926a`.
- `HARNESS_REGRESSION_QUALIFICATION=PASS`: the complete deterministic suite passed `576/576` (`554/554` historical reference, `18/18` harness tests, `4/4` other deterministic tests). `TEST_GAME_INSTANCES=1864`; these were deterministic fixtures only. `EXPERIMENTAL_GAMES=0`; `PROSPECTIVE_WORLD_OUTCOMES_GENERATED=0`; planned execution directory contamination is `NONE`.
- Isolation passed: `API_CALLS=0`, `EXTERNAL_MODEL_RESPONSES=0`, `MOCK_MODEL_RESPONSES=86` observed from loopback test servers, and no non-loopback socket attempts. V5 and baseline resolution, integrated treatment isolation, telemetry schema, and individual policy-engine consistency all pass, including `true` for matching votes, `false` for uniquely resolved mismatches, and fail-closed missing/ambiguous cases.
- V5 remains unchanged at `a3bde3f71baa4a6f68108803ef99e6fd2768c81fde016b1f06984f2e669f18c4`; the legacy baseline adapter remains unchanged at `a5633b042dfa2848d8fa30fc19cc32d830b0e85c79c9f13a95340f98ed7dbb8f`. Production, R2 status, and full-game claims remain unchanged: `R2_STATUS=PRECALL_INTEGRITY_FAIL`, `R3_PREREGISTRATION_READY=NO`, `FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED`, `PRODUCTION=OFF`.
- Artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-harness-regression-r2/` and implementation revision artifacts under `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-harness-r2/`.
- Exact next allowed task: prepare a new R3 preregistration freezing the qualified harness r2 hash, V5/baseline hashes, prompts, model/config, worlds, schedule, analysis, and telemetry; then run a separate zero-API R3 pre-call integrity check. Do not execute the 100 games, call APIs, or promote production.

## 45. V5 R3 prospective full-game preregistration (2026-09-22)

- New preregistration run: `20260922-v232-camouflage-v5-full-game-prereg-r3`; status `V5_FULL_GAME_PREREGISTRATION_R3_READY`. This is an infrastructure-corrected continuation of R2's prospective design. R1 and R2 remain immutable with `R1_STATUS=PRECALL_INTEGRITY_FAIL` and `R2_STATUS=PRECALL_INTEGRITY_FAIL`; no prospective outcomes were observed before reuse.
- R3 freezes qualified harness `avalon/eval/v2/v232_full_game_v5.py` at SHA-256 `7b5d5cc88b331cd2b7b0824e78fcc9c8f255873baec42ddec270652e46cf926a`, inherited from `20260922-v232-camouflage-v5-full-game-harness-regression-r2` with `HARNESS_QUALIFICATION=PASS`. Qualification evidence remains `576/576` deterministic tests (`554/554` legacy, `18/18` harness, `4/4` additional), `1,864` test Game instances, `0` experimental games, `0` prospective outcomes, `0` API calls, `0` external model responses, and `86` loopback mock responses. Qualification r1 remains a preserved failure because mismatched policy/engine votes were not retained as evidence.
- V5 remains unchanged at `a3bde3f71baa4a6f68108803ef99e6fd2768c81fde016b1f06984f2e669f18c4`; baseline remains `DeepSeekFocalMerlinActionPolicy` using direct `LiveClient` focal-Merlin decisions from `avalon/eval/v2/live.py` at `1dfe6387ef3c9bab20c663dd47a43d0d9f0b78f6af4ec11ca60d1423bb4b0826`, with no vote override. The legacy `v232_full_game.py` is recorded as historical provenance only and is not the active runner. `V5_MODIFIED=NO`, `BASELINE_MODIFIED=NO`, and production remains OFF.
- R3 reuses exactly the 50 R2 worlds `FG-W001`--`FG-W050` and the 100-row alternating schedule; copied world and schedule hashes match R2 byte-for-byte. `MATCHED_WORLDS=50`, `VALID_WORLDS=50/50`, `PLANNED_FULL_GAMES=100`, `WORLD_REUSE_FROM_R2=YES`, and `OUTCOMES_OBSERVED_BEFORE_REUSE=NO`.
- The exact model contract is `deepseek-v4-flash`; the complete R2 prompt archive is copied and rehashed. All 11 archived entries and both assembled role-system prompts reproduce. The qualified 19-field telemetry schema and individual policy-to-engine event instrumentation are frozen, including fail-closed missing/ambiguous resolution and retained mismatches.
- The R3 package preserves the paired `GOOD_FULL_GAME_WIN` endpoint, `WW`/`LL`/`LW`/`WL` classification, exact paired McNemar test at alpha `0.05`, Bonferroni-Wilson interval, effect gate, secondary definitions, validity/retry rules, information boundary, post-divergence pairing rule, and historical-data exclusions. A separate future zero-API pre-call run is required; this preregistration does not establish executability.
- Boundaries: `API_CALLS=0`; `EXPERIMENTAL_GAMES=0`; `EXTERNAL_MODEL_RESPONSES=0`; `PROSPECTIVE_WORLD_OUTCOMES_GENERATED=0`; `FULL_GAME_EVALUATION=NOT_RUN`; `EXPERIMENT_EXECUTABLE=NOT_YET_EVALUATED`; `EXECUTION=NOT_AUTHORIZED`; `GENERAL_SAFETY_CLAIM=NOT_ESTABLISHED`; `FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED`.
- Authoritative artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-prereg-r3/` including `v5_full_game_preregistration.md`, frozen world/schedule, analysis/metric/validity/safety specifications, `archived_prompts/`, prompt manifests/specifications, `source_hash_manifest.json`, `r3_harness_config.json`, `telemetry_schema.json`, `reuse_equivalence.json`, `harness_qualification_inheritance_note.md`, `r2_failure_inheritance_note.md`, `preregistration_manifest.json`, and `preregistration_static_validation_result.json`.
- A partial local assembly attempt is preserved as `20260922-v232-camouflage-v5-full-game-prereg-r3_attempt1/` and is non-evidence; the authoritative R3 directory above passed static artifact validation. No R3 execution destination was created.
- Exact next allowed task: run a separate zero-API R3 pre-call integrity check against the frozen package. Do not execute games, call APIs, generate model responses, modify V5/baseline, change worlds/schedule/prompts/analysis, or promote production.

## 46. R3 final zero-API pre-call integrity check (2026-09-22)

- Final pre-call run: `20260922-v232-camouflage-v5-full-game-precall-r3`; target `20260922-v232-camouflage-v5-full-game-prereg-r3`. `PRECALL_INTEGRITY=PASS`; `EXPERIMENT_EXECUTABLE=YES`; `EXECUTION_AUTHORIZED=false`; `FULL_GAME_EVALUATION=NOT_RUN`.
- Frozen R3 integrity passed: `PREREGISTRATION_INTEGRITY=PASS`; `R1_IMMUTABILITY=PASS`; `R2_IMMUTABILITY=PASS`; qualified harness hash gate `PASS` for `7b5d5cc88b331cd2b7b0824e78fcc9c8f255873baec42ddec270652e46cf926a`; `LEGACY_V3_HARNESS_ACTIVE=NO`; V5 and baseline source/resolution gates `PASS`; treatment isolation `PASS` with only `{Merlin voting policy}` differing.
- Runtime compatibility passed without a provider call: all 11 archived prompt hashes and both assembled prompts matched; `DYNAMIC_CONTEXT_GATE=PASS`; exact `deepseek-v4-flash` inference configuration matched; world manifest `50/50`; pairing `50/50`; execution schedule `100/100`; no six-seed or generated-schedule fallback.
- Qualified 19-field safety telemetry and policy-to-engine instrumentation passed. In-memory synthetic recorder checks retained matching and mismatching event rows and failed closed for missing/ambiguous event resolution. Safety invariant instrumentation, analysis, validity, API accounting, and historical-sample isolation all passed.
- The empty execution destination `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-exec-r3/` passed `EXECUTION_DESTINATION_GATE=PASS` with `EXPERIMENT_DIRECTORY_CONTAMINATION=NONE`.
- Boundaries remain: `API_CALLS=0`; `EXPERIMENTAL_GAMES=0`; `EXTERNAL_MODEL_RESPONSES=0`; `PROSPECTIVE_WORLD_OUTCOMES_GENERATED=0`; no Game object, policy vote, model response, or trajectory was generated. Production remains OFF and no safety/effect claim is established.
- Artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-precall-r3/`, including `r3_precall_integrity_result.json`, `r3_precall_integrity_report.md`, source/candidate/harness/prompt/inference reconciliations, world/pair and execution-order ledgers, treatment/telemetry/instrumentation audits, execution-destination audit, and `r3_precall_artifact_manifest.json`.
- Three partial local preflight assembly attempts are preserved as `20260922-v232-camouflage-v5-full-game-precall-r3_attempt1/`, `..._attempt2/`, and `..._attempt3/`; they contain no provider calls, games, responses, or trajectories and are non-authoritative. The authoritative result is the PASS directory above.
- Exact next allowed task: stop. Execution still requires a separate explicit authorization. Do not call APIs, execute the 100 games, generate trajectories, alter the R3 preregistration, change V5/baseline, or promote production.

## 47. R3 frozen prospective full-game execution (2026-09-22)

- The user explicitly authorized execution of the frozen R3 prospective run `20260922-v232-camouflage-v5-full-game-prereg-r3` after the authoritative pre-call `20260922-v232-camouflage-v5-full-game-precall-r3` passed. The read-only execution-start freeze revalidated the PASS pre-call result, 50 frozen worlds, 100-row schedule, qualified harness, V5, baseline transport, prompt builders, and exact `deepseek-v4-flash` settings before the first provider call.
- The frozen schedule stopped after rows 1 and 2 under the inherited first-technical-failure rule. `FG-W001-BASELINE` is one `VALID_COMPLETED_GAME`. `FG-W001-V5` reached a legal terminal state but is `NONRETRYABLE_TECHNICAL_FAILURE`: V5 decision `FG-W001-V5-R2-A1-46` matched two individual engine vote events (`R2-047` and `R2-061`) during exact telemetry resolution. The qualified resolver failed closed; this is an ambiguous/unresolved telemetry failure, with `POLICY_ENGINE_MISMATCHES=0`.
- No rerun, seed reroll, arm replacement, reserve world, schedule continuation, reordering, or favorable-loss substitution occurred. The remaining 98 scheduled rows were not executed. The raw ledger is locked with `RAW_LEDGER_LOCKED=YES`; paired primary and secondary analyses were not run. `EXPERIMENT_INTEGRITY=FAIL`, `FULL_GAME_EVALUATION=INVALID_TECHNICAL_FAILURE`, `FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED`, and `PRODUCTION=OFF`.
- Operational accounting at stop: `API_ATTEMPTS=30`, accepted model responses `30`, retries `0`, unknown-usage attempts `0`, conservative peak-rate estimate/charge `¥0.20128016`, safety-invariant violations `0`, and technical failures `1`. `VALID_COMPLETED_GAMES=1/100`; the paired denominator is `0/50` because the V5 arm is invalid. V5 and baseline source hashes remained frozen; `V5_MODIFIED=NO`, `BASELINE_MODIFIED=NO`, and production changes are `0`.
- Authoritative execution artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-exec-r3/`, including `r3_raw_execution_manifest.json` (SHA-256 `b38da7092254a09a5b42aea0e23643d2545d91ffec2ffc2c1f270a46265a6dcf`), `r3_full_game_evaluation_result.json`, `r3_full_game_evaluation_report.md`, `r3_primary_analysis.md`, `r3_secondary_analysis.md`, `r3_metric_reconciliation.md`, `r3_experiment_integrity_report.md`, raw game archives, API journal/accounting, safety telemetry, policy-engine reconciliation, technical-failure ledger, and `r3_evaluation_artifact_manifest.json`.
- Exact next allowed task: stop this R3 run. Do not rerun or resume its schedule, repair the ambiguous telemetry in place, replace the missing 98 rows, compute partial effectiveness statistics, alter V5/baseline/worlds/schedule/prompts/model, enable production, or claim a full-game effect. Any further execution requires a new explicitly authorized preregistration and pre-call integrity run.

## 48. R3 resolver equivalence check (2026-09-22)

- Offline engineering run: `20260922-v232-camouflage-v5-harness-equivalence-r1`. It replayed the retained `FG-W001-V5` accepted model-response tape (13 responses), the same decoded population/action tape, seed `970001`, frozen world `FG-W001`, and V5 arm through an old no-resolver-failure path and an isolated coordinate-aware resolver copy. Provider calls were `0`; the current qualified R3 source was not modified.
- Equivalence status: `PASS`. Actions, full event/state-transition log, public transcript, terminal outcome, normalized replay record, and normalized trace were identical. Both paths consumed all 13 mocked model responses and all action rows. The only differences were provenance/resolver metadata and runtime timing fields.
- The old path reproduces the R3 ambiguity for decision `FG-W001-V5-R2-A1-46`, with candidates `R2-047` and `R2-061`, and fails closed. The isolated patch adds the already-recorded `(round, attempt)` coordinate to event matching and selects `R2-047`; it does not alter action selection or engine transitions. Patched copy SHA-256: `1b7d10cfc7d4ffc86a3dbcd8fe4661b1757228e9bbeb04186f83ff131b946d11`.
- This result is engineering equivalence evidence only. It does not repair, reopen, or add observations to the invalid R3 full-game run. Production remains OFF; V5 and the qualified source remain unchanged. Artifacts are under `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-harness-equivalence-r1/`; three zero-call assembly attempts are preserved as `_attempt1`, `_attempt2`, and `_attempt3`.
- Exact next allowed task: stop after equivalence. Do not apply the copied patch to the qualified source, resume the R3 schedule, rerun the failed pair, or make a full-game/effect claim. Any live/full-game use of the coordinate-aware resolver requires a new source revision, targeted qualification, preregistration, and zero-API pre-call gate.

## 49. R4 resolver technical qualification and pre-call (2026-09-22)

- New isolated source revision: `20260922-v232-camouflage-v5-harness-r4`. The only source change is a seven-line resolver insertion that filters matching engine `VOTE` events by frozen `(round, proposal-attempt)` coordinates before the uniqueness check. The R3-qualified source remains unchanged at SHA-256 `7b5d5cc88b331cd2b7b0824e78fcc9c8f255873baec42ddec270652e46cf926a`; the R4 copy is SHA-256 `1b7d10cfc7d4ffc86a3dbcd8fe4661b1757228e9bbeb04186f83ff131b946d11`.
- R4 technical qualification is `PASS`: 8/8 targeted resolver checks passed. The old resolver still fails closed on the retained `R2-047`/`R2-061` ambiguity; the coordinate-aware copy selects `R2-047`, preserves exact decision cursors, fails closed on missing/mismatched coordinates, and retains uniquely resolved policy-engine mismatches. The inherited deterministic equivalence remains `PASS` with 0 provider calls and identical actions, state transitions, public transcript, terminal outcome, normalized record, and normalized trace.
- New preregistration: `20260922-v232-camouflage-v5-full-game-prereg-r4`, status `V5_FULL_GAME_PREREGISTRATION_R4_READY`. Candidate, baseline, treatment contrast, prompts, model/configuration, world schedule, seed schedule, RNG, agent policy, engine semantics, analysis, validity, and telemetry are frozen unchanged. The R3 world/seed definitions are reused for a technical-repair schedule with `R3_OUTCOMES_CARRIED_FORWARD=NO`; R3's one valid baseline row and one invalid V5 row are excluded from every R4 denominator and analysis. No world was selected from an outcome.
- New zero-API pre-call: `20260922-v232-camouflage-v5-full-game-precall-r4`; `PRECALL_INTEGRITY=PASS`, `EXPERIMENT_EXECUTABLE=YES` structurally, `EXECUTION_AUTHORIZED=false`. All 21 gates passed, including R4 source hash, R3 source immutability, candidate/baseline, prompt, inference, world/schedule, treatment isolation, telemetry, R3 invalid-row exclusion, and empty execution destination. `API_CALLS=0`, `EXPERIMENTAL_GAMES=0`, `EXTERNAL_MODEL_RESPONSES=0`, `PROSPECTIVE_WORLD_OUTCOMES_GENERATED=0`; production remains OFF.
- Authoritative artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-harness-r4/`, `.../20260922-v232-camouflage-v5-full-game-prereg-r4/`, `.../20260922-v232-camouflage-v5-full-game-precall-r4/`; each artifact manifest is internally consistent. The first failed prereg assembly is preserved at `20260922-v232-camouflage-v5-full-game-prereg-r4_attempt1/` and is non-authoritative.
- Exact next allowed task: stop and await separate explicit authorization to execute the new R4 prospective run. If authorized, execute only the frozen R4 package from its empty destination, record all API/accounting/telemetry artifacts, and stop on the first technical failure. Do not resume or repair R3, include R3 rows, alter the R4 schedule/prompts/model/candidate/baseline, or promote production; no effectiveness claim is established.

## 50. R4 frozen prospective full-game execution stopped on first technical failure (2026-09-22)

- The user explicitly authorized the frozen R4 100-row run after the R4 zero-API pre-call passed. The execution began from the verified empty destination with the isolated coordinate-aware harness at SHA-256 `1b7d10cfc7d4ffc86a3dbcd8fe4661b1757228e9bbeb04186f83ff131b946d11`; V5, baseline, model/configuration, prompts, worlds, seeds, schedule, and production boundaries remained frozen. R3 rows/outcomes were excluded.
- The first 69 scheduled rows are `VALID_COMPLETED_GAME`. Row 70, `FG-W035-V5`, is `NONRETRYABLE_TECHNICAL_FAILURE`: recorded provider error `LLMError: connection_error`, `status=failed`, `game_status_not_completed`, and `terminal_category:game_not_completed`. That row made 15 provider attempts, 4 retries, 10 accepted responses, and 5 unknown-usage attempts. The first-technical-failure rule halted the schedule; rows 71--100 were not executed.
- Raw execution is locked: `RAW_LEDGER_LOCKED=YES`; 70/100 rows observed; 69/100 valid games; 34/50 complete valid pairs plus one incomplete `FG-W035` pair; technical failures `1`; policy-engine mismatches `0`; safety-invariant violations `0`; API attempts `1400`; accepted/successful model responses `1373`; retries `35`; unknown-usage attempts `27`; conservative peak-rate estimate/charge `¥10.228406`; production remains `OFF`.
- `EXPERIMENT_INTEGRITY=FAIL`, `FULL_GAME_EVALUATION=INVALID_TECHNICAL_FAILURE`, and `FULL_GAME_EFFECT_CLAIM=NOT_ESTABLISHED`. The preregistered primary and secondary analyses were not run; complete pairs are not a partial effectiveness sample. No rerun, replacement, reroll, continuation, arm substitution, or favorable-loss substitution occurred.
- Authoritative run artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-exec-r4/`; raw manifest SHA-256 `491aa610d9bd45c1c333078ff77ad922f4d96d6d995d560b87db74427a5790ed`; result, integrity, evaluation, metric, primary, secondary, and artifact-manifest reports are in the same directory. Raw manifest verification is `81/81`; evaluation artifact-manifest verification is `89/89`.
- Exact next allowed task: stop R4. Any further live execution requires a new run ID/preregistration and a new zero-API pre-call that addresses the transport failure, followed by separate execution authorization. Do not resume or repair R4 in place, fill the missing 30 rows, compute partial effectiveness statistics, alter the R4 package, or promote production.

## 51. R5 transport-resilience preregistration and zero-API qualification (2026-09-22)

- New R5 preregistration: `20260922-v232-camouflage-v5-full-game-prereg-r5`. R4 remains `INVALID_TECHNICAL_FAILURE`; its 70 observed rows, responses, trajectories, and outcomes are excluded from every R5 denominator. The same 50 world definitions and 100-row schedule are reused as fixed design inputs only.
- Candidate, baseline, treatment contrast, prompts, `joint_v2`, model identity `deepseek-v4-flash`, endpoint, decoder, engine semantics, RNG, legal menus, telemetry, and statistical gates remain unchanged. The only new R5 execution contract is transport resilience: 90-second timeout, up to 4 retries after the initial attempt, 2/4/8/16-second backoff capped at 30 seconds, with all attempts and unknown usage persisted. No fallback provider, alias, action repair, or outcome-dependent rerun is permitted.
- Offline transport qualification: `20260922-v232-camouflage-v5-transport-qualification-r1`; `PASS`. Four consecutive loopback connection errors recover on the fifth attempt; five consecutive errors fail closed after four retries; retry context digest is stable; unknown usage is accounted; loopback-only. Provider API calls `0`, external model responses `0`, prospective games `0`. Targeted deterministic suites `35/35` passed.
- R5 zero-API pre-call: `20260922-v232-camouflage-v5-full-game-precall-r5`; `PRECALL_INTEGRITY=PASS`; `EXPERIMENT_EXECUTABLE=YES`; `EXECUTION_AUTHORIZED=false`. All 23 gates passed, including R4 harness immutability, R4 outcome exclusion, transport qualification, prompt/source/world/schedule/treatment gates, R5 runner compilation/plan validation, and an empty R5 execution destination. API calls, games, responses, and trajectories remain `0`; production remains `OFF`.
- Authoritative artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-prereg-r5/`, `.../20260922-v232-camouflage-v5-transport-qualification-r1/`, and `.../20260922-v232-camouflage-v5-full-game-precall-r5/`. Preregistration manifest verification is `41/41`; transport artifact verification is `7/7`; pre-call artifact verification is `11/11`.
- Exact next allowed task: obtain separate explicit authorization for the new R5 100-row live execution, then run only the frozen package from `20260922-v232-camouflage-v5-full-game-exec-r5` and stop at the first technical failure. Do not resume R4, include R4 outcomes, change the R5 transport contract after pre-call, compute partial effectiveness statistics, or promote production.

## 52. R5 frozen prospective full-game execution and analysis (2026-09-23)

- The user explicitly authorized continuation of the frozen R5 100-row run after the R5 pre-call passed. The execution-start record preserved the empty destination, explicit authorization, frozen `deepseek-v4-flash` contract, R5 transport policy, candidate/baseline/harness hashes, and `production=OFF` before the first provider call. The separate offline UI/`OfflineClient` repair was not part of the R5 source package and did not alter these frozen hashes.
- All `100/100` scheduled rows completed as `VALID_COMPLETED_GAME`: `50/50` baseline and `50/50` V5 games, `50/50` complete valid matched pairs, zero technical failures, zero policy-engine mismatches, and zero safety-invariant violations. R4 rows/outcomes remained excluded. The raw ledger is locked with raw-manifest SHA-256 `c605ac14dd0f99a16d3ec134b4cbb41507010d802b8210ffb8c5c6760177cc69`.
- Operational accounting at completion: `1983` API attempts, `1945` accepted model responses, `47` retries, `38` unknown-usage attempts, reported-usage estimate `¥4.15181774`, and conservative peak-rate estimate/charge `¥10.55700548`. No provider fallback, action repair, rerun, seed reroll, arm replacement, schedule continuation, or favorable-loss substitution occurred.
- The preregistered primary analysis ran after the raw lock. Baseline Good wins were `0/50`; V5 Good wins were `0/50`; pair classes were `WW=0`, `LL=50`, `LW=0`, `WL=0`; paired contrast `(LW-WL)/50=0`; exact two-sided paired McNemar `p=1.0`; frozen Bonferroni-Wilson paired-difference interval `[-0.091303733, 0.091303733]`. The fixed result is `FULL_GAME_EFFECT_NOT_ESTABLISHED`; no full-game effectiveness claim is established and production remains OFF.
- Descriptive secondary results were also analyzed after the lock: each arm had `48` assassination entries with `48` Merlin hits and `0` conditional survivals, plus `2` three-failed-mission terminals; each arm had `148` successful and `18` failed quests. V5 telemetry had `357` focal Merlin decisions, `212` approvals, `145` rejections, `0` clean-team rejections, `0` dirty-team approvals, `357/357` consistent policy-to-engine rows, and zero safety-invariant violations.
- Authoritative artifacts: `results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-exec-r5/`, including `r5_full_game_evaluation_result.json`, `r5_primary_analysis.md`, `r5_secondary_analysis.md`, `r5_metric_reconciliation.md`, `r5_experiment_integrity_report.md`, `r5_evaluation_artifact_manifest.json`, and the locked raw ledgers/journal. The artifact manifest verifies `119` files with zero hash mismatches.
- Exact next allowed task: review this completed R5 result; do not promote V5 or treat the zero-win paired outcome as a positive effectiveness result. Any new live execution or policy change requires a new frozen preregistration, zero-API pre-call, and separate explicit authorization.

## 53. Local browser live API and explicit V5 trial mode (2026-09-23)

- At the user's request, the browser backend now supports an explicit local `--mode live --merlin-policy v5` mode. Live play uses the existing configured `ChatClient`; only an AI Merlin's team vote is replaced by the frozen V5 vote function using that Merlin's legal view and public Chronicle observations. Other AI actions and human votes retain their existing paths. Candidate, baseline research source, engine rules, legal menus, and sealed voting were not changed.
- The CLI defaults remain `--mode offline --merlin-policy baseline`; offline mode rejects V5. The live CLI checks local model configuration before listening, and the session endpoint/UI expose the selected mode. A separate local server was started on port `8766` with the built browser assets, while the existing offline server on `8765` remained active. The `8766` session returned `mode=live`, `merlin_vote_policy=v5`, and `phase=START`; the browser start screen rendered the same selection.
- Targeted backend checks passed `67` tests with `2` known long-running cases deselected; the browser build and diff whitespace check passed. No provider request or game was initiated by this setup, so end-to-end paid-call gameplay is not yet verified. Interactive games in this mode are local trial play, not additions to the locked R5 evaluation or evidence of V5 effectiveness.
- R5's `FULL_GAME_EFFECT_NOT_ESTABLISHED` conclusion and `PRODUCTION=OFF` remain unchanged. Do not make V5 the default or reinterpret local trial games as a prospective research sample. Any new controlled evaluation still requires its own frozen design, zero-API pre-call, and explicit execution authorization.

## 54. First live browser AI action failure diagnostic (2026-09-23)

- In the local `8766` trial, the AI leader's team proposal committed, then the first DISCUSSION advance returned `invalid_plan`. The locked public prefix contained only START, LEADER, DIRECTION, ROUND, RESOLVE_REFRESH, and TEAM; no failed discussion action was published. This path is `Agent.prepare` validation and occurs before the V5 Merlin voting branch. The existing process had no per-attempt response/validator journal, so the exact reason for that historical failure cannot be recovered.
- A bounded separate DeepSeek probe of a reconstructed public discussion state reproduced `invalid_plan: Invalid plan keys`: one response included an extra `recommended_action.discussion_kind` field. Another probe produced the required shape and passed. This supports intermittent model schema drift but does not prove the historical failure used that same extra field. A user-facing restart of the paused AI turn later accepted one legal public discussion action and advanced the session without modifying the earlier TEAM event.
- Live browser backends launched after this code revision write owner-only local JSONL failure metadata under `~/.avalon/diagnostics/`. Records include phase, decision kind, acting seat, legal actions, retry index, allowlisted validation reason, provider response ID/hash, finish reason, and reported usage; they exclude response text, prompts, credentials, roles, and private plans. The running `8766` process predates this change and is preserved with its active match; it will not acquire diagnostics until a future restart.
- The extra-field regression remains rejected with no action repair, no public event, and no revision increment. Relevant fake-client/backend suites passed `64` tests with `2` known long-running cases deselected; `git diff --check` and compilation passed. This is engineering diagnosis and local observability only. R5 research results, frozen evaluation sources, V5 candidate source, and `PRODUCTION=OFF` are unchanged. Do not use local trial actions as controlled evaluation evidence.

## 55. P5 PASS followed by AI validation pause (2026-09-23)

- A later local trial on the still-running pre-diagnostic `8766` process had public seq 6 TEAM by P5, seq 7 PASS by P5, then `invalid_plan` while P4 was next in DISCUSSION. The PASS was legally committed; the rejected P4 action produced no public event. The failed response and exact validation reason were not retained by that old process, so the earlier extra `discussion_kind` probe is not proof of this failure's field-level cause.
- The built-in `restart_round` recovery retained the P5 PASS prefix and accepted seq 8 PASS by P4; the active match reached revision 9 with P3 next. A zero-API regression at `tests/test_live_discussion_pass.py` covered the P5 proposal/PASS to P4 handoff with the modern cognition envelope across four P4 roles; all variants passed, confirming legal menu, event context, and action order. No deterministic PASS transition fault was found.
- A separate diagnostic-ready live/V5 server started on `127.0.0.1:8767` at `phase=START`; its owner-only log is `~/.avalon/diagnostics/live-ai-b79212d80251416c.jsonl` (directory mode `0700`, file mode `0600`). It has made no provider calls. The `8766` match is preserved. Neither local trial is part of R5 or a controlled effectiveness sample; production remains OFF.

## 56. Repeated live-browser PASS diagnosis and accepted-action telemetry (2026-09-23)

- The preserved `8766` match reached revision `11`, `DISCUSSION`, with human P1 next. Its public Chronicle `~/.avalon/chronicles/f4e0b787717144b7884af834c4840d96.jsonl` contains authoritative seq `7`--`10` `PASS` actions from AI P5, P4, P3, and P2; every event has `resolve_after=3` and `resolve_cost=0`. These were not a stale UI rendering or the zero-Resolve forced-PASS branch. P6 had not acted. V5 only affects Merlin team voting, not discussion actions.
- The existing decoder executes `discussion.kind=PASS` even when a validated plan also contains non-null `social`; that draft is not published. A deterministic fake-client test reproduced this accepted-but-unused draft. The old `8766` process has no accepted-response journal, so its four plans' draft presence, retries, and exact model rationales are unknown; do not attribute all four historical PASS actions to that mismatch.
- A separate bounded local live/V5 reproduction on freshly launched `8767` used six seats and seed `34` (P5 leader, counterclockwise order). AI P5's first discussion response failed validation with `Invalid performance keys`; its retry committed seq `7` `PASS` with `plan_social_present=true`. P4 committed seq `8` `PASS` without a draft or retry. P3 first failed `Invalid resource action`, then committed seq `9` `PASS` without a draft. P2's three attempts failed `Invalid plan keys`, `Invalid ranking`, and `Invalid cognition response`; no P2 event committed. The new match is paused at revision `6`, `DISCUSSION`, P2 next. This is local diagnosis, not a matched reproduction of the old game or R5 evidence.
- New live-only accepted-action diagnostics record only committed discussion/council action kind and seq, phase/decision kind/actor/legal menu, non-null-draft boolean, retry count, and allowlisted response ID/hash/finish/usage. Response text, prompts, roles, private plans, and credentials are excluded. The active `8767` log is owner-only `~/.avalon/diagnostics/live-ai-affa5a35421988e8.jsonl` (`0700` directory, `0600` file); the `8766` match remains unchanged. Relevant tests passed `34/34`, with `git diff --check` clean. No prompt, decoder, legal-menu, V5, R5 runner, or production policy change was made.
- The frozen R5 call journal has `647` SOCIAL and `2` PASS accepted focal-Merlin ordinary discussion actions; all `2` PASS plans had null social. R5 used a different LiveClient context with a `response_contract` and only focal Merlin model calls, so these counts are not a same-condition comparator for the live browser's AI seats. Current evidence establishes multiple observed paths to silence and an output-consistency gap, but not the model's causal preference for PASS. R5's `FULL_GAME_EFFECT_NOT_ESTABLISHED` and `PRODUCTION=OFF` remain unchanged. Any behavior-changing correction to validation or prompting should be separately versioned and checked against the frozen boundaries; do not silently promote it.

## 57. User-authorized local engaged-discussion repair (2026-09-23)

- The user explicitly requested repairing silence strategy so AI produces as much public output as possible. The authorized scope is the local live browser's discussion contract, versioned as `engaged_v1`; it is not a V5 vote change or a new R5 controlled evaluation. Agent/GameSession defaults remain baseline; new live browser sessions select engaged discussion by default and allow explicit `--discussion-policy baseline`.
- In ordinary/council discussion, whenever the acting legal view permits an affordable one-Resolve SOCIAL action, the policy requires model-authored SOCIAL. A conflicting PASS (including PASS with a draft) is rejected and retried within the existing retry bound, never converted into speech. At no affordable speech, PASS with null social remains accepted. Role/tactical/privacy checks, engine legal menus/costs, beliefs, sealed votes, and native Assassin targeting remain authoritative. Local context adds exact role/phase response schema and active writing instructions; local retry feedback removes the contradictory suggestion to conserve by passing. Frozen ChatClient system prompts and R5 sources/artifacts are not edited.
- The related deterministic suite passed `161/161` tests, including eight new engagement test IDs. The bounded engineering smoke plan is one six-seat seed-34 opening, at most four AI discussion actions before human P1, at most twenty actual provider attempts including retries/retrieval, and stop on the first failed action. Use the existing configured client/model and persist safe attempt/usage and decision metadata under `results/local_live/20260923-engaged-discussion-v1-r1/`. No full-game outcome or effectiveness claim is sought, and no R5 schedule is resumed.
- The bounded smoke completed `PASS`: AI P5/P4/P3/P2 each committed one model-authored SOCIAL, with `resolve_after=2`, then stopped before human P1. Eight actual `deepseek-v4-flash` provider attempts were journaled, including one P4 validation retry (`Invalid social action`); unknown-usage attempts were zero. Reported usage was `74063` prompt and `1578` completion tokens. This is one opening-prefix engineering check, not four independent games or a strategy-effect result. Final schema/writing refinements passed an overlapping `41/41` targeted rerun after the broader `161/161` suite; do not add those counts together. Artifacts include `config.json`, `attempts.jsonl`, `decisions.jsonl`, `result.json`, `public_events.json`, `final_targeted.xml`, and `report.md` in the run directory.
- The repaired live/V5 backend is running at `http://127.0.0.1:8768/`; `/api/session` confirms `discussion_policy=engaged_v1`, and the rendered page shows `积极发言`. Its local diagnostic log is `~/.avalon/diagnostics/live-ai-5ef484eb8d6282bf.jsonl`. Existing 8766/8767 processes remain preserved and do not load the repair; users should use 8768 for repaired play. Browser build and diff checks passed. Local play on the repaired server is allowed; R5 stays closed and production research candidate promotion remains OFF. Do not treat this smoke or interactive play as a new controlled R5 sample or silently change its frozen gates.

## 58. Public record scrolling and vote continuation repair (2026-09-23)

- The user's public-history dialog clipped its oversized inner list, and every state render reset scrolling. The frontend now constrains the dialog to the viewport, gives the list the remaining height with native scrolling, and preserves the reading position across updates. Live browser verification reached both the newest records and the oldest record with the title and close button visible.
- No deterministic vote deadlock was reproduced in the preserved 8768 game. It was at revision 15, VOTE, with P6's final sealed ballot pending; one browser advance produced revision 16, VOTE_RESULT, with 2 approvals and 4 rejections. The UI previously required separate clicks per AI ballot and then an unlabeled-next-step `继续` gate. The repaired voting button collects remaining AI ballots sequentially through existing versioned commands, bounded by player count, and stops at a human choice, result/phase boundary, failure, or stale revision. Other AI phases still advance once. No engine, legal-menu, vote-policy, information-boundary, or decoder changes were made.
- Results now show vote totals and explicit next actions, and the panel distinguishes mission round from proposal attempt. Reload kept the active server/game intact; clicking `开始第 2 次提案` reached revision 17, TEAM_DRAFT, mission 1, proposal 2, leader P5/SAGE. No human ballot/mission choice or additional model-provider request was made by these ballot/continue checks. The next AI proposal remains available on 8768.
- Run `results/local_ui/20260923-public-log-vote-flow-r1/` records safe public state, browser scroll metrics, code hashes, and checks. The Node suite passed 14 tests; the Python GUI/HTTP suite passed 26 tests with one existing 16-game stress case deselected. An initial broad run was interrupted in that case after 9 overlapping tests passed; preserve it as incomplete, not a full-suite PASS. Two new six-seat regressions verify rejection -> next proposal and approval -> mission. Frontend build (851 modules) and diff checks passed. Cross-browser/mobile scrolling was not separately tested.
- Next allowed work is continued local play or review of these UI repairs. R5 remains closed with FULL_GAME_EFFECT_NOT_ESTABLISHED and production candidate promotion OFF; do not reinterpret local UI checks as new research evidence or modify frozen evaluation artifacts.

## 59. User-requested natural Chinese speech prompt (2026-09-23)

- The user explicitly requested normal conversational Chinese instead of medieval diction. The shared scene's public-writing section is now versioned `plain_zh_v1`: direct discussion of teams, votes and missions, exact seat IDs, grounded short statements/questions, no archaic stock phrases or imitation of old messages. Role personality is allowed without disclosing private information. The same style covers discussion, challenge/reaction windows, council, and private short summaries. The conflicting `RESOLVE_PROTOCOL` style sentence and private-disclosure retry wording in `avalon/llm.py` were updated consistently. Legal actions, JSON fields/enums, 240-character bound, citations, privacy checks, and the engaged-discussion policy are unchanged.
- Existing clients freeze prompts at creation; editing files or restarting an AI turn cannot replace the active client's cached text. The 8768 match was preserved. A fresh live/V5/engaged server is ready at `http://127.0.0.1:8769/`, phase START, with diagnostic path `~/.avalon/diagnostics/live-ai-45ee74c31a89c5a8.jsonl`. Start a new game there for the new wording. No live model call or new match was made as part of this prompt edit.
- `tests/test_llm.py` plus `tests/test_engaged_discussion.py` passed 23 tests. Sixteen credential-free request-shape checks covered four roles across plan/window/exile decisions, verifying both system-prompt variants contain the new style and no affirmative medieval-writing requirement. Verification and source hashes are in `results/local_live/20260923-plain-chinese-prompt-v1/verification.json`. This validates prompt assembly, not empirical model-style adherence or playing strength.
- This intentional shared prompt/transport-text edit changes current source hashes relative to R5's frozen inputs. R5 archived prompts, candidate/evaluation sources and locked run artifacts were not modified; do not replay the old R5 execution contract with these edited files or treat this style revision as its original baseline. R5 remains FULL_GAME_EFFECT_NOT_ESTABLISHED and production candidate promotion OFF. Next allowed work is local play on 8769 or review of the wording; any new research execution still needs a separate frozen design and authorization.
