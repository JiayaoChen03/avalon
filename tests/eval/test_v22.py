"""v2.2 offline boundaries, trajectory attribution and disabled policy checks."""
from copy import deepcopy
import json
import socket

import pytest

from avalon.engine import Game, make_players
from avalon.eval.simulation import digest, play_game
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2.v22_replay import semantic, mechanical_state, replay_trajectory
from avalon.eval.v2.v22_diagnostics import contingencies, pair_rows, align_pair, read_lines
from avalon.eval.v2.v22_runner import offline_guard, validate_paths
from avalon.eval.v2.v22_vote import (candidate_menu_context, vote_outcome_context,
    ContinuationConfig, production_branches)
from avalon.eval.v2.v21_contract import enrich_context, legal_menu, menu_context, POLICY_CANDIDATE
from avalon.eval.v2.v21_runtime import Session, atomic_json, json_read
from avalon.eval.simulation import policy_context


def test_semantic_actions_preserve_cards_citations_and_ap():
    a = {'kind': 'SOCIAL', 'social': {'card': 'DEFEND', 'target': 'P2', 'reason': 'observe', 'citations': [], 'public_writing': 'hello'}}
    b = deepcopy(a); b['social']['public_writing'] = 'another expression'
    assert semantic(a) == semantic(b)
    b['social']['card'] = 'ACCUSE'
    assert semantic(a) != semantic(b)
    b = deepcopy(a); b['social']['citations'] = ['R1-006']
    assert semantic(a) != semantic(b)
    assert semantic({'citations': ['R1-006', 'R1-008']}) != semantic({'citations': ['R1-008', 'R1-006']})
    assert semantic({'approve': True, 'strong': False}) != semantic({'approve': True, 'strong': True})


def test_team_order_is_separate_from_members():
    assert semantic({'team': ['P2', 'P1']}) == semantic({'team': ['P1', 'P2']})
    assert semantic({'team': ['P3', 'P1']}) != semantic({'team': ['P1', 'P2']})


def test_mechanical_projection_drops_prose_not_resource_state():
    a = Game(make_players(5, 3), seed=3); b = deepcopy(a)
    for g, text in ((a, 'hold judgment'), (b, 'still observing')):
        g.propose(g.leader, ['P1', 'P2'])
        actor = g.next_actor
        g.act(actor, {'kind': 'SOCIAL', 'social': {'card': 'HEDGE', 'target': next(p for p in g.ids if p != actor),
            'reason': 'observe', 'citations': [], 'public_writing': text}})
    # Valid, equally costly actions differ only in their public prose.
    assert a.events != b.events
    assert mechanical_state(a) == mechanical_state(b)
    b.resolve['P1'] -= 1
    assert mechanical_state(a) != mechanical_state(b)


def planned_pair():
    spec = {'experiment': 'A', 'scenario_id': 's', 'phase': 'main', 'scope': 'single_seat',
            'focal': 'P1', 'order': ['joint_v2', 'joint_v1']}
    return {'active': [spec], 'fixed': [], 'repeats': []}


def test_failed_and_missing_arms_are_not_losses():
    plan = planned_pair()
    jobs = [{'experiment': 'A', 'scenario_id': 's', 'variant': 'joint_v1', 'status': 'completed', 'focal_win': 1, 'focal_role': 'GOOD'},
            {'experiment': 'A', 'scenario_id': 's', 'variant': 'joint_v2', 'status': 'failed', 'focal_win': None, 'focal_role': 'GOOD'}]
    rows = pair_rows(plan, jobs)
    assert rows[0]['one_side_completed'] and rows[0]['candidate_value'] is None
    for r in contingencies(rows):
        assert r['denominator'] == 0 and r['delta'] is None and r['one_side_complete'] == 1
        assert all(r[k] == 0 for k in ('both_zero', 'both_one', 'zero_to_one', 'one_to_zero'))
    assert pair_rows(plan, jobs[:1])[0]['arm_statuses']['joint_v2'] == 'not_run'


def test_all_four_cells_and_scenario_denominators():
    base = {'experiment': 'A', 'scope': 'single_seat', 'phase': 'main', 'metric': 'focal_win', 'observer_role': 'MERLIN',
            'fully_paired': True, 'one_side_completed': False, 'completed_arms': 2, 'source_game_id': None}
    rows = [{**base, 'scenario_id': str(i), 'reference_value': a, 'candidate_value': b}
            for i, (a, b) in enumerate([(0, 0), (0, 1), (1, 0), (1, 1)])]
    for r in contingencies(rows):
        assert [r[k] for k in ('both_zero', 'zero_to_one', 'one_to_zero', 'both_one')] == [1, 1, 1, 1]
        assert r['denominator'] == r['source_clusters'] == 4 and r['delta'] == 0


