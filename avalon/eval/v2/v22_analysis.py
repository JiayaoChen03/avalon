"""Cross-trajectory alignment and decision/terminal diagnostics, offline only."""
from collections import Counter, defaultdict
import math
from pathlib import Path

from avalon.engine import EVIL_ROLES
from avalon.eval.simulation import digest
from .v21_runtime import json_read, atomic_json
from .v21_reporting import cluster_delta
from .v22_diagnostics import read_lines, export, align_pair


def belief_link(d):
    a, b = (d['beliefs'][v] for v in ('joint_v1', 'joint_v2'))
    worlds = [{tuple(sorted(w['roles'].items())): w['probability'] for w in x['worlds']} for x in (a, b)]
    tv = .5 * math.fsum(abs(worlds[0].get(w, 0) - worlds[1].get(w, 0)) for w in set(worlds[0]) | set(worlds[1]))
    row = {k: d[k] for k in ('trajectory_id', 'corpus', 'source_arm', 'experiment', 'scenario_id', 'scope',
        'observer_id', 'observer_role', 'decision_index', 'phase', 'round', 'attempt', 'after_seq', 'action', 'status')}
    row.update(posterior_tv=tv, max_evil_marginal_delta=max(abs(a['marginals'][p]['evil'] - b['marginals'][p]['evil']) for p in a['marginals']),
        merlin_top_v1=a['merlin_top'], merlin_top_v2=b['merlin_top'], merlin_top_changed=a['merlin_top'] != b['merlin_top'])
    for label, x in (('v1', a), ('v2', b)):
        queries = x['joint_team_queries']
        if queries:
            minimum = min(q['mission_failure_probability'] for q in queries)
            row['best_mission_teams_' + label] = sorted(sorted(q['team']) for q in queries if abs(q['mission_failure_probability'] - minimum) < 1e-12)
            row['minimum_model_mission_risk_' + label] = minimum
            team = d['action'].get('team') if d['phase'] == 'team' and d['action'] else d['team']
            selected = next((q for q in queries if set(q['team']) == set(team)), None)
            row['chosen_team_risk_' + label] = selected['mission_failure_probability'] if selected else None
            row['chosen_team_clean_' + label] = selected['clean_probability'] if selected else None
        if d['phase'] == 'assassination' and d['action']:
            row['chosen_target_merlin_probability_' + label] = x['marginals'][d['action']['target']]['merlin']
    row['best_mission_team_set_changed'] = row.get('best_mission_teams_v1') != row.get('best_mission_teams_v2') if a['joint_team_queries'] else None
    row['risk_note'] = 'Mission proxy under frozen q, not role utility or game win probability; recorded action unchanged'
    return row


