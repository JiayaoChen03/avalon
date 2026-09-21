"""r7-only descriptive diagnostics, with every planned arm retained."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import csv
import math
from pathlib import Path

from avalon.chronicle import PUBLIC_KINDS, context_record
from avalon.engine import EVIL_ROLES, Game, Player
from avalon.eval.simulation import canonical, digest
from .reporting import write_csv
from .v21_reporting import pairing, ratio, cluster_delta, independent_repeat
from .v21_runtime import atomic_json, json_read
from .v22_replay import semantic


def read_lines(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt') as stream:
        for line in stream:
            if line.strip(): yield json.loads(line)


def export(out, name, rows):
    rows = list(rows); out = Path(out)
    (out / (name + '.jsonl')).write_text(''.join(canonical(r) + '\n' for r in rows))
    write_csv(out / (name + '.csv'), [
        {k: canonical(v) if isinstance(v, (list, dict)) else v for k, v in r.items()} for r in rows])
    return rows


def contingencies(rows):
    """All four paired cells, including zeros; missing outcomes aren't losses."""
    groups = defaultdict(list)
    for r in rows:
        for role in ('ALL', r['observer_role']):
            groups[r['experiment'], r['scope'], r['phase'], r['metric'], role].append(r)
    result = []
    for (exp, scope, phase, metric, role), rs in sorted(groups.items()):
        valid = [r for r in rs if r['fully_paired'] and r['reference_value'] is not None and r['candidate_value'] is not None]
        cells = Counter((r['reference_value'], r['candidate_value']) for r in valid)
        stats = cluster_delta([(r['source_game_id'] or r['scenario_id'], r['reference_value'], r['candidate_value']) for r in valid])
        result.append({'experiment': exp, 'scope': scope, 'phase': phase, 'metric': metric, 'observer_role': role,
            'planned_pairs': len(rs), 'complete_pairs': len(valid),
            'both_zero': cells[0, 0], 'zero_to_one': cells[0, 1], 'one_to_zero': cells[1, 0], 'both_one': cells[1, 1],
            'one_side_complete': sum(r['one_side_completed'] for r in rs),
            'neither_complete': sum(r['completed_arms'] == 0 for r in rs),
            'reference_numerator': stats['reference']['numerator'], 'candidate_numerator': stats['candidate']['numerator'],
            'denominator': len(valid), 'source_clusters': stats['paired_clusters'],
            'delta': stats['delta'], 'ci95': stats['ci95'], 'interpretation': stats['status'],
            'metric_note': 'approval is descriptive, not correctness' if metric == 'approve' else
                           'clean team is an intermediate property, not evil-role utility' if metric == 'clean_team' else
                           'conditional on both completed; no failed-game imputation'})
    return result


def pair_rows(plan, jobs):
    lookup = {(j['experiment'], j['scenario_id'], j['variant']): j for j in jobs}
    rows = []
    for p in pairing(plan, jobs):
        if len(p['planned_order']) != 2: continue
        arms = ('joint_v1', 'joint_v2') if p['experiment'] == 'A' else ('policy_current', 'policy_candidate')
        a, b = [lookup.get((p['experiment'], p['scenario_id'], arm), {}) for arm in arms]
        metric = ('clean_team' if p['phase'] == 'team' else 'approve') if p['scope'] == 'fixed' else (
            'good_win' if p['scope'] == 'whole_table' else 'focal_win')
        av = a.get(metric) if a.get('status') == 'completed' else None
        bv = b.get(metric) if b.get('status') == 'completed' else None
        rows.append({**p, 'reference_arm': arms[0], 'candidate_arm': arms[1], 'metric': metric,
            'observer_role': a.get('observer_role', a.get('focal_role', b.get('observer_role', b.get('focal_role', 'unavailable')))),
            'reference_value': av, 'candidate_value': bv,
            'reference_terminal_reason': a.get('terminal_reason'), 'candidate_terminal_reason': b.get('terminal_reason'),
            'reference_error': a.get('error'), 'candidate_error': b.get('error'),
            'reference_action': a.get('action'), 'candidate_action': b.get('action'),
            'team_members_changed': set(a['action']['team']) != set(b['action']['team'])
                if p['phase'] == 'team' and p['fully_paired'] else None,
            'team_order_only_changed': a['action']['team'] != b['action']['team'] and set(a['action']['team']) == set(b['action']['team'])
                if p['phase'] == 'team' and p['fully_paired'] else None,
            'vote_changed': a['action']['approve'] != b['action']['approve']
                if p['phase'] == 'vote' and p['fully_paired'] else None,
            'strong_changed': a['action']['strong'] != b['action']['strong']
                if p['phase'] == 'vote' and p['fully_paired'] else None})
    return rows