def test_offline_guard_blocks_network_and_settings():
    from avalon.llm import Settings
    with offline_guard():
        with pytest.raises(RuntimeError, match='offline-only'): socket.create_connection(('example.invalid', 80))
        with pytest.raises(RuntimeError, match='offline-only'): Settings.load()


def test_source_directory_cannot_be_output(tmp_path):
    with pytest.raises(ValueError): validate_paths(tmp_path, tmp_path / 'analysis')
    with pytest.raises(ValueError): validate_paths(tmp_path / 'source', tmp_path)
    assert validate_paths(tmp_path / 'source', tmp_path / 'separate')[0].name == 'source'


def test_real_game_reconstruction_and_cross_belief_inputs(tmp_path):
    row, _, record = play_game(19191, 'joint_v2', belief_factory=make_version, capture_decisions=True, all_seats=True)
    assert row['status'] == 'completed'
    meta = {'corpus': 'fixed_source', 'source_arm': 'joint_v2', 'scenario_id': 'test-source', 'experiment': 'source', 'scope': 'generation'}
    with offline_guard(): audit = replay_trajectory((record, None, tmp_path / 'trace', meta))
    assert audit['events_equal'] and audit['same_legal_stream_to_both_beliefs']
    assert audit['duplicate_checks'] == audit['public_observations_delivered'] > 0
    inputs = json.loads((tmp_path / 'trace/legal_inputs.json').read_text())
    ordinary = next(v for v in inputs['initial_views'].values() if v['role'] == 'GOOD')
    assert ordinary['known_evil'] == []
    assert all(set(p) == {'id', 'name'} for p in ordinary['players'])
    decisions = list(read_lines(tmp_path / 'trace/decisions.jsonl.gz'))
    assert all(set(d['beliefs']) == {'joint_v1', 'joint_v2'} for d in decisions if d.get('beliefs'))
    endpoints = json.loads((tmp_path / 'trace/endpoints.json').read_text())
    assert len(endpoints) == 10 and all(e['point'] == 'endpoint' for e in endpoints)
    from avalon.eval.v2.v22_diagnostics import team_funnel
    transitions = list(team_funnel(record))
    assert sum(r['executed'] for r in transitions) == sum(e['kind'] == 'MISSION' for e in record['events'])
    assert all(r['locked'] for r in transitions if r['executed'])
    for r in transitions:
        initial = next(e for e in record['events'] if e['record_id'] == r['proposal_id'])
        assert (initial['round'], initial['attempt'], initial['kind']) == (r['round'], r['attempt'], 'TEAM')


def vote_fixture(n=5, mission=1, attempt=1):
    g = Game(make_players(n, 1823), seed=1823)
    g.round = mission; g.attempt = attempt; g.phase = 'vote'; g.team = g.ids[:g.team_size]
    if mission == 4: g.successes, g.failures = 2, 1
    view = g.view(next(p for p in g.ids if g.players[p].role == 'GOOD'))
    o = make_version('joint_v2', view)
    return g, enrich_context(policy_context(view, o), o), o.snapshot()['worlds']


def test_flag_off_is_identical_and_only_vote_changes():
    _, c, worlds = vote_fixture(); original = digest([c, worlds])
    base = menu_context(c, POLICY_CANDIDATE)
    assert candidate_menu_context(c, worlds) == base
    on = candidate_menu_context(c, worlds, enabled=True)
    assert on['action_menu'] == base['action_menu'] and on['response_contract'] == base['response_contract']
    assert {k: v for k, v in on.items() if k != 'vote_outcome_context'} == base
    assert digest([c, worlds]) == original
    g = Game(make_players(5, 31), seed=31); v = g.view(g.leader); o = make_version('joint_v2', v)
    nonvote = enrich_context(policy_context(v, o), o)
    assert candidate_menu_context(nonvote, enabled=True) == menu_context(nonvote, POLICY_CANDIDATE)


