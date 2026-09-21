"""Deterministic, network-free reports from exported v2.2 diagnostic records."""
from collections import Counter, defaultdict
import hashlib
import math
from pathlib import Path

from avalon.eval.simulation import canonical, digest
from .v21_runtime import atomic_json, json_read
from .v21_reporting import ratio, cluster_delta
from .v22_diagnostics import read_lines, export, contingencies

METRICS = ('unknown_brier_score', 'unknown_log_loss', 'evil_set_probability', 'evil_set_midrank',
    'merlin_probability', 'merlin_log_loss', 'merlin_brier', 'merlin_midrank', 'merlin_top_ties',
    'configuration_log_loss', 'configuration_probability', 'configuration_midrank', 'configuration_top_ties',
    'configuration_in_top', 'configuration_unique_correct', 'configuration_tie_expected_hit')


def finalize_metadata(out):
    """Provenance, aliases and unexecuted live plan, with no live dispatcher."""
    from .v22_runner import sha, verify_source, ROOT
    from .v22_vote import CONTEXT_REVISION
    out = Path(out); config = json_read(out / 'config.json'); source = Path(config['source_run'])
    audit = json_read(out / 'source_audit.json')
    audit['v22_attachment_found_initially'] = audit.get('v22_attachment_found', False)
    audit['v22_attachment_found'] = True
    audit['spec_sha256'] = sha(out / 'codex_joint_belief_v2_2_optimization_plan.md') if (out / 'codex_joint_belief_v2_2_optimization_plan.md').exists() else None
    file_rows = []
    inventory = json_read(out / 'source_input_manifest.json')['files']
    for name, info in inventory.items():
        category = name.split('/')[0]
        if category not in {'jobs', 'requests', 'checkpoints', 'active_replays'} or not name.endswith('.json'): continue
        data = json_read(source / name); meta = data.get('identity', {}).get('metadata', data)
        required = ('view', 'marginals', 'posterior_hash') if '/contexts/' in name else (
            ('commits', 'decisions', 'identity') if name.endswith('state.json') else
            ('players', 'events', 'decisions', 'run_id') if category == 'active_replays' else
            ('run_id', 'scenario_id', 'variant', 'status') if category == 'jobs' else ('run_id', 'attempt_uid', 'decision_id'))
        missing = [k for k in required if k not in data]
        file_rows.append({'path': name, **info, 'type': 'json_object', 'valid_rows': 1,
            'run_id': meta.get('run_id'), 'run_id_scope': 'embedded' if meta.get('run_id') else 'parent checkpoint/run manifest',
            'experiment': meta.get('experiment'), 'arm': meta.get('variant'), 'missing_required_fields': missing,
            'supports': 'legal input/reconstruction' if category == 'checkpoints' else
                        'attempt/retry/cost audit' if category == 'requests' else 'outcome/trajectory/fixed snapshot audit'})
        if missing: raise ValueError('Missing required source fields: ' + name)
        if meta.get('run_id') and meta['run_id'] != source.name: raise ValueError('Foreign source run: ' + name)
    export(out, 'source_record_inventory', file_rows)
    audit['per_record_file_inventory'] = 'source_record_inventory.jsonl'
    audit['record_files_with_valid_schema'] = len(file_rows)
    audit['all_file_hash_inventory'] = 'source_input_manifest.json'
    atomic_json(out / 'source_audit.json', audit)
    config_source = json_read(source / 'config.json'); manifest = json_read(source / 'source_manifest.json')
    dims = {'adapter_revision': config_source['adapter_revision'],
        'runtime_revision': 'r7-sha256:' + manifest['sha256']['avalon/eval/v2/v21_runtime.py'],
        'rules_hash': manifest['sha256']['avalon/engine.py'],
        'model_configuration_hash': digest(config_source['settings']),
        'scenario_manifest_hash': digest(json_read(source / 'dataset_manifest.json'))}
    config['version_aliases'] = {
        name: {**dims, 'belief_revision': belief, 'policy_revision': policy, 'context_revision': context}
        for name, belief, policy, context in [
            ('r7_A_ref', 'joint_v1', 'menu-current-r1', 'r7-base-menu-context'),
            ('r7_A_candidate', 'joint_v2', 'menu-current-r1', 'r7-base-menu-context'),
            ('r7_B_candidate', 'joint_v2', 'vote-consequences-r1', 'r7-vote-decision-context'),
            ('v22_candidate', 'joint_v2', 'vote-consequences-r1', CONTEXT_REVISION)]}
    config.update(candidate_enabled=False, candidate_status='offline_prototype_validated',
        live=False, budget_cny=None, analysis_split='development/diagnostic',
        new_effect_primary='focal alignment win on new scenario-paired single-seat games, not_run',
        new_model_samples=0, status='candidate_ready_offline')
    atomic_json(out / 'config.json', config)
    # Decision table is safe metadata/actions; full posterior checkpoints and
    # host-only truth scores remain in their explicitly separate artifacts.
    decisions = []
    paid = {r['decision_id']: r for r in read_lines(out / 'request_diagnostics.jsonl') if r['retry_index'] == 0}
    for path in sorted((out / 'trajectories').glob('*/decisions.jsonl.gz')):
        for d in read_lines(path):
            d['was_model_requested'] = d.get('decision_id') in paid
            d['request_payload_hash'] = paid.get(d.get('decision_id'), {}).get('request_sha256')
            beliefs = d.pop('beliefs', {})
            for variant, b in beliefs.items():
                d[variant + '_posterior_hash'] = b['posterior_hash']
                q = next((q for q in b.get('joint_team_queries') or [] if set(q['team']) == set(d['team'])), None)
                d[variant + '_current_team_risk'] = q['mission_failure_probability'] if q else None
            d['diagnostic_tags'] = ['frozen_source_reconstruction', 'not_a_new_model_sample']
            decisions.append(d)
    export(out, 'decision_diagnostics', decisions)
    export(out, 'phase_transitions', read_lines(out / 'team_funnel.jsonl'))
    changed = {'avalon/eval/v2/v22_runner.py': 'Offline orchestration, source identity checks, network-denied CLI; reuses v2.1 functions.',
        'avalon/eval/v2/v22_replay.py': 'Production-transaction reconstruction and original-posterior checks before cross scoring.',
        'avalon/eval/v2/v22_diagnostics.py': 'Planned-pair, proposal, vote, request, repeat and cost diagnostics from r7 only.',
        'avalon/eval/v2/v22_analysis.py': 'Semantic/state alignment, belief-to-action descriptors, Merlin paths and one-candidate selection.',
        'avalon/eval/v2/v22_vote.py': 'Only behavioral candidate: default-off bounded vote branch context, unchanged legal menu and posterior.',
        'avalon/eval/v2/v22_reporting.py': 'Raw-only deterministic reports; no rerunning models or altering scores.',
        'tests/eval/test_v22.py': 'Information, attribution, production aggregation, numerical/flag and reconstruction tests.',
        'docs/joint-belief-v22.md': 'Actual offline commands, assumptions, result and live boundaries.'}
    atomic_json(out / 'change_inventory.json', {'changes': [{'path': p, 'sha256': sha(ROOT / p) if (ROOT / p).exists() else None,
        'change': 'new file', 'purpose': reason} for p, reason in changed.items()],
        'existing_r7_files_modified': [], 'production_default_changed': False,
        'source_original_files_checked_unchanged': len(manifest['sha256']),
        'candidate_surface': 'Only an optional vote input aid; no runtime replacement or forced actions'})
    live = []
    for phase, per_role, offset in [('smoke', 3, 22310000), ('main', 10, 22320000)]:
        for ri, role in enumerate(('GOOD', 'MERLIN', 'EVIL', 'ASSASSIN')):
            for i in range(per_role):
                seed = offset + ri * 100 + i
                live.append({'scenario_id': f'v22-{phase}-{seed}', 'seed': seed, 'phase': phase,
                    'scope': 'single_seat', 'focal': f'P{(ri+i)%5+1}', 'focal_role': role,
                    'profile': ('v21_heldout_a', 'v21_heldout_b')[i % 2],
                    'order': ['r7_B_candidate', 'v22_candidate'] if i % 2 == 0 else ['v22_candidate', 'r7_B_candidate'],
                    'split': 'new_engineering_smoke' if phase == 'smoke' else 'new_exploratory_test', 'status': 'not_run'})
    atomic_json(out / 'live_plan.json', {'status': 'not_run_requires_separate_authorization_and_live_wiring_review',
        'live': False, 'budget_cny': None, 'candidate_enabled_by_default': False,
        'reference': config['version_aliases']['r7_B_candidate'], 'candidate': config['version_aliases']['v22_candidate'],
        'candidate_config': json_read(out / 'offline_validation_plan.json')['config'],
        'primary_metric': 'focal alignment win; conditional completed pairs plus full plan completion accounting',
        'scenario_manifest_hash': digest(live), 'scenarios': live,
        'fixed_snapshots_first': 'Use new controlled source games; freeze legal snapshot list before first paid response.',
        'engineering_gate': 'All smoke games complete with original menu legality and transaction/state checks; independent of win rates.',
        'statistics': 'source-game/scenario clusters, role strata, both directions retained, no outcome-driven expansion',
        'shared_budget': 'A newly authorized single cap must cover all stages, retries, corrections, unknown usage and pending attempts.',
        'required_existing_components': ['v21_runtime.MenuClient', 'Session', 'DurableBudget', 'v21_runner'],
        'remaining_integration': 'This delivery provides a pure context builder and offline prototype. A later paid run must explicitly wire that builder into the existing request logging path and freeze its hash; this offline CLI cannot dispatch live calls.'})
    atomic_json(out / 'source_readonly_verification.json', verify_source(source, out, True))