def team_funnel(record):
    truth = {p['id']: p['role'] for p in record['players']}; events = record['events']
    for e in events:
        if e['kind'] not in {'TEAM', 'TEAM_REVISE'}: continue
        coord = (e['round'], e['attempt'])
        related = [x for x in events if (x['round'], x['attempt']) == coord]
        nominations = [x for x in related if x['kind'] in {'TEAM', 'TEAM_REVISE'}]
        final = e['seq'] == nominations[-1]['seq']
        lock = next((x for x in related if x['kind'] == 'TEAM_LOCK'), None) if final else None
        vote = next((x for x in related if x['kind'] == 'TEAM_VOTE'), None) if final else None
        vote_decision = next((d for d in record['decisions'] if d['phase'] == 'vote' and
            (d['round'], d['attempt']) == coord), None) if final else None
        locked = bool(lock or vote_decision or vote)
        lock_seq = lock['seq'] if lock else vote_decision['after_seq'] if vote_decision else vote['seq'] if vote else None
        mission = next((x for x in related if x['kind'] == 'MISSION'), None) if final else None
        result = next((x for x in events if x['kind'] == 'RESULT'), {})
        yield {'trajectory_id': record['game_id'], 'experiment': record.get('experiment', 'source'),
            'scenario_id': record.get('scenario_id'), 'source_arm': record.get('variant', 'joint_v2'),
            'scope': record.get('scope'), 'stage': record.get('stage'), 'source_status': record.get('status', 'completed'),
            'round': e['round'], 'attempt': e['attempt'], 'event_id': e['record_id'],
            'proposal_id': nominations[0]['record_id'], 'initial_team': sorted(nominations[0]['team']),
            'revision_index': nominations.index(e), 'lock_event_id': events[lock_seq - 1]['record_id'] if lock_seq else None,
            'locked': locked, 'lock_evidence': 'explicit_TEAM_LOCK' if lock else
                'implicit_team_fixed_on_vote_phase' if vote_decision else 'revealed_TEAM_VOTE' if vote else 'unavailable',
            'focal_proposer': e['actor'] == record.get('observer_id'),
            'event_kind': e['kind'], 'proposer': e['actor'], 'proposer_role': truth[e['actor']],
            'team': sorted(e['team']), 'evil_members_offline': sum(truth[p] in EVIL_ROLES for p in e['team']),
            'clean_team_offline': all(truth[p] not in EVIL_ROLES for p in e['team']),
            'final_before_vote': final, 'vote_event_id': vote.get('record_id') if vote else None,
            'approved': vote.get('approved') if vote else None, 'executed': mission is not None,
            'mission_event_id': mission.get('record_id') if mission else None,
            'mission_success': mission.get('success') if mission else None,
            'public_fail_count': mission.get('fail_count') if mission else None,
            'fail_threshold': mission.get('fail_threshold') if mission else None,
            'terminal_reason': result.get('reason'), 'winner': result.get('winner'),
            'path': 'revised_away' if not final else 'unvoted_partial' if not vote else
                    'rejected' if not vote['approved'] else 'approved_unexecuted_partial' if not mission else
                    'executed_success' if mission['success'] else 'executed_fail'}