def merlin_path(record, decisions):
    truth = {p['id']: p['role'] for p in record['players']}
    merlin = next(p for p, role in truth.items() if role == 'MERLIN')
    events = record['events']; result = next((e for e in events if e['kind'] == 'RESULT'), {})
    missions = [e for e in events if e['kind'] == 'MISSION']
    own_teams = [e for e in events if e['kind'] in {'TEAM', 'TEAM_REVISE'} and e['actor'] == merlin]
    social = [e for e in events if e['kind'] == 'SOCIAL' and e['actor'] == merlin]
    votes = [e for e in events if e['kind'] == 'VOTE' and e['actor'] == merlin]
    assassin = next((d for d in decisions if d['phase'] == 'assassination' and d.get('action')), None)
    role_source = 'model' if record['scope'] == 'whole_table' or record['observer_id'] == merlin else 'controlled_opponent'
    row = {'trajectory_id': record['game_id'], 'experiment': record['experiment'], 'scenario_id': record['scenario_id'],
        'source_arm': record['variant'], 'scope': record['scope'], 'stage': record['stage'],
        'merlin': merlin, 'focal_is_merlin': record['observer_id'] == merlin, 'merlin_policy_source': role_source,
        'source_status': record['status'], 'winner': result.get('winner'), 'terminal_reason': result.get('reason'),
        'failure_path': 'incomplete' if not result else 'survived' if result['winner'] == 'GOOD' else result['reason'],
        'mission_successes': sum(e['success'] for e in missions), 'mission_failures': sum(not e['success'] for e in missions),
        'merlin_executed_teams': sum(merlin in e['team'] for e in missions),
        'merlin_proposed_clean': sum(all(truth[p] not in EVIL_ROLES for p in e['team']) for e in own_teams),
        'merlin_proposed_count': len(own_teams), 'merlin_votes': len(votes),
        'merlin_dirty_team_approvals': sum(e['approve'] and any(truth[p] in EVIL_ROLES for p in e['team']) for e in votes),
        'social_count': len(social), 'accuse_count': sum(e['card'] == 'ACCUSE' for e in social),
        'defend_count': sum(e['card'] == 'DEFEND' for e in social), 'hedge_count': sum(e['card'] == 'HEDGE' for e in social),
        'accuse_evil_offline': sum(e['card'] == 'ACCUSE' and truth[e['target']] in EVIL_ROLES for e in social),
        'defend_good_offline': sum(e['card'] == 'DEFEND' and truth[e['target']] not in EVIL_ROLES for e in social),
        'exposure_note': 'Public behavior descriptors only, not a calibrated identification probability or causal attribution',
        'assassination_available': assassin is not None}
    if assassin:
        row['assassin_policy_source'] = 'model' if record['scope'] == 'whole_table' or record['observer_id'] == assassin['observer_id'] else 'controlled_opponent'
        row['assassin_target'] = assassin['action']['target']
        for v, s in assassin['beliefs'].items():
            row[v + '_merlin_mass_at_assassin'] = s['marginals'][merlin]['merlin']
            row[v + '_merlin_top'] = s['merlin_top']
            row[v + '_merlin_in_top'] = merlin in s['merlin_top']
            row[v + '_top_ties'] = len(s['merlin_top'])
    return row


def summarize_belief(endpoints):
    metrics = ('unknown_brier_score', 'unknown_log_loss', 'configuration_log_loss',
        'configuration_tie_expected_hit', 'merlin_log_loss', 'merlin_brier')
    groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in endpoints:
        for metric in metrics:
            if row.get(metric) is not None:
                groups[row['corpus'], row['source_arm'], row['observer_role'], metric][
                    row['trajectory_id'], row['scenario_id']][row['variant']].append(row[metric])
    result = []
    for (corpus, arm, role, metric), trajectories in sorted(groups.items()):
        values = []
        for (tid, scenario), variants in trajectories.items():
            if len(variants) != 2: continue
            a, b = [math.fsum(variants[v]) / len(variants[v]) for v in ('joint_v1', 'joint_v2')]
            values.append((scenario if corpus == 'active' else tid, a, b))
        stats = cluster_delta(values)
        result.append({'corpus': corpus, 'source_arm': arm, 'observer_role': role, 'metric': metric,
            'trajectory_pairs': len(values), 'clusters': stats['paired_clusters'],
            'v1_mean': stats['reference']['value'], 'v2_mean': stats['candidate']['value'],
            'delta': stats['delta'], 'ci95': stats['ci95'], 'interpretation': stats['status'],
            'aggregation': 'mean over same-role seats within each trajectory first, then cluster by active scenario or source game',
            'direction': 'lower' if 'loss' in metric or 'brier' in metric else 'higher'})
    return result