def test_hidden_referee_fields_outside_legal_input_do_not_affect_aid():
    _, c, worlds = vote_fixture()
    a = candidate_menu_context(c, worlds, enabled=True)
    c['referee_truth'] = {'P1': 'DO_NOT_USE'}; c['future_votes'] = [True] * 5
    c['opponent_private_posterior'] = 'DO_NOT_USE'; c['terminal_winner'] = 'DO_NOT_USE'
    b = candidate_menu_context(c, worlds, enabled=True)
    assert a == b and 'DO_NOT_USE' not in json.dumps(b)


def test_individual_vote_is_not_outcome_and_strong_is_not_extra_weight():
    _, c, worlds = vote_fixture()
    aid = vote_outcome_context(c['view'], worlds, legal_menu(c['view']))
    for b in aid['exact_production_branches']:
        assert set(b['reachable_branches']) == {'pass', 'reject'}
        assert b['pass_probability_unknown_range'] == [0, 1]
        assert b['reachable_branches']['pass']['phase'] == 'mission'
    actions = {b['action_id']: b['action'] for b in aid['exact_production_branches']}
    for s in aid['sensitivity_scenarios']:
        for approve in (False, True):
            probs = [r['model_pass_probability'] for r in s['actions'] if actions[r['action_id']]['approve'] == approve]
            assert len(set(probs)) == 1


@pytest.mark.parametrize('n', [5, 6])
def test_rejection_terminal_uses_production_rules(n):
    _, c, worlds = vote_fixture(n, attempt=5)
    aid = vote_outcome_context(c['view'], worlds, legal_menu(c['view']))
    for b in aid['exact_production_branches']:
        assert b['reachable_branches']['reject']['winner'] == 'EVIL'
        assert b['reachable_branches']['reject']['phase'] == 'ended'
    c['view']['rules']['max_proposals'] = 4
    with pytest.raises(ValueError, match='unsupported_rules'):
        vote_outcome_context(c['view'], worlds, legal_menu(c['view']))


def test_ap_cost_once_and_unknown_utility_not_zero():
    _, c, worlds = vote_fixture()
    aid = vote_outcome_context(c['view'], worlds, legal_menu(c['view']))
    costs = {b['action_id']: b['ap_cost'] for b in aid['exact_production_branches']}
    for scenario in aid['sensitivity_scenarios']:
        for a in scenario['actions']:
            if costs[a['action_id']]: assert a['net_proxy_utility_range'] is None and a['ap_penalty_once'] is None
    priced = vote_outcome_context(c['view'], worlds, legal_menu(c['view']), ContinuationConfig(ap_shadow_price=.07))
    for scenario in priced['sensitivity_scenarios']:
        for a in scenario['actions']:
            assert a['ap_penalty_once'] == pytest.approx(costs[a['action_id']] * .07)
            assert a['gross_proxy_utility_range'][0] - a['net_proxy_utility_range'][0] == pytest.approx(a['ap_penalty_once'])


def test_no_resource_no_strong_option_and_no_host_action():
    _, c, worlds = vote_fixture(); c['view']['resolve'][c['view']['self']] = 0
    c['view']['legal_options'] = [o for o in c['view']['legal_options'] if o['kind'] != 'STRONG_VOTE']
    c['view']['legal_actions'] = [a for a in c['view']['legal_actions'] if a != 'STRONG_VOTE']
    aid = candidate_menu_context(c, worlds, enabled=True)
    assert all(not o['action']['strong'] for o in aid['action_menu'])
    assert 'chosen_action' not in aid['vote_outcome_context']


def test_same_alignment_marginals_different_joint_risk():
    _, c, _ = vote_fixture(); v = c['view']; own = v['self']; others = [p['id'] for p in v['players'] if p['id'] != own]
    def world(evil):
        good = [p for p in others if p not in evil]
        return {'roles': {own: 'GOOD', evil[0]: 'ASSASSIN', evil[1]: 'EVIL', good[0]: 'MERLIN', good[1]: 'GOOD'}, 'probability': .5}
    a = [world(others[:2]), world(others[2:])]
    b = [world([others[0], others[2]]), world([others[1], others[3]])]
    v['team'] = others[:2]
    ra = vote_outcome_context(v, a, legal_menu(v))['current_model_mission_failure']
    rb = vote_outcome_context(v, b, legal_menu(v))['current_model_mission_failure']
    assert ra == pytest.approx(.375) and rb == pytest.approx(.5)
    assert all(sum(w['probability'] for w in a if w['roles'][p] in {'EVIL', 'ASSASSIN'}) ==
               sum(w['probability'] for w in b if w['roles'][p] in {'EVIL', 'ASSASSIN'}) for p in others)