def hindsight_ballot(view, players, revealed_votes, own_action):
    """Host-only local substitution through Game.vote, never a policy feature."""
    g = Game([Player(**p) for p in players], seed=0, direction=view['speaking_direction'])
    g.phase = 'vote'; g.round = view['round']; g.attempt = view['attempt']; g.team = list(view['team'])
    g.successes = view['successes']; g.failures = view['failures']; g.resolve = dict(view['resolve'])
    g.leader_index = g.ids.index(view['leader'])
    votes = dict(revealed_votes); votes[view['self']] = own_action['approve']
    strong = dict.fromkeys(g.ids, False); strong[view['self']] = own_action['strong']
    g.vote(votes, strong=strong)
    event = next(e for e in g.events if e['kind'] == 'TEAM_VOTE')
    return {'approved': event['approved'], 'phase': g.phase, 'winner': g.winner,
            'self_resolve_after': g.resolve[view['self']]}


def fixed_vote_situations(plan, jobs, records):
    lookup = {(j['experiment'], j['scenario_id'], j['variant']): j for j in jobs}
    for spec in plan['fixed']:
        if spec['phase'] != 'vote': continue
        arms = ('joint_v1', 'joint_v2') if spec['experiment'] == 'A' else ('policy_current', 'policy_candidate')
        a, b = [lookup.get((spec['experiment'], spec['scenario_id'], arm), {}) for arm in arms]
        if not a.get('context'): continue
        c = a['context']; v = c['view']; record = records[spec['source_game_id']]
        actual = next((e for e in record['events'] if e['kind'] == 'TEAM_VOTE'
            and (e['round'], e['attempt']) == (v['round'], v['attempt'])), None)
        missions = [e for e in record['events'] if e['kind'] == 'MISSION' and
                    (e['round'], e['attempt']) == (v['round'], v['attempt'])]
        query = next(q for q in c['joint_team_queries'] if set(q['team']) == set(v['team']))
        other_yes = sum(val for p, val in actual['votes'].items() if p != v['self']) if actual else None
        valid = a.get('status') == b.get('status') == 'completed'
        ca, cb = (a['action'], b['action']) if valid else ({}, {})
        current_branch = hindsight_ballot(v, record['players'], actual['votes'], ca) if actual and valid else None
        candidate_branch = hindsight_ballot(v, record['players'], actual['votes'], cb) if actual and valid else None
        current_approved = current_branch['approved'] if current_branch else None
        candidate_approved = candidate_branch['approved'] if candidate_branch else None
        ids = [p['id'] for p in v['players']]; step = 1 if v['speaking_direction'] == 'clockwise' else -1
        nxt = ids[(ids.index(v['leader']) + step) % len(ids)]
        yield {'experiment': spec['experiment'], 'scenario_id': spec['scenario_id'], 'source_game_id': spec['source_game_id'],
            'snapshot_id': spec['snapshot_id'], 'observer_id': v['self'], 'observer_role': v['role'],
            'source_cluster': spec['source_game_id'], 'status': 'completed' if valid else 'partial',
            'round': v['round'], 'attempt': v['attempt'], 'successes': v['successes'], 'failures': v['failures'],
            'team': sorted(v['team']), 'clean_probability': query['clean_probability'],
            'mission_failure_probability': query['mission_failure_probability'],
            'uniform_next_team_failure': sum(q['mission_failure_probability'] for q in c['joint_team_queries']) / len(c['joint_team_queries']),
            'remaining_rejections_before_terminal': v['rules']['max_proposals'] - v['attempt'],
            'next_leader': nxt, 'observer_is_next_leader': nxt == v['self'], 'self_resolve': v['resolve'][v['self']],
            'reference_approve': ca.get('approve'), 'candidate_approve': cb.get('approve'),
            'reference_strong': ca.get('strong'), 'candidate_strong': cb.get('strong'),
            'approve_changed': ca.get('approve') != cb.get('approve') if valid else None,
            'strong_changed': ca.get('strong') != cb.get('strong') if valid else None,
            'same_posterior': a.get('posterior_hash') == b.get('posterior_hash') if valid else None,
            'same_legal_view': a.get('legal_view_hash') == b.get('legal_view_hash') if valid else None,
            'other_actual_approvals': other_yes, 'source_ballots_pivotal': other_yes == v['required_approvals'] - 1 if actual else None,
            'source_ballots_reference_approved': current_approved, 'source_ballots_candidate_approved': candidate_approved,
            'source_ballots_approval_flipped': current_approved != candidate_approved if actual and valid else None,
            'hindsight_reference_branch': current_branch, 'hindsight_candidate_branch': candidate_branch,
            'source_actual_approved': actual['approved'] if actual else None,
            'source_actual_mission_success': missions[0]['success'] if missions else None,
            'proposed_team_clean_offline': a.get('proposed_team_clean_offline'),
            'risk_stratification': 'continuous risk only; no outcome-chosen bins', 'evidence_level': 'derived',
            'counterfactual_limit': 'Production Game.vote, one ballot substitution with other source ballots fixed; no later game outcome'}


