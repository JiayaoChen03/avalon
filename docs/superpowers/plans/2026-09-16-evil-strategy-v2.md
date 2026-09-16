# Evil strategy v2 implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the independent strategy core; apply test-driven-development and a final spec/code review to integration.

**Goal:** Make two evil AI players coordinate legal strategies in code and express them through live sequential LLM speech.

**Architecture:** One game-scoped, private coordinator consumes only authorized evil IDs and public events. Agents receive bounded tactical projections; Game remains authoritative.

**Tech Stack:** Python 3.10+, standard library unittest; existing dotenv and HTTP client.

**Spec:** `docs/superpowers/specs/2026-09-16-evil-strategy-v2-design.md`

## Global Constraints

- Code decides WHAT. LLM decides HOW.
- No mock runtime, fixed dialogue, hidden reasoning transfer, full role table, or true Merlin ID in the manager.
- Preserve 5/6-player rules, real sequential requests and bounded same-turn retries.
- Do not read/change `.env`, make live API calls, commit or push from worker tasks.
- Tests may replace only the external model boundary; all rule/strategy logic stays real.

### Task 1: Private strategy core

**Files:** Create `avalon/evil_strategy.py`, optionally `avalon/evil_state.py` for focused data/observation logic, and `tests/test_evil_strategy.py`. Do not edit other production/test files.

**Interfaces (binding):**

```python
class EvilStrategyManager:
    def __init__(self, player_ids, evil_ids, *, seed=None, controlled_evil_ids=None): ...
    # .state: EvilSharedState; .decisions: list[StrategyDecision]
    # .evil_ids / .controlled_evil_ids: sets of IDs
    def observe(self, event): ...  # idempotent public-event ingestion; ignore REVEAL
    def tactical_context(self, view, phase=None): ...  # TacticalContext; own evil view only
    def choose_team(self, view): ...  # list[str], legal team of view['team_size']
    def vote(self, view): ...  # bool for view['self'] on view['team']
    def mission_cards(self, view, external_cards=None): ...  # controlled evil IDs on team -> SUCCESS/FAIL
    def assassinate(self, view): ...  # legal non-evil ID, selected using code probabilities
    def debug_snapshot(self): ...  # deep-copied JSON-compatible structured state
```

`TacticalContext.to_dict()` returns a fresh bounded JSON-compatible object with `strategy_mode`, `role` (Aggressor/Sleeper), `primary_objective`, `secondary_objective` (string or None), `primary_target`, `evil_partner`, `distance_strength`, `active_narratives`, `agenda_topic`, `constraints`, `relevant_public_events`, `allowed_cards`. `primary_target` is a valid ID and `allowed_cards` a nonempty subset of existing CARDS. `StrategyDecision` is a dataclass containing round, attempt, phase, agent_id, strategy_mode, primary_objective, secondary_objective, target, confidence; may add small structured action/role fields. No natural-language reasoning.

Public methods receive an ordinary copied `Game.view` (existing fields). Good/Merlin views must be rejected even if they know evil IDs. Main phases are team, discussion, vote (override), mission, assassination. `tactical_context` is stable per `(round,attempt,phase,self)`; shared selection is stable within a phase, yet scores reflect new observed events. `choose_team` is stable and called before LLM to convey selected team; `vote` called after discussion; mission assignment is computed once per proposal, idempotent, excludes absent players. Changes in external_cards cannot silently reuse an incompatible cache.

**Required behavior:**