def test_real_threshold_and_evil_success_remain_possible(monkeypatch):
    # The actual repository currently uses threshold 1 for both supported sizes.
    # Probe a production-rule extension consistently at both API boundaries.
    from avalon.engine import mission_rules as original
    def threshold_two(n, round): return {**original(n, round), 'fail_threshold': 2}
    monkeypatch.setattr('avalon.engine.mission_rules', threshold_two)
    monkeypatch.setattr('avalon.eval.v2.v22_vote.mission_rules', threshold_two)
    _, c, worlds = vote_fixture(6, mission=4)
    assert c['view']['rules']['fail_threshold'] == 2
    aid = vote_outcome_context(c['view'], worlds, legal_menu(c['view']))
    assert 0 < aid['current_model_mission_failure'] < 1


def test_original_posterior_mismatch_stops_exported_scores(tmp_path):
    state = tmp_path / 'checkpoint/state.json'
    session = Session(state, {'game_id': 'test', 'config': 'frozen'})
    row, _, record = play_game(29192, 'joint_v2', belief_factory=make_version, all_seats=True,
        capture_decisions=True, session=session, context_enricher=enrich_context)
    assert row['status'] == 'completed'
    record.update(scope='whole_table', observer_id='P1', variant='joint_v2')
    checkpoint = json_read(state); path = state.parent / 'contexts/0000.json'; c = json_read(path)
    c['posterior_hash'] = 'corrupt'; atomic_json(path, c)
    checkpoint['decisions'][0]['binding']['context_hash'] = digest(c); atomic_json(state, checkpoint)
    with pytest.raises(ValueError, match='reconstruction_mismatch'):
        replay_trajectory((record, state, tmp_path / 'invalid', {'corpus': 'active', 'scenario_id': 's'}))
    assert not (tmp_path / 'invalid/audit.json').exists() and not (tmp_path / 'invalid/endpoints.json').exists()


def test_new_proposal_not_matched_just_by_round():
    def d(attempt):
        return {'round': 1, 'attempt': attempt, 'phase': 'vote', 'observer_id': 'P1', 'observer_role': 'GOOD',
            'occurrence': 0, 'decision_index': 0, 'status': 'executed', 'action': {'approve': True, 'strong': False},
            'semantic_action': {'approve': True, 'strong': False}, 'legal_information_hash': str(attempt), 'mechanical_hash': str(attempt)}
    a = {'meta': {'trajectory_id': 'a'}, 'decisions': [d(1)], 'public_events': [], 'mechanical_states': []}
    b = {'meta': {'trajectory_id': 'b'}, 'decisions': [d(2)], 'public_events': [], 'mechanical_states': []}
    pair, aligned = align_pair(a, b)
    assert pair['common_coordinate_prefix'] == 0 and aligned == []
    # A synthetic menu for a controlled/forced seat is not an actual model input.
    control_a, control_b = d(1), d(1)
    for x in (control_a, control_b): x.update(phase='discussion', was_model_requested=False)
    control_a['model_context_hash'] = 'controlled-a'; control_b['model_context_hash'] = 'controlled-b'
    real = d(1); real.update(decision_index=1, was_model_requested=True, model_context_hash='same-paid-input')
    a['decisions'], b['decisions'] = [control_a, real], [control_b, deepcopy(real)]
    pair, aligned = align_pair(a, b)
    assert pair['model_context_prefix'] == 1 and pair['first_input_difference'] is None


def test_future_events_are_after_decision_cutoff(tmp_path):
    row, _, record = play_game(88113, 'joint_v2', belief_factory=make_version, capture_decisions=True, all_seats=True)
    output = tmp_path / 'cutoff'; replay_trajectory((record, None, output,
        {'corpus': 'fixed_source', 'source_arm': 'joint_v2', 'scenario_id': 'cutoff', 'experiment': 'source', 'scope': 'generation'}))
    cutoff = min(e['seq'] for e in record['events'] if e['kind'] in {'ASSASSINATE', 'RESULT'})
    assert all(r.get('event', {}).get('seq', 0) < cutoff for r in read_lines(output / 'inference.jsonl.gz'))
    assert all(r['event_seq'] < cutoff for r in read_lines(output / 'belief_trace.jsonl.gz'))