def cross_replay_metrics(out, games):
    game_meta = {r['game_id']: r for r in games}
    units = []
    for path in sorted((out / 'trajectories').glob('*/belief_trace.jsonl.gz')):
        group = defaultdict(list)
        for r in read_lines(path): group[r['observer_id'], r['variant'], r['point']].append(r)
        for (_, _, point), rows in group.items():
            first = rows[0]; game = game_meta.get(first['trajectory_id'], {})
            unit = {k: first[k] for k in ('trajectory_id', 'corpus', 'source_arm', 'scenario_id', 'experiment', 'scope', 'observer_id', 'observer_role', 'variant')}
            unit.update(stage=game.get('stage', 'diagnostic_source'), point=point, within_observer_states=len(rows))
            unit.update(source_completion=game.get('status', 'completed'), is_focal=first['observer_id'] == game.get('focal_id'))
            for m in METRICS:
                values = [r[m] for r in rows if r.get(m) is not None]
                unit[m] = math.fsum(values) / len(values) if values else None
            units.append(unit)
    export(out, 'cross_replay_units', units)
    groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in units:
        for m in METRICS:
            if r[m] is not None:
                for cohort in (('all_role_observers', 'focal_observer') if r['is_focal'] else ('all_role_observers',)):
                    group = (r['corpus'], r['experiment'], r['scope'], r['stage'], r['source_arm'], r['observer_role'],
                             r['point'], m, r['source_completion'], cohort)
                    groups[group][r['trajectory_id'], r['scenario_id']][r['variant']].append(r[m])
    summary = []
    for key, by_game in sorted(groups.items()):
        values = [(scenario if key[0] == 'active' else tid,
                   math.fsum(v['joint_v1']) / len(v['joint_v1']), math.fsum(v['joint_v2']) / len(v['joint_v2']))
                  for (tid, scenario), v in by_game.items() if 'joint_v1' in v and 'joint_v2' in v]
        stats = cluster_delta(values)
        summary.append(dict(zip(('corpus', 'experiment', 'scope', 'stage', 'source_arm', 'observer_role', 'point', 'metric', 'source_completion', 'cohort'), key)) | {
            'trajectory_pairs': len(values), 'independent_clusters': stats['paired_clusters'],
            'v1_mean': stats['reference']['value'], 'v2_mean': stats['candidate']['value'],
            'delta': stats['delta'], 'ci95': stats['ci95'], 'interpretation': stats['status'],
            'weighting': 'average states within observer, then same-role seats within source game; scenario clusters; source arms reported separately',
            'evidence_level': 'derived', 'analysis_split': 'development/diagnostic'})
    return export(out, 'cross_replay_metrics', summary)


