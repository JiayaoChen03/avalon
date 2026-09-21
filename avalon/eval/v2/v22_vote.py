"""Disabled-by-default vote branch aid; no new beliefs, actions or live runner.

One current ballot, at most one later proposal ballot, and one mission result.
Utilities are bounded score proxies, never calibrated game-win probabilities.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import combinations, product
import math
from pathlib import Path

from avalon.engine import Game, Player, mission_rules
from avalon.mission_likelihood import MissionLikelihoodConfig, MissionOutcomeLikelihood
from avalon.eval.simulation import digest, canonical, policy_context
from .adapters import make_version
from .v21_contract import legal_menu, menu_context, POLICY_CANDIDATE, enrich_context
from .v21_runtime import atomic_json, json_read
from .v22_diagnostics import export, read_lines

CONTEXT_REVISION = 'vote-outcome-v22-prototype-r1'


@dataclass(frozen=True)
class ContinuationConfig:
    revision: str = CONTEXT_REVISION
    q: float = .5
    other_vote_probabilities: tuple = (.25, .5, .75)
    proposal_horizon: int = 2
    ap_shadow_price: float | None = None

    def __post_init__(self):
        if self.proposal_horizon != 2 or not 0 < self.q < 1:
            raise ValueError('Only frozen two-proposal horizon and interior q are supported')
        if not self.other_vote_probabilities or any(not 0 <= p <= 1 for p in self.other_vote_probabilities):
            raise ValueError('Invalid declared vote sensitivity')
        if self.ap_shadow_price is not None and (not math.isfinite(self.ap_shadow_price) or self.ap_shadow_price < 0):
            raise ValueError('Invalid AP utility coefficient')


def hypothetical_game(view, world):
    """Mechanical probe built from a posterior hypothesis, not referee state."""
    g = Game([Player(p['id'], p['name'], world[p['id']]) for p in view['players']], seed=0,
             direction=view['speaking_direction'])
    g.round = view['round']; g.attempt = view['attempt']; g.phase = 'vote'
    g.team = list(view['team']); g.successes = view['successes']; g.failures = view['failures']
    g.resolve = deepcopy(view['resolve']); g.lives = deepcopy(view['lives']); g.safe_round = view['safe_round']
    g.leader_index = g.ids.index(view['leader'])
    rules = g.view(view['self'])['rules']
    if rules != view['rules'] or g.view(view['self'])['required_approvals'] != view['required_approvals']:
        raise ValueError('unsupported_rules: legal view does not match frozen production rules')
    return g


def production_branches(view, worlds, menu):
    if menu != legal_menu(view): raise ValueError('Menu differs from production legal menu')
    world = worlds[0]['roles']; proto = hypothetical_game(view, world)
    others = [p for p in proto.ids if p != view['self']]
    result = []
    for option in menu:
        action = option['action']
        patterns = []; costs = set(); branches = {}
        for ballots in product((False, True), repeat=len(others)):
            g = deepcopy(proto); votes = dict(zip(others, ballots)); votes[view['self']] = action['approve']
            strong = dict.fromkeys(g.ids, False); strong[view['self']] = action['strong']
            g.vote(votes, strong=strong)
            approved = next(e['approved'] for e in g.events if e['kind'] == 'TEAM_VOTE')
            cost = view['resolve'][view['self']] - g.resolve[view['self']]; costs.add(cost)
            branches['pass' if approved else 'reject'] = {'phase': g.phase, 'winner': g.winner,
                'next_attempt': g.attempt, 'next_leader': g.leader, 'self_resolve_after': g.resolve[view['self']]}
            patterns.append((sum(ballots), approved))
        if len(costs) != 1: raise ValueError('Unexpected ballot-dependent own resource cost')
        result.append({'action_id': option['action_id'], 'action': deepcopy(action), 'ap_cost': next(iter(costs)),
            'reachable_branches': branches, 'pass_probability_unknown_range': [int(all(x[1] for x in patterns)), int(any(x[1] for x in patterns))],
            '_patterns': patterns})
    return result


def vote_outcome_context(view, worlds, menu, config=ContinuationConfig()):
    if view['phase'] != 'vote': raise ValueError('Vote-only helper')
    if not worlds or any(w['probability'] < 0 for w in worlds) or not math.isclose(sum(w['probability'] for w in worlds), 1, abs_tol=1e-9):
        raise ValueError('Full normalized joint posterior required')
    # Read only whitelisted legal inputs; external truth/policy labels ignored.
    branches = production_branches(view, worlds, menu)
    ids = [p['id'] for p in view['players']]; teams = list(combinations(ids, view['team_size']))
    align = view['private_knowledge']['self_alignment']
    model = MissionOutcomeLikelihood(MissionLikelihoodConfig(enabled=True, q=config.q))
    rules = mission_rules(len(ids), view['round'])
    proto = hypothetical_game(view, worlds[0]['roles'])

    def score_value(success):
        g = deepcopy(proto); g.successes += int(success); g.failures += int(not success)
        # Council is not simulated. This probes only the actual score/terminal
        # transition after council; AP/social/exile continuation is unsupported.
        g.phase = 'council_result'; g.finish_council()
        if g.winner: return (float(g.winner == align),) * 2
        if g.phase == 'assassination': return (0., 1.)
        good = .5 + (g.successes - g.failures) / (2 * len(view['rules']['team_sizes']))
        value = good if align == 'GOOD' else 1 - good
        return (value, value)

    success_value, fail_value = score_value(True), score_value(False)
    base_good = .5 + (view['successes'] - view['failures']) / (2 * len(view['rules']['team_sizes']))
    base_value = base_good if align == 'GOOD' else 1 - base_good

    def mission_value(world, team):
        k = sum(view['rules']['role_alignments'][world[p]] == 'EVIL' for p in team)
        fail = model.team_failure_probability(k, rules, team)
        return tuple((1 - fail) * success_value[i] + fail * fail_value[i] for i in (0, 1)), fail

    current = [0., 0.]; future = [0., 0.]; current_risk = 0.
    for w in worlds:
        value, risk = mission_value(w['roles'], view['team'])
        next_values = [mission_value(w['roles'], t)[0] for t in teams]
        current_risk += w['probability'] * risk
        for i in (0, 1):
            current[i] += w['probability'] * value[i]
            future[i] += w['probability'] * math.fsum(x[i] for x in next_values) / len(next_values)
    sensitivities = []
    for p in config.other_vote_probabilities:
        # Votes are explicitly role/world-independent in this sensitivity model.
        # Thus pass weighting does not accidentally decorrelate a role-based
        # voting model from mission outcomes. No such opponent model is fitted.
        next_pass = math.fsum(math.comb(len(ids), yes) * p ** yes * (1-p) ** (len(ids)-yes)
            for yes in range(view['required_approvals'], len(ids) + 1))
        per_action = []
        for b in branches:
            patterns = b['_patterns']; n = len(ids) - 1
            passed = math.fsum(p ** yes * (1-p) ** (n-yes) for yes, ok in patterns if ok)
            rejected = b['reachable_branches'].get('reject')
            if rejected is None:
                reject_value = (base_value, base_value)
            elif rejected['winner']:
                reject_value = (float(rejected['winner'] == align),) * 2
            else:
                # Stop after one additional proposal vote. A second rejection
                # uses the public proposal limit; no unbounded search.
                next_reject = float(align == 'EVIL') if rejected['next_attempt'] == view['rules']['max_proposals'] else base_value
                reject_value = tuple(next_pass * future[i] + (1-next_pass) * next_reject for i in (0, 1))
            gross = [passed * current[i] + (1-passed) * reject_value[i] for i in (0, 1)]
            penalty = None if config.ap_shadow_price is None and b['ap_cost'] else (config.ap_shadow_price or 0.) * b['ap_cost']
            per_action.append({'action_id': b['action_id'], 'model_pass_probability': passed,
                'pass_utility_range': current, 'reject_utility_range': list(reject_value),
                'gross_proxy_utility_range': gross, 'ap_penalty_once': penalty,
                'net_proxy_utility_range': None if penalty is None else [x - penalty for x in gross]})
        sensitivities.append({'assumption_id': f'world_independent_bernoulli_votes_{p}',
            'other_yes_probability': p, 'next_proposal_pass_probability': next_pass, 'actions': per_action})
    for b in branches: b.pop('_patterns')
    return {'revision': config.revision, 'evidence_level': 'model_dependent',
        'exact_production_branches': branches, 'current_model_mission_failure': current_risk,
        'horizon': 'current ballot plus one next-proposal ballot; at most one executed mission result',
        'utility': '0/1 only for rule-terminal branches; nonterminal score proxy .5+(good-evil)/(2*number_of_missions), complemented for EVIL; assassination interval [0,1]',
        'assumption_ids': ['frozen_joint_posterior', f'independent_sabotage_q_{config.q}',
            'uniform_legal_next_team_same_mission', 'world_independent_vote_sensitivities', 'stop_after_second_ballot', 'no_new_belief_evidence'],
        'unsupported_fields': ['true_opponent_ballots', 'actual_next_leader_policy', 'future_social_or_exile_effects',
            'assassination_survival_probability', 'calibrated_game_win_probability'] +
            (['AP_shadow_utility_unknown_for_costly_actions'] if config.ap_shadow_price is None else []),
        'sensitivity_scenarios': sensitivities, 'config': asdict(config),
        'instruction': 'Inspect possible branches and assumption ranges. Preserve all legal choices; this aid neither chooses nor repairs an action.'}


def candidate_menu_context(context, worlds=None, *, enabled=False, config=ContinuationConfig()):
    result = menu_context(context, POLICY_CANDIDATE)
    if enabled and context['view']['phase'] == 'vote':
        result['vote_outcome_context'] = vote_outcome_context(context['view'], worlds, result['action_menu'], config)
    return result


def evaluate_snapshots(out):
    """Evaluate an immutable aid, not a surrogate for new LLM actions."""
    out = Path(out); selected = json_read(out / 'selected_bottleneck.json')
    if selected['selected_component'] != 'vote_branch_consequences_and_bounded_continuation':
        raise ValueError('A different single candidate was selected')
    from .v21_data import source_game, input_for
    cfg = ContinuationConfig(); config_hash = digest(asdict(cfg))
    plan_path = out / 'offline_validation_plan.json'
    plan = {'frozen_before_generation': True, 'config': asdict(cfg), 'config_hash': config_hash,
        'source_type': 'new controlled production-engine games, not LLM', 'status': 'frozen',
        'scenarios': [{'seed': 22261000 + i, 'profile': ('v21_development', 'v21_validation', 'v21_heldout_a', 'v21_heldout_b')[i // 3],
            'split': 'new_offline_validation', 'phase': 'v22_controlled_validation', 'scope': 'generation',
            'focal': 'P1', 'scenario_id': f'v22-controlled-{22261000+i}'} for i in range(12)],
        'selection': 'first vote per role per source game; freeze before generation; no candidate outcome tuning',
        'primary': 'legal menu, posterior/input immutability and rule-branch consistency; not an effectiveness test'}
    if plan_path.exists():
        if digest(json_read(plan_path)) != digest(plan): raise ValueError('Validation plan changed')
    else: atomic_json(plan_path, plan)
    corpus_path = out / 'controlled_validation_replays.jsonl'
    if corpus_path.exists(): records = list(read_lines(corpus_path))
    else:
        records = [source_game(s) for s in plan['scenarios']]
        corpus_path.write_text(''.join(canonical(r) + '\n' for r in records))
    # r7 diagnostic inputs carry no truth labels into the candidate.
    source = Path(json_read(out / 'config.json')['source_run'])
    jobs = [json_read(p) for p in sorted((source / 'jobs').glob('*.json'))]
    data = [{'corpus': 'r7_diagnostic', 'source_game_id': j['source_game_id'], 'snapshot_id': j['snapshot_id'],
             'context': j['context'], 'worlds': j['joint_state']['worlds'], 'recorded_action': j.get('action')}
            for j in jobs if j['experiment'] == 'B' and j['scope'] == 'fixed' and j['variant'] == 'policy_current']
    for r in records:
        seen = set()
        for index, d in enumerate(r['decisions']):
            role = d['view']['role']
            if d['phase'] != 'vote' or role in seen: continue
            seen.add(role)
            spec = {'source_game_id': r['game_id'], 'decision_index': index}
            contexts, _, observers = input_for(spec, {r['game_id']: r})
            data.append({'corpus': 'new_controlled_validation', 'source_game_id': r['game_id'],
                'snapshot_id': f"{r['game_id']}:{index}", 'context': contexts['joint_v2'],
                'worlds': observers['joint_v2'].snapshot()['worlds'], 'recorded_action': None})
    results = []
    for d in data:
        c, worlds = d['context'], d['worlds']; before = digest([c, worlds]); base = menu_context(c, POLICY_CANDIDATE)
        off = candidate_menu_context(c, worlds); on = candidate_menu_context(c, worlds, enabled=True, config=cfg)
        aid = on['vote_outcome_context']
        assert off == base and digest([c, worlds]) == before
        assert on['action_menu'] == base['action_menu'] and on['response_contract'] == base['response_contract']
        assert {k: v for k, v in on.items() if k != 'vote_outcome_context'} == base
        results.append({k: d[k] for k in ('corpus', 'source_game_id', 'snapshot_id')} | {
            'observer_role': c['view']['role'], 'input_hash': digest(c), 'posterior_hash': c['posterior_hash'],
            'disabled_context_hash': digest(off), 'reference_context_hash': digest(base), 'candidate_context_hash': digest(on),
            'additional_context_bytes': len(canonical(on).encode()) - len(canonical(base).encode()),
            'status': 'passed', 'candidate_action': None, 'candidate_action_status': 'not_run',
            'recorded_r7_action_diagnostic_only': d['recorded_action'], 'vote_outcome_context': aid})
    export(out, 'candidate_contexts', results)
    sizes = sorted(r['additional_context_bytes'] for r in results)
    summary = {'status': 'passed', 'candidate_enabled_by_default': False, 'config_hash': config_hash,
        'snapshots': len(results), 'by_corpus': dict(Counter(r['corpus'] for r in results)),
        'by_role': dict(Counter(r['observer_role'] for r in results)), 'new_controlled_games': len(records),
        'new_controlled_game_status': dict(Counter(r['status'] for r in records)),
        'menu_unchanged': True, 'posterior_unchanged': True, 'disabled_inputs_identical': True,
        'added_context_bytes': {'min': sizes[0], 'median': sizes[len(sizes)//2], 'max': sizes[-1]},
        'new_llm_calls': 'not_run', 'candidate_actions': 'not_run', 'game_effect': 'not_run',
        'limitation': 'Uniform future teams and declared independent vote sensitivities are assumptions; no provider action sampled'}
    atomic_json(out / 'candidate_validation.json', summary)
    return summary