- Implement all EvilSharedState concepts from user spec, plus pair_suspicion and distance_strength. Initialize code estimates as hypotheses, not fictional history. State exposes no complete LLM plans.
- Public SOCIAL, TEAM_VOTE and MISSION events drive suspicion/trust/profiles/tags, partner agreement/defense and normalized Merlin likelihood. Known evil probability is zero; one signal cannot lock Merlin. Deduplicate event IDs.
- Support NORMAL_DECEPTION, FAKE_CONFLICT, CONSENSUS_SEEDING, AGENDA_CAPTURE, MERLIN_HUNT, SACRIFICE, CRISIS_RECOVERY with state-based scores + small seedable randomness and repetition penalties; initial roles vary by seed, dynamically exchange when trust/suspicion difference warrants it.
- High pair suspicion triggers fake conflict; distance uses round, trust, suspicion, agreement, pairing. Aggressor gets CREATE_DISTANCE_FROM_PARTNER; Sleeper MAINTAIN_INDEPENDENCE. Avoid mechanically mutual immediate attacks.
- A highly suspected member (e.g. .82) with safe, trusted teammate (.23 suspicion/.74 trust) can be sacrificed. Target gets SACRIFICE_SELF + misleading affiliation with a non-evil target; partner gets SACRIFICE_PARTNER. No fixed round trigger.
- Limit partner defense. Consensus reinforcement requires an actual partner seed plus an intervening other speaker; immediate adjacency uses independent objective instead.
- Keep 0–4 bounded narrative records containing category, target(s), evidence seq IDs, no invented event facts or dialogue. When evidence allows, retain 2–4 competing interpretations. Target selection considers public tags as soft modifiers.
- Team choices, vote divergence/distance, sacrifice voting, code-owned assassination and at-most-one mission fail are real control logic. Vary fail owner with exposure/history/randomness; no same-person hardcode. Fifth rejection is an evil win and decisive mission scores must inform decisions.
- Human evil cards in external_cards remain authoritative; if a human already fails, AI returns SUCCESS. Without controlled evil members on team return {}. Validate external cards and membership without exposing them.
- Keep only necessary code histories/caches (games bounded at 5 missions/25 proposals); do not use actual Merlin identity or accept LLM-supplied probabilities.

- [x] Write strategy tests first and show expected initial failure for missing behavior.
- [x] Implement scoring, state updates, roles, bounded projection and action coordination.
- [x] Run `python -m unittest discover -s tests -p test_evil_strategy.py -v`; cover literal acceptance scenarios, privacy/seed/idempotency and natural public-event progression.
- [x] Self-review and write a concise report with command/result evidence. No git mutations.

### Task 2: Agent and live LLM integration

**Files:** `avalon/agents.py`, `avalon/llm.py`, new `tests/test_evil_integration.py`, existing test external-response fixtures.

- [x] Failing tests: binding rejects good/Merlin; evil response cannot overwrite code state; malicious tactical disclosures retry with identical context and never publish; mutate input cannot mutate Game/manager; both agents use same manager.
- [x] Add validated manager binding and fresh view refresh, minimal evil-response schema, stable EVIL_SYSTEM, bounded private tactical projection and whitelist response parsing.
- [x] Route evil choose_team/vote/mission/assassinate to code; preserve good agent behavior and actual LLM natural speech. Reject explicit private disclosures for managed evil with existing retry policy.
- [x] Run focused integration tests and existing agent/LLM regression tests.

### Task 3: Terminal, debug isolation and acceptance

**Files:** `avalon/terminal.py`, `tests/test_terminal.py`, `tests/test_evil_integration.py`, `README.md`.

- [x] Write failing full-game tests for manager lifecycle, no shared state for good, at most one coordinated sabotage, human card preservation, stderr/debug trace separation and fixed-seed reproducibility.
- [x] Wire one manager per run, refresh views before actual actions, observe each public event exactly once, refresh major decision phases, and collect human evil mission card before coordinating AI. Use the manager's returned card mapping directly.
- [x] Add `--debug-strategy` stderr and `--strategy-log` separate JSONL; reject collisions with public log or local env. Print structured objectives/roles/targets/owner/probability without raw provider content. Map private validation errors to role-neutral public errors.
- [x] Document current strategy boundaries, priority scope, commands, tests and heuristic limitations. Keep future personalities/LLM strategy proposal explicitly outside MVP.
- [x] Run full unittest suite, a local HTTP CLI game and bounded real-provider smoke if useful; review diff and verify no private state in public outputs.

## Progress

- Task 1: implemented; 55 strategy tests pass, including red/green regression evidence and real-Game event-only progression for Sacrifice, Crisis Recovery and Merlin Hunt.
- Task 2: implemented; managed evil leaders request only their actual discussion performance, including the already selected team.
- Task 3: implemented; independent review and focused re-review passed with no remaining blockers.
- Full verification: `python -m unittest discover -s tests -v` — 136 tests passed in 19.590s, including real CLI/local HTTP runs, 5/6-player complete games, privacy and human paths.
- Live check after review fixes: existing DeepSeek V4 Flash configuration produced two consecutive validated evil-agent public actions with matching accepted strategy traces, one request each. No configuration changes or full-game quality claim.
- Review corrections: record social decisions only after accepted public events; reject exact private narrative/agenda/constraint labels and readable variants; restrict external mission cards to uncontrolled evil teammates. Earlier error-channel, mission-map and redundant-request fixes are also covered by regressions.
- Repository scan found no API-key literals; `.env` remains untracked; `avalon/engine.py` is unchanged.