def runtime_summary(attempts, decisions):
    first_failed = [r for r in decisions if not r['first_valid']]
    by_phase = defaultdict(list)
    for d in decisions: by_phase[d['phase']].append(d)
    retries = Counter(); grouped = defaultdict(list)
    for r in attempts: grouped[r['decision_id']].append(r)
    for rows in grouped.values():
        rows.sort(key=lambda r: r['retry_index'])
        for before, after in zip(rows, rows[1:]):
            if after['transport_retries_used'] > before['transport_retries_used']: retries['transport'] += 1
            elif after['corrections_used'] > before['corrections_used']: retries['output_correction'] += 1
            else: retries['unclassified'] += 1
    return {'http_attempts': len(attempts), 'logical_model_decisions': len(decisions),
        'first_valid': ratio(sum(d['first_valid'] for d in decisions), len(decisions)),
        'eventual_valid': ratio(sum(d['eventual_valid'] for d in decisions), len(decisions)),
        'first_failure_classes': dict(Counter(d['first_failure_class'] for d in first_failed)),
        'all_failed_attempt_classes': dict(Counter(r['failure_class'] for r in attempts if not r['accepted'])),
        'retry_http_attempts': sum(r['retry_index'] > 0 for r in attempts), 'retry_types': dict(retries),
        'first_failure_by_phase': {p: {'first_failure': ratio(sum(not r['first_valid'] for r in rs), len(rs)),
            'categories': dict(Counter(r['first_failure_class'] for r in rs if not r['first_valid']))} for p, rs in sorted(by_phase.items())},
        'unrecovered_decisions': [d for d in decisions if not d['eventual_valid']],
        'unrecovered_attempts': [r for r in attempts if not r['recovered_decision']],
        'new_model_calls': {'status': 'not_run', 'count': 0}, 'r7_output_actions_repaired': False}