def finish_diagnostics(out, active, plan):
    paths = list((out / 'trajectories').glob('*/audit.json'))
    audits = [json_read(p) for p in paths]
    export(out, 'trajectory_audit', audits)
    by_tid = {a['trajectory_id']: p.parent for a, p in zip(audits, paths)}
    alignment = {}; endpoints = []; links = []; merlin = []; seen_active = {}
    paid = {r['decision_id']: r for r in read_lines(out / 'request_diagnostics.jsonl') if r['retry_index'] == 0}
    for record in active:
        path = by_tid[record['game_id']]
        alignment[record['experiment'], record['scenario_id'], record['variant']] = json_read(path / 'alignment.json')
        for d in alignment[record['experiment'], record['scenario_id'], record['variant']]['decisions']:
            d['was_model_requested'] = d['decision_id'] in paid
            d['request_payload_hash'] = paid.get(d['decision_id'], {}).get('request_sha256')
        decisions = list(read_lines(path / 'decisions.jsonl.gz'))
        merlin.append(merlin_path(record, decisions))
        seen_active[record['game_id']] = record
    for path in by_tid.values():
        endpoints.extend(json_read(path / 'endpoints.json'))
        links.extend(belief_link(d) for d in read_lines(path / 'decisions.jsonl.gz') if d.get('beliefs'))
    pairs = []; rows = []
    for spec in plan['active']:
        arms = ('joint_v1', 'joint_v2') if spec['experiment'] == 'A' else ('policy_current', 'policy_candidate')
        a, b = [alignment.get((spec['experiment'], spec['scenario_id'], arm)) for arm in arms]
        meta = {k: spec[k] for k in ('experiment', 'scenario_id', 'scope', 'phase')}
        if not a or not b:
            pairs.append({**meta, 'status': 'missing_trajectory', 'reference_present': bool(a), 'candidate_present': bool(b)})
            continue
        pair, aligned = align_pair(a, b)
        pairs.append({**meta, **pair, 'status': 'available_including_partial_prefix'})
        rows.extend({**meta, **r} for r in aligned)
    export(out, 'trajectory_divergences', pairs)
    export(out, 'aligned_decisions', rows)
    export(out, 'active_vote_changes', [r for r in rows if r['experiment'] == 'B' and r['phase'] == 'vote'])
    export(out, 'merlin_failure_paths', merlin)
    export(out, 'belief_action_link', links)
    export(out, 'belief_endpoints', endpoints)
    export(out, 'belief_metrics', summarize_belief(endpoints))


def select_bottleneck(out):
    """Selection is post-diagnostic, never presented as held-out validation."""
    votes = [r for r in read_lines(out / 'fixed_vote_situations.jsonl') if r['experiment'] == 'B']
    changes = [r for r in votes if r['approve_changed']]
    merlin = [r for r in read_lines(out / 'merlin_failure_paths.jsonl') if r['focal_is_merlin'] and r['stage'] == 'main'
              and r['experiment'] == 'A' and r['scope'] == 'single_seat']
    data = {'selection_status': 'exploratory_mechanistic_gap_not_identified_root_cause',
        'selected_component': 'vote_branch_consequences_and_bounded_continuation',
        'enabled_by_default': False, 'live': False, 'budget_cny': None,
        'only_policy_change': 'Append one bounded branch comparison to existing frozen v2.1 candidate vote input; no other phase changes',
        'evidence': {'B_fixed_vote_changes': len(changes), 'B_fixed_vote_denominator': len(votes),
            'B_changes_pivotal_under_source_other_ballots': sum(bool(r['source_ballots_approval_flipped']) for r in changes),
            'B_changed_with_last_rejection': sum(r['remaining_rejections_before_terminal'] == 0 for r in changes),
            'A_main_single_seat_merlin_failure_paths': dict(Counter(r['failure_path'] for r in merlin)),
            'changed_snapshot_ids': [r['snapshot_id'] for r in changes],
            'nonpivotal_counterexamples': [r['snapshot_id'] for r in changes if not r['source_ballots_approval_flipped']],
            'source_tables': ['fixed_vote_situations.jsonl', 'active_vote_changes.jsonl', 'merlin_failure_paths.jsonl',
                'trajectory_divergences.jsonl', 'team_funnel.jsonl', 'belief_metrics.jsonl']},
        'observed_gap': 'v2.1 lists risk/facts and a uniform next-team average, but no conditional approval/rejection branch value or score-to-mission-race conversion.',
        'causal_identification': 'unavailable: observed vote changes do not identify why the model changed; alternate continuations were not executed',
        'why_minimal': 'Expose current and one additional proposal ballot, at most one mission, with pivotal conditions and the same frozen posterior; no new inference engine or model calls.',
        'not_selected': ['belief/evidence recalibration', 'Merlin expression/exposure policy', 'team proposal policy', 'output-contract retry repair'],
        'merlin_limit': 'Assassination-heavy Merlin losses are not repaired by a mission-race vote helper; no claim to fix the dominant loss path.',
        'remaining_failure': 'Keep r7 malformed-output/correction-limit failure intact; no silent repair or paid replay.',
        'validation': 'Local mechanical/property tests and fixed-posterior context exports only; new action/game benefit not_run'}
    atomic_json(out / 'selected_bottleneck.json', data)
    return data