def lcp(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y: break
        n += 1
    return n


def align_pair(a, b):
    """First divergences plus later same-coordinate descriptive comparisons.

    A common seed does not keep later information equal. No forced alignment
    by array offset is used after the structured decision coordinates differ.
    """
    ad, bd = a['decisions'], b['decisions']; ae, be = a['public_events'], b['public_events']
    key = lambda d: (d['round'], d['attempt'], d['phase'], d['observer_id'], d['occurrence'])
    coord_prefix = lcp([key(d) for d in ad], [key(d) for d in bd])
    legal_prefix = lcp([(key(d), d['legal_information_hash']) for d in ad], [(key(d), d['legal_information_hash']) for d in bd])
    raw_prefix = lcp([(key(d), d['action']) for d in ad], [(key(d), d['action']) for d in bd])
    semantic_prefix = lcp([(key(d), d['semantic_action']) for d in ad], [(key(d), d['semantic_action']) for d in bd])
    mechanical_prefix = lcp([s['mechanical_hash'] for s in a['mechanical_states']], [s['mechanical_hash'] for s in b['mechanical_states']])
    semantic_branch = None
    model_ad = [d for d in ad if d.get('was_model_requested')]
    model_bd = [d for d in bd if d.get('was_model_requested')]
    model_hash = lambda d: d.get('request_payload_hash') or d.get('model_context_hash')
    model_prefix = lcp([(key(d), model_hash(d)) for d in model_ad], [(key(d), model_hash(d)) for d in model_bd])
    model_branch = None
    if model_prefix < min(len(model_ad), len(model_bd)):
        da, db = model_ad[model_prefix], model_bd[model_prefix]
        same_env = key(da) == key(db) and da['legal_information_hash'] == db['legal_information_hash']
        model_branch = {'model_sequence_index': model_prefix, 'reference_index': da['decision_index'],
            'candidate_index': db['decision_index'], 'observer_id': da['observer_id'], 'phase': da['phase'],
            'is_focal': da.get('is_focal'), 'actual_model_seat': da.get('is_model_seat'),
            'classification': 'environment_or_history_difference' if not same_env else
                'payload_serialization_difference' if da.get('model_context_hash') == db.get('model_context_hash') else 'belief_or_context_treatment',
            'full_request_hash_available': bool(da.get('request_payload_hash') and db.get('request_payload_hash')),
            'same_legal_information': same_env, 'same_posterior': da.get('original_posterior_hash') == db.get('original_posterior_hash')}
    if semantic_prefix < min(len(ad), len(bd)):
        da, db = ad[semantic_prefix], bd[semantic_prefix]
        semantic_branch = {'index': semantic_prefix, 'coordinates_equal': key(da) == key(db),
            'reference': {k: da[k] for k in ('phase', 'observer_id', 'round', 'attempt', 'action', 'status')},
            'candidate': {k: db[k] for k in ('phase', 'observer_id', 'round', 'attempt', 'action', 'status')},
            'same_legal_information': da['legal_information_hash'] == db['legal_information_hash'],
            'same_mechanical_state': da['mechanical_hash'] == db['mechanical_hash']}
        semantic_branch['is_focal'] = da.get('is_focal')
    aligned = []; by_key = {key(d): d for d in bd}
    for da in ad:
        db = by_key.get(key(da))
        if db is None: continue
        aligned.append({'reference_index': da['decision_index'], 'candidate_index': db['decision_index'],
            'observer_id': da['observer_id'], 'observer_role': da['observer_role'],
            'phase': da['phase'], 'round': da['round'], 'attempt': da['attempt'], 'occurrence': da['occurrence'],
            'same_legal_information': da['legal_information_hash'] == db['legal_information_hash'],
            'same_mechanical_state': da['mechanical_hash'] == db['mechanical_hash'],
            'raw_action_changed': da['action'] != db['action'], 'semantic_action_changed': da['semantic_action'] != db['semantic_action'],
            'same_original_posterior': da.get('original_posterior_hash') == db.get('original_posterior_hash'),
            'same_model_context': da.get('model_context_hash') == db.get('model_context_hash')
                if da.get('was_model_requested') and db.get('was_model_requested') else None,
            'both_were_model_requests': bool(da.get('was_model_requested') and db.get('was_model_requested')),
            'same_request_payload_hash': da.get('request_payload_hash') == db.get('request_payload_hash')
                if da.get('request_payload_hash') and db.get('request_payload_hash') else None,
            'reference_action': da['action'], 'candidate_action': db['action'],
            'reference_status': da['status'], 'candidate_status': db['status'],
            'alignment': 'common_information' if da['legal_information_hash'] == db['legal_information_hash'] else
                         'coordinate_only_after_information_divergence'})
    return {'reference_trajectory': a['meta']['trajectory_id'], 'candidate_trajectory': b['meta']['trajectory_id'],
        'common_public_event_prefix': lcp(ae, be), 'common_structured_event_prefix': lcp([semantic(e) for e in ae], [semantic(e) for e in be]),
        'common_coordinate_prefix': coord_prefix, 'common_legal_information_decisions': legal_prefix,
        'raw_action_prefix': raw_prefix, 'semantic_action_prefix': semantic_prefix,
        'model_context_prefix': model_prefix, 'first_input_difference': model_branch,
        'mechanical_state_prefix_commits': mechanical_prefix,
        'mechanical_branch': {'reference': a['mechanical_states'][mechanical_prefix], 'candidate': b['mechanical_states'][mechanical_prefix]}
            if mechanical_prefix < min(len(a['mechanical_states']), len(b['mechanical_states'])) else None,
        'semantic_branch': semantic_branch,
        'reference_decisions': len(ad), 'candidate_decisions': len(bd),
        'common_prefix_note': 'Exact legal input includes public prose; structured semantic comparison removes only prose/team order.'}, aligned


def reliability_tables(source, jobs):
    calls = []; unmatched = []
    for p in sorted((source / 'requests').glob('*.request.json')):
        request = json_read(p); response = p.with_name(p.name.replace('.request.json', '.response.json'))
        r = json_read(response) if response.exists() else {**request, 'accepted': False, 'usage_status': 'unavailable', 'error': 'outcome_unknown'}
        if r['run_id'] != source.name: raise ValueError('Foreign request run_id')
        calls.append(r)
        if not response.exists(): unmatched.append(r['attempt_uid'])
    by_decision = defaultdict(list)
    for c in calls: by_decision[c['decision_id']].append(c)
    for cs in by_decision.values(): cs.sort(key=lambda c: c['retry_index'])
    attempts = []; decisions = []
    for did, cs in sorted(by_decision.items()):
        recovered = any(c.get('accepted') for c in cs)
        decisions.append({'decision_id': did, 'scenario_id': cs[0]['scenario_id'], 'experiment': cs[0]['experiment'],
            'variant': cs[0]['variant'], 'observer_role': cs[0]['observer_role'], 'phase': cs[0]['phase'],
            'first_valid': bool(cs[0].get('accepted')), 'eventual_valid': recovered, 'attempt_count': len(cs),
            'first_failure_class': cs[0].get('failure_class') if not cs[0].get('accepted') else None,
            'first_validation_reason': cs[0].get('validation_reason') if not cs[0].get('accepted') else None,
            'attempt_uids': [c['attempt_uid'] for c in cs], 'status': 'completed' if recovered else 'failed_or_unresolved'})
        for c in cs:
            attempts.append({k: c.get(k) for k in ('decision_id', 'attempt_uid', 'scenario_id', 'experiment', 'variant', 'observer_role',
                'phase', 'retry_index', 'transport_retries_used', 'corrections_used', 'accepted', 'error', 'validation_reason',
                'failure_class', 'usage_status', 'estimated_cny', 'budget_charged_cny', 'normalization')} | {
                'recovered_decision': recovered, 'request_sha256': c.get('transport', {}).get('request_sha256'),
                'context_hash': c.get('context_hash'), 'model_context_hash': c.get('model_context_hash'),
                'canonical_model_context_hash_verified': c.get('model_context_hash') == digest(c.get('context')),
                'reserved_cny': c.get('reservation', {}).get('cny'),
                'pending': c['attempt_uid'] in unmatched,
                'known_peak_minus_period_estimate_cny': c.get('budget_charged_cny', 0) - c['estimated_cny'] if c.get('estimated_cny') is not None else None,
                'raw_response': c.get('transport', {}).get('response_content') if not recovered else None,
                'finish_reason': c.get('transport', {}).get('finish_reason')})
    repeats = []
    for r in jobs:
        if r['scope'] != 'fixed_repeat': continue
        original = next((j for j in jobs if j['experiment'] == 'A' and j.get('snapshot_id') == r['snapshot_id'] and j['variant'] == 'joint_v2'), {})
        rc = next((c for c in calls if c['scenario_id'] == r['scenario_id'] and c['retry_index'] == 0), None)
        oc = next((c for c in calls if c['scenario_id'] == original.get('scenario_id') and c['variant'] == 'joint_v2' and c['retry_index'] == 0), None)
        valid = r.get('status') == original.get('status') == 'completed'
        equal_fields = {field: r.get(field) == original.get(field) and r.get(field) is not None
                        for field in ('legal_view_hash', 'posterior_hash', 'menu_hash', 'model_context_hash')}
        repeats.append({'snapshot_id': r['snapshot_id'], 'source_game_id': r['source_game_id'], 'observer_role': r['observer_role'],
            'phase': r['phase'], 'repeat_index': r['repeat_index'], 'status': r['status'],
            'original_attempt_uid': oc.get('attempt_uid') if oc else None, 'repeat_attempt_uid': rc.get('attempt_uid') if rc else None,
            'independent_http_requests': independent_repeat(oc, rc),
            'identical_initial_payload': oc.get('transport', {}).get('request_sha256') == rc.get('transport', {}).get('request_sha256') if oc and rc else None,
            'equal_fields': equal_fields, 'complete_context_equal': r.get('context') == original.get('context'),
            'model_configuration_equal': bool(oc and rc and oc.get('transport', {}).get('request_sha256') == rc.get('transport', {}).get('request_sha256')),
            'raw_action_changed': r.get('action') != original.get('action') if valid else None,
            'semantic_action_changed': semantic(r.get('action')) != semantic(original.get('action')) if valid else None,
            'new_independent_scene': False, 'new_v22_model_request': False})
    return attempts, decisions, repeats


def audit_source_records(source, out, jobs, pairs, attempts, decisions):
    """Inventory requested records and reconcile redundant exports without repair."""
    names = ('report.md', 'summary.json', 'pair_manifest.jsonl', 'games.csv', 'paired_outcomes.csv',
        'fixed_snapshot_results.jsonl', 'decision_attempts.jsonl', 'llm_calls.jsonl', 'config.json',
        'dataset_manifest.json', 'source_manifest.json', 'budget.json', 'source_replays.jsonl', 'active_replays.jsonl')
    audit = json_read(out / 'source_audit.json'); inventory = json_read(out / 'source_input_manifest.json')['files']; rows = []
    for name in names:
        p = source / name
        if not p.exists():
            rows.append({'path': name, 'status': 'missing', 'valid_rows': None}); continue
        data = []
        if p.suffix == '.jsonl': data = list(read_lines(p))
        elif p.suffix == '.csv':
            with p.open() as f: data = list(csv.DictReader(f))
        elif p.suffix == '.json': data = [json_read(p)]
        missing = Counter()
        for r in data:
            for key in ('run_id', 'experiment', 'variant'):
                if key not in r: missing[key] += 1
        rows.append({'path': name, 'sha256': inventory[name]['sha256'], 'type': p.suffix[1:], 'status': 'available',
            'valid_rows': len(data) if data else None, 'run_ids': sorted({str(r['run_id']) for r in data if 'run_id' in r}),
            'arms': sorted({str(r['variant']) for r in data if 'variant' in r}), 'absent_top_level_fields': dict(missing),
            'absence_note': 'Some aggregate/corpus schemas intentionally lack row-level run_id/variant; parent manifest supplies provenance.'})
    old = json_read(source / 'summary.json'); reconstructed = { '/'.join((r['experiment'], r['scope'] + '_' + r['phase'], r['observer_role'])): r
        for r in contingencies(pairs) if r['scope'] in {'single_seat', 'whole_table'} }
    comparisons = []
    for key, row in reconstructed.items():
        ref = old['comparisons'].get(key)
        comparisons.append({'metric': key, 'available_in_original_summary': ref is not None,
            'counts_equal': bool(ref and (row['reference_numerator'], row['candidate_numerator'], row['denominator']) ==
                (ref['reference']['numerator'], ref['candidate']['numerator'], ref['reference']['denominator']))})
    for row in contingencies(pairs):
        if row['scope'] != 'fixed' or row['observer_role'] == 'ALL': continue
        key = '/'.join((row['experiment'], 'fixed_team' if row['metric'] == 'clean_team' else 'fixed_vote_approval_descriptive', row['observer_role']))
        ref = old['comparisons'].get(key)
        comparisons.append({'metric': key, 'available_in_original_summary': ref is not None,
            'counts_equal': bool(ref and (row['reference_numerator'], row['candidate_numerator'], row['denominator']) ==
                (ref['reference']['numerator'], ref['candidate']['numerator'], ref['reference']['denominator']))})
    first = sum(d['first_valid'] for d in decisions); final = sum(d['eventual_valid'] for d in decisions)
    comparisons += [{'metric': k, 'counts_equal': n == old['reliability'][k]['numerator'] and len(decisions) == old['reliability'][k]['denominator']}
                    for k, n in [('first_legal_response', first), ('eventually_legal_response', final)]]
    audit.update(requested_file_records=rows, report_reconciliation=comparisons,
        all_report_counts_checked_equal=all(r['counts_equal'] for r in comparisons),
        scoring_definitions={'single_seat_win': 'focal alignment wins', 'whole_table_win': 'GOOD alignment wins',
            'fixed_team': 'all proposed team members have GOOD alignment, independent of observer role utility',
            'vote': 'boolean approve/reject; strong spends AP but adds no vote weight; no abstention in team vote',
            'completion': 'both completed for conditional paired effects; failures/missing retained without imputation'},
        reused_historical_data=False, specification='codex_joint_belief_v2_2_optimization_plan.md')
    atomic_json(out / 'source_audit.json', audit)
    export(out, 'source_file_records', rows)
    export(out, 'report_reconciliation', comparisons)
    ledger = json_read(source / 'budget.json')
    known = math.fsum(r['estimated_cny'] for r in attempts if r['estimated_cny'] is not None)
    unknown = math.fsum(r['budget_charged_cny'] or r['reserved_cny'] for r in attempts if r['usage_status'] == 'unavailable')
    premium = math.fsum(r['known_peak_minus_period_estimate_cny'] for r in attempts if r['known_peak_minus_period_estimate_cny'] is not None)
    conservative = math.fsum(r['budget_charged_cny'] or r['reserved_cny'] for r in attempts)
    atomic_json(out / 'budget_reconciliation.json', {'source_run_id': source.name, 'source_only': True,
        'http_attempts': len(attempts), 'known_usage_estimate_cny': known, 'unknown_usage_full_reserve_cny': unknown,
        'known_peak_rate_conservatism_cny': premium, 'conservative_cny': conservative,
        'identity_residual_cny': conservative - known - premium - unknown,
        'source_ledger_difference_cny': conservative - ledger['conservative_budget_charged_cny'],
        'pending_attempts': sum(r['pending'] for r in attempts), 'unknown_usage_attempts': sum(r['usage_status'] == 'unavailable' for r in attempts),
        'new_run_live': False, 'new_run_budget_cny': None, 'new_model_usage_status': 'not_run', 'invoice': 'unavailable'})


def diagnose_basic(source, out):
    plan = json_read(source / 'dataset_manifest.json')
    jobs = [json_read(p) for p in sorted((source / 'jobs').glob('*.json'))]
    if any(j['run_id'] != source.name for j in jobs): raise ValueError('Foreign job run_id')
    if len({(j['experiment'], j['scenario_id'], j['variant']) for j in jobs}) != len(jobs): raise ValueError('Duplicate jobs')
    sources = {r['game_id']: r for r in read_lines(source / 'source_replays.jsonl')}
    active = [json_read(p) for p in sorted((source / 'active_replays').glob('*.json'))]
    export(out, 'completion_manifest', pairing(plan, jobs))
    pairs = export(out, 'paired_outcomes', pair_rows(plan, jobs))
    export(out, 'paired_contingencies', contingencies(pairs))
    export(out, 'games', [j for j in jobs if j['scope'] in {'single_seat', 'whole_table'}])
    export(out, 'team_funnel', [row for r in active for row in team_funnel(r)])
    export(out, 'fixed_vote_situations', fixed_vote_situations(plan, jobs, sources))
    # Exact legal contexts already archived by r7, for local candidate evaluation.
    export(out, 'candidate_snapshot_inputs', [{'scenario_id': j['scenario_id'], 'snapshot_id': j['snapshot_id'],
        'source_game_id': j['source_game_id'], 'observer_role': j['observer_role'], 'context': j['context'],
        'recorded_action': j.get('action'), 'posterior_hash': j['posterior_hash']}
        for j in jobs if j['experiment'] == 'B' and j['scope'] == 'fixed' and j['variant'] == 'policy_current'])
    attempts, decisions, repeats = reliability_tables(source, jobs)
    export(out, 'request_diagnostics', attempts); export(out, 'decision_reliability', decisions)
    export(out, 'repeat_diagnostics', repeats)
    audit_source_records(source, out, jobs, pairs, attempts, decisions)
    export(out, 'resource_events', [{ 'trajectory_id': r['game_id'], 'experiment': r['experiment'], 'source_arm': r['variant'],
        'scenario_id': r['scenario_id'], 'event_id': e['record_id'], 'kind': e['kind'], 'actor': e.get('actor'),
        'round': e['round'], 'attempt': e['attempt'], 'resolve_cost': e.get('resolve_cost'), 'resolve_after': e.get('resolve_after'),
        'evidence_level': 'observed', 'cost_is_error': False} for r in active for e in r['events'] if 'resolve_cost' in e])
    return plan, jobs, sources, active