def funnel_summary(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[r['experiment'], r['source_arm'], r['scope'], r['stage']].append(r)
    result = {}
    for key, rs in sorted(groups.items()):
        locked = [r for r in rs if r['locked']]
        clean = [r for r in locked if r['clean_team_offline']]
        executed = [r for r in rs if r['executed']]
        good_led = [r for r in rs if r['proposer_role'] not in {'EVIL', 'ASSASSIN'}]
        focal_good = [r for r in good_led if r['focal_proposer']]
        dirty = [r for r in executed if not r['clean_team_offline']]
        result['/'.join(key)] = {'good_led_proposed_clean': ratio(sum(r['clean_team_offline'] for r in good_led), len(good_led)),
            'focal_good_led_proposed_clean': ratio(sum(r['clean_team_offline'] for r in focal_good), len(focal_good)),
            'clean_locked_approved': ratio(sum(r['approved'] is True for r in clean), len(clean)),
            'executed_clean': ratio(sum(r['clean_team_offline'] for r in executed), len(executed)),
            'dirty_executed_success': ratio(sum(r['mission_success'] is True for r in dirty), len(dirty)),
            'paths': dict(Counter(r['path'] for r in rs)), 'unit': 'team version / locked proposal / executed mission as named; never multiply these ratios'}
    return result


def aggregate(out):
    out = Path(out); config = json_read(out / 'config.json')
    if config['live'] or config['budget_cny'] is not None: raise ValueError('Offline report only')
    load = lambda name: list(read_lines(out / (name + '.jsonl')))
    completion = load('completion_manifest'); pairs = load('paired_outcomes'); games = load('games')
    cells = export(out, 'paired_contingencies', contingencies(pairs))
    for r in cells:
        if sum(r[k] for k in ('both_zero', 'zero_to_one', 'one_to_zero', 'both_one')) != r['complete_pairs']:
            raise ValueError('Paired cells do not sum to completed pairs')
        if r['zero_to_one'] - r['one_to_zero'] != r['candidate_numerator'] - r['reference_numerator']:
            raise ValueError('Paired net wins identity failed')
    attempts = load('request_diagnostics'); decisions = load('decision_reliability'); repeats = load('repeat_diagnostics')
    runtime = runtime_summary(attempts, decisions); atomic_json(out / 'runtime_diagnostics.json', runtime)
    valid_repeats = [r for r in repeats if r['status'] == 'completed' and r['independent_http_requests'] and
                     r['complete_context_equal'] and all(r['equal_fields'].values()) and r['identical_initial_payload']]
    repeat = {'repeat_jobs': len(repeats), 'valid_same_input_independent_requests': len(valid_repeats),
        'mechanical_consistency': ratio(sum(not r['semantic_action_changed'] for r in valid_repeats), len(valid_repeats)),
        'unique_snapshots': len({r['snapshot_id'] for r in repeats}), 'source_games': len({r['source_game_id'] for r in repeats}),
        'by_role': {role: ratio(sum(not r['semantic_action_changed'] for r in valid_repeats if r['observer_role'] == role),
            sum(r['observer_role'] == role for r in valid_repeats)) for role in sorted({r['observer_role'] for r in repeats})},
        'independent_new_scenarios': 0, 'evidence_level': 'observed', 'limit': 'Small repeat coverage; no proof of provider determinism'}
    atomic_json(out / 'repeatability.json', repeat)
    metrics = cross_replay_metrics(out, games)
    merlin = load('merlin_failure_paths'); votes = load('fixed_vote_situations'); divergence = load('trajectory_divergences')
    by_pair = {(r['experiment'], r['scenario_id']): r for r in divergence}
    cases = []
    for r in pairs:
        if r['scope'] == 'fixed': continue
        diff = by_pair.get((r['experiment'], r['scenario_id']), {}); branch = diff.get('semantic_branch') or {}
        category = ('incomplete' if not r['fully_paired'] else 'unfavorable' if r['reference_value'] > r['candidate_value'] else
                    'favorable' if r['reference_value'] < r['candidate_value'] else 'same_outcome')
        cases.append({k: r[k] for k in ('experiment', 'scenario_id', 'scope', 'phase', 'observer_role', 'reference_value', 'candidate_value',
            'reference_terminal_reason', 'candidate_terminal_reason')} | {'category': category,
            'first_semantic_branch': branch, 'first_input_difference': diff.get('first_input_difference'),
            'same_information_at_semantic_branch': branch.get('same_legal_information'),
            'evidence_level': 'observed/derived; not causal attribution'})
    export(out, 'case_review', cases)
    b_votes = [r for r in votes if r['experiment'] == 'B']; changes = [r for r in b_votes if r['approve_changed']]
    oracle = json_read(out / 'candidate_validation.json') if (out / 'candidate_validation.json').exists() else {'status': 'not_run'}
    merlin_groups = defaultdict(list)
    for r in merlin:
        if r['focal_is_merlin']: merlin_groups[r['experiment'], r['scope'], r['stage'], r['source_arm']].append(r)
    terminal = {}
    for k, rs in sorted(merlin_groups.items()):
        opportunities = [r for r in rs if r['assassination_available']]
        terminal['/'.join(k)] = {'games': len(rs), 'paths': dict(Counter(r['failure_path'] for r in rs)),
            'assassinated_conditional': ratio(sum(r['terminal_reason'] == 'merlin_assassinated' for r in opportunities), len(opportunities)),
            'opportunity_selection_warning': 'Opportunity set can change with policy; not a causal skill effect'}
    analyses = {'planned_arms': sum(len(r['planned_order']) for r in completion),
        'completed_arms': sum(r['completed_arms'] for r in completion),
        'arm_states': dict(Counter(s for r in completion for s in r['arm_statuses'].values())),
        'active_games_completed': ratio(sum(r['status'] == 'completed' for r in games), len(games)),
        'active_pairs_completed': ratio(sum(r['fully_paired'] for r in pairs if r['scope'] in {'single_seat', 'whole_table'}),
                                       sum(r['scope'] in {'single_seat', 'whole_table'} for r in pairs)),
        'fixed_pairs_completed': ratio(sum(r['fully_paired'] for r in pairs if r['scope'] == 'fixed'), sum(r['scope'] == 'fixed' for r in pairs)),
        'incomplete_pairs': [r for r in pairs if not r['fully_paired']]}
    audits = load('trajectory_audit')
    links = [r for r in load('belief_action_link') if r['corpus'] == 'active']
    sensitivity = {role: {'posterior_differs': ratio(sum(r['posterior_tv'] > 1e-12 for r in links if r['observer_role'] == role),
        sum(r['observer_role'] == role for r in links)), 'unit': 'strategic predecision states, descriptive and correlated'}
        for role in sorted({r['observer_role'] for r in links})}
    summary = {'run_id': config['run_id'], 'source_run_id': config['source_run_id'], 'live': False, 'budget_cny': None,
        'status': 'candidate_ready' if oracle.get('status') == 'passed' else 'diagnosed',
        'scope': 'All r7 material is diagnostic/development, including originally held-out source games',
        'source': json_read(out / 'source_audit.json'), 'completion': analyses, 'paired_contingencies': cells,
        'runtime': {k: v for k, v in runtime.items() if k not in {'unrecovered_attempts'}}, 'repeatability': repeat,
        'budget_reconciliation': json_read(out / 'budget_reconciliation.json'),
        'trajectory_reconstruction': {'trajectories': len(audits), 'all_passed': all(a['status'] == 'passed' for a in audits),
            'active_trajectories': sum(a['corpus'] == 'active' for a in audits),
            'source_trajectories': sum(a['corpus'] == 'fixed_source' for a in audits),
            'original_full_posterior_checks': sum(a['original_posterior_hash_checks'] for a in audits),
            'original_marginal_checks': sum(a['original_marginal_checks'] for a in audits),
            'archived_fixed_posterior_checks': sum(a['fixed_snapshot_posterior_checks'] for a in audits),
            'transactions': sum(a['commits_checked'] for a in audits), 'idempotence_checks': sum(a['duplicate_checks'] for a in audits)},
        'divergences': {'pairs': len(divergence),
            'semantic_branches': sum(r.get('semantic_branch') is not None for r in divergence),
            'branches_with_same_legal_information': sum(bool(r.get('semantic_branch', {}) and r['semantic_branch']['same_legal_information']) for r in divergence),
            'mechanical_branches': sum(r.get('mechanical_branch') is not None for r in divergence),
            'interpretation': 'Earliest observed difference is not a unique cause of final outcome; later coordinate matches are descriptive only'},
        'cross_replay_primary_diagnostics': [r for r in metrics if r['corpus'] == 'active' and r['experiment'] == 'A'
            and r['scope'] == 'single_seat' and r['stage'] == 'main' and r['observer_role'] == 'GOOD'
            and r['point'] == 'endpoint' and r['metric'] in {'unknown_brier_score', 'unknown_log_loss'}
            and r['cohort'] == 'focal_observer' and r['source_completion'] == 'completed'],
        'same_trajectory_belief_sensitivity_by_role': sensitivity,
        'team_funnel': funnel_summary(load('team_funnel')), 'focal_merlin_paths': terminal,
        'A_main_unfavorable_cases': [r for r in cases if r['experiment'] == 'A' and r['scope'] == 'single_seat' and r['phase'] == 'main' and r['category'] == 'unfavorable'],
        'B_fixed_votes': {'approval_changes': ratio(len(changes), len(b_votes)),
            'hindsight_pivotal_changes': ratio(sum(r['source_ballots_approval_flipped'] for r in changes), len(changes)),
            'change_roles': dict(Counter(r['observer_role'] for r in changes)),
            'changed_attempts': dict(Counter(str(r['attempt']) for r in changes)),
            'approval_is_accuracy': False, 'future_counterfactual_outcomes': 'unavailable'},
        'selected_bottleneck': json_read(out / 'selected_bottleneck.json'), 'candidate_validation': oracle,
        'tests': config.get('tests', {}), 'new_real_model_usage': {'status': 'not_run', 'requests': 0, 'tokens': None, 'cost_cny': None},
        'new_llm_actions': 'not_run', 'new_game_effect': 'not_run', 'mechanism_effect': 'inconclusive',
        'language_evidence': 'not_run', 'recursive_tom': 'not_run', 'cross_game_memory': 'not_run'}
    atomic_json(out / 'summary.json', summary)
    write_report(out, summary)
    return summary


def write_report(out, s):
    r = s['runtime']; t = s['trajectory_reconstruction']; b = s['budget_reconciliation']
    lines = ['# Joint Belief v2.2：r7 轨迹诊断与默认关闭候选', '',
        f"本次 `{s['run_id']}` 为离线运行，来源仅 `{s['source_run_id']}`。live=false、budget_cny=null。新增模型调用、模型动作与游戏效果均 **not_run**。", '',
        '## 核验与完成状态', '',
        f"原源码快照及工作区冻结文件、配置/语料指纹与原报告哈希核验通过。所有 r7 数据已标记 diagnostic/development，未从其他历史运行补缺。{s['completion']['completed_arms']}/{s['completion']['planned_arms']} 个计划臂完成。",
        f"重建 {t['trajectories']} 条实际来源轨迹（主动 {t['active_trajectories']}、r7 自带来源游戏 {t['source_trajectories']}），生产事件一致；{t['transactions']} 个事务、{t['original_full_posterior_checks']} 次原臂完整 posterior 哈希及 {t['archived_fixed_posterior_checks']} 次快照 posterior 核验。普通来源决策只保存边际，未伪称其每步有原始完整 posterior；完整历史可重建，保存点逐一核对。", '',
        '## 配对四格（observed / derived）', '',
        '|实验/范围/阶段|双方输|仅候选赢|仅参照赢|双方赢|完整/计划|候选−参照|95% 场景区间|',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    for x in s['paired_contingencies']:
        if x['observer_role'] != 'ALL' or x['scope'] == 'fixed': continue
        lines.append(f"|{x['experiment']}/{x['scope']}/{x['phase']}|{x['both_zero']}|{x['zero_to_one']}|{x['one_to_zero']}|{x['both_one']}|{x['complete_pairs']}/{x['planned_pairs']}|{x['delta']}|{x['ci95']} ({x['interpretation']})|")
    lines += ['', '单席位以 focal 阵营胜利计分，全桌以 GOOD 阵营胜利计分。未完成臂不填成输。四格与净胜利恒等式经过检查；退化区间不证明等效。固定组队指标是整队 GOOD 阵营，属于中间属性，并非坏人角色的通用效用。', '',
        '## 相同来源轨迹的概率评分（derived）', '',
        '|实际来源臂|角色|指标|来源场景数|v1|v2|v2−v1|95% 区间|', '|---|---|---|---:|---:|---:|---:|---|']
    for x in s['cross_replay_primary_diagnostics']:
        lines.append(f"|{x['source_arm']}|{x['observer_role']}|{x['metric']}|{x['independent_clusters']}|{x['v1_mean']:.6f}|{x['v2_mean']:.6f}|{x['delta']:.6f}|{x['ci95']}|")
    lines += ['', '上表为 A 主实验单席位、focal 角色 GOOD、完成轨迹的终局揭示前未知目标评分；失败前缀另列。每观察者/来源游戏先聚合，按场景聚类；两条来源臂分别报告。决策前、每轮末、终局前的全部角色及特殊角色/joint 指标见 cross_replay_metrics.csv。禁止将不同主动轨迹当等信息实验；未进行校准提升或 entropy 必须下降的判断。', '',
        f"同一主动来源轨迹的关键决策前，v1/v2 完整 posterior 的差异按角色记录为 {s['same_trajectory_belief_sensitivity_by_role']}。这些是相关状态的描述计数，不是独立样本；不能把已知阵营角色的行动波动称为新增阵营识别能力。", '',
        '## 收益在哪些环节未出现', '',
        '完整提案链保留 proposal_id、修订前后成员、锁定、获批、执行、任务与终局。team_funnel.csv 和 phase_transitions.csv 包含未获批及中止记录，资源消耗单独保留，不自动判为错误。固定快照的干净队伍改善不能直接推出提案获批或整局收益。',
        f"B 固定投票改变 {s['B_fixed_votes']['approval_changes']['numerator']}/{s['B_fixed_votes']['approval_changes']['denominator']}；其中在固定来源其他票、通过生产 Game.vote 替换单票后，有 {s['B_fixed_votes']['hindsight_pivotal_changes']['numerator']}/{s['B_fixed_votes']['hindsight_pivotal_changes']['denominator']} 改变该次聚合结果。此 hindsight 标记仅供离线分析；未执行分支的后续胜负 unavailable。", '',
        '梅林 focal 的终局分解：', '', '|实验/范围/阶段/臂|全部路径|条件被刺中|', '|---|---|---|']
    for name, data in s['focal_merlin_paths'].items():
        rate = data['assassinated_conditional']; lines.append(f"|{name}|{data['paths']}|{rate['numerator']}/{rate['denominator']}|")
    lines += ['', 'A 单席位主实验中三组不利胜负变化（全部其他配对及不完整项亦保留在 case_review.csv）：', '',
        '|场景 / 角色|参照终局|候选终局|首次结构动作分叉|当时合法信息相同|', '|---|---|---|---|---|']
    for c in s['A_main_unfavorable_cases']:
        branch = c['first_semantic_branch']; ref = branch.get('reference', {})
        lines.append(f"|{c['scenario_id']} / {c['observer_role']}|{c['reference_terminal_reason']}|{c['candidate_terminal_reason']}|{ref.get('phase')} / {ref.get('observer_id')}|{c['same_information_at_semantic_branch']}|")
    lines += ['', '刺杀前概率、候选并列集合与实际目标保留在 merlin_failure_paths.csv / belief_action_link.csv。公开准确指控等仅是行为特征，不是经过校准的暴露概率；未改梅林表达或刺杀策略。', '',
        '## 剩余失败、重复请求与旧费用', '',
        f"首次合法 {r['first_valid']['numerator']}/{r['first_valid']['denominator']}；最终合法 {r['eventual_valid']['numerator']}/{r['eventual_valid']['denominator']}。首次失败分类 {r['first_failure_classes']}。HTTP 重试 {r['retry_http_attempts']}，拆分 {r['retry_types']}。",
        '唯一未恢复决策仍保留：两次解析错误后，最后一次 SOCIAL 带非法额外字段，耗尽既定修正次数。没有重新调用或主机修正选择。完整原响应片段与错误定位在 runtime_diagnostics.json。',
        f"同输入独立重复请求核验 {s['repeatability']['valid_same_input_independent_requests']}/{s['repeatability']['repeat_jobs']}；来自 {s['repeatability']['unique_snapshots']} 个快照、{s['repeatability']['source_games']} 个来源游戏。机械一致 {s['repeatability']['mechanical_consistency']}，不扩大独立样本，也不证明模型确定性。",
        f"r7 已知 usage 估算 ¥{b['known_usage_estimate_cny']:.8f}；峰值费率保守差额 ¥{b['known_peak_rate_conservatism_cny']:.8f}；未知 usage 全额预留 ¥{b['unknown_usage_full_reserve_cny']:.8f}；合计 ¥{b['conservative_cny']:.8f}。逐请求可归账；本轮没有继承预算、释放预留或查询账单。", '',
        '## 唯一候选与验证边界', '',
        '选定投票分支后果与有限延续辅助的探索性原型，默认关闭。现有 v2.1 DecisionContext 的事实和菜单保留；新模块只添加个人投票经未知其他投票聚合后的可达分支、AP 成本、当前及一次后续提案（最多一次任务）的模型依赖价值范围。原系统提示词、belief、证据、适配器、事务、梅林和其他阶段策略均冻结。',
        '这是 hypothesis / model_dependent 层的最小候选，尚未定位为 r7 净损失的因果根因，尤其不能修复主要梅林刺杀损失。下一队伍均匀假设、角色无关的其他投票敏感性和任务 q 明确声明；不使用真实其他票或隐藏角色，不自动替换合法模型动作。',
        f"候选离线验证：{s['candidate_validation']}。实际测试：{s['tests']}。专项与全仓测试重叠，不相加宣称独立测试数。",
        '工程通过表示 candidate_ready；新真实模型行动与游戏收益 not_run，机制效应 inconclusive。新受控来源验证是软件与信息边界验证，不能称作新 LLM 对手实验。', '',
        '## 文件与重算', '',
        'source_audit.json / source_input_manifest.json：来源、字段与哈希；selected_bottleneck.json：证据与反例；decision_diagnostics.csv：决策、输入和资源定位；phase_transitions.csv：提案链；cross_replay_metrics.csv：分层评分；trajectories/：合法初态、事件流、完整关键 posterior 与因子增量。',
        'runtime_diagnostics.json、repeatability.json、budget_reconciliation.json 保留失败、重复与旧费用。live_plan.json 是待另行授权的新计划，未启动。实际命令见 docs/joint-belief-v22.md。',
        '', '仅重算报告（无网络）：', '', '```bash',
        f'.venv/bin/python -m avalon.eval.v2.v22_runner --mode report-only --run-dir {out}', '```', '']
    (out / 'report.md').write_text('\n'.join(lines))
    (out / 'diagnosis.md').write_text('# 诊断证据层级\n\n'
        '- observed：r7 已记录动作、胜负、失败、重复与用量；不是新实验。\n'
        '- derived：生产规则重建、配对四格、原 posterior 匹配、同轨迹交叉评分、单票聚合。\n'
        '- hypothesis：分支后果/延续表达不足可能限制风险信息转化；没有证明为唯一根因。\n'
        '- model_dependent：候选的两任务阶段估计与敏感性范围。\n'
        '- unavailable/not_run：未执行替代分支终局、新 LLM 动作/胜率、真实账单、未保存步骤的原始完整 posterior。\n\n'
        '全部案例与反例保留，不只筛选不利游戏。详细计数、相互独立的效应边界和文件链接见 report.md。\n')
