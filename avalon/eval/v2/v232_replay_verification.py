"""Exact source-variant replay through production Game transactions.

No new policies are run. Truth constructs the referee Game only; each observer
is initialized from Game.view and receives public projections exclusively.
"""
from copy import deepcopy
import json
from pathlib import Path

from avalon.engine import Game, Player
from avalon.chronicle import PUBLIC_KINDS, context_record
from avalon.eval.simulation import digest
from .adapters import make_version
from .v21_contract import legal_menu, decode_menu
from .v21_runtime import json_read
from .v22_replay import source_transaction
from .v232_channel import sha256


class Mismatch(Exception):
    def __init__(self, kind, field, expected, actual, event_id=None, delta=None):
        self.detail = {'mismatch_kind': kind, 'first_mismatch_field': field,
            'expected_hash': digest(expected), 'actual_hash': digest(actual),
            'first_mismatch_event_id': event_id, 'max_abs_raw_delta': delta,
            'expected_value': expected, 'actual_value': actual}
        super().__init__(kind + ':' + field)


def equal(expected, actual, kind, field, event=None):
    if expected != actual:
        raise Mismatch(kind, field, expected, actual, event)


def seat_variant(record, pid, source_run):
    if record.get('scope') == 'generation':
        return 'joint_v2'
    arm = record.get('variant', 'joint_v2')
    focal = record.get('observer_id', record.get('focal'))
    if 'v23-r2' in source_run:
        # Reproduce the actual historical factory. In the reference arm,
        # play_game passed "reference" to all seats and it mapped to v2.
        if arm == 'reference' or pid == focal:
            return 'joint_v2'
        return 'joint_v1'
    if record.get('scope') != 'whole_table' and pid != focal:
        return 'joint_v1'
    return 'joint_v2' if arm.startswith('policy_') else arm


def verify_record(task):
    source_run, cohort, record, source_file, source_root = task
    source_file, source_root = Path(source_file), Path(source_root)
    row = {'source_run_id': source_run, 'source_file': str(source_file),
           'source_sha256': sha256(source_file), 'game_id': record.get('game_id'),
           'source_variant': record.get('variant', 'joint_v2'),
           'replay_variant': 'source_native_per_seat', 'config_hash': None,
           'verification_mode': 'production_Game_transactions_and_original_belief',
           'verification_status': 'UNVERIFIABLE', 'legal_cutoff_verified': False,
           'exclusion_reason': None, 'cutoffs': [], 'checks': {},
           'first_mismatch_event_id': None, 'first_mismatch_field': None,
           'mismatch_kind': None, 'expected_hash': None, 'actual_hash': None,
           'max_abs_raw_delta': None, 'expected_exact_top': None, 'actual_exact_top': None,
           'expected_target': None, 'actual_target': None, 'affected_snapshot_ids': '[]'}
    cursor = 0; dc = 0; checks = {'legal_views': 0, 'marginals': 0, 'full_posterior': 0,
                               'events': 0, 'commits': 0, 'probe_checks': 0}
    try:
        config_path = source_root / 'config.json'
        if not config_path.exists():
            raise Mismatch('configuration_missing', 'config.json', 'source config', None)
        cfg = json_read(config_path); row['config_hash'] = sha256(config_path)
        equal(source_run, cfg.get('run_id'), 'configuration_mismatch', 'run_id')
        if 'r7' in source_run:
            from .v21_runner import configuration_fingerprint
            equal(cfg['configuration_fingerprint'], configuration_fingerprint(cfg, json_read(source_root/'dataset_manifest.json')),
                  'configuration_mismatch', 'configuration_fingerprint')
        manifest = json_read(source_root/'source_manifest.json')
        hashes = manifest.get('sha256', manifest.get('hashes', {}))
        from avalon.eval.joint_belief import ROOT
        for name in ('avalon/engine.py', 'avalon/evidence.py', 'avalon/cognition.py',
                     'avalon/joint_beliefs.py', 'avalon/mission_likelihood.py',
                     'avalon/eval/v2/adapters.py', 'avalon/eval/v2/v21_contract.py'):
            if name not in hashes:
                raise Mismatch('configuration_missing', name, 'frozen source hash', None)
            equal(hashes[name], sha256(ROOT/name), 'configuration_mismatch', name)
        game = Game([Player(**p) for p in record['players']], seed=record['seed'], direction=record['direction'])
        native = {pid: seat_variant(record, pid, source_run) for pid in game.ids}
        observers = {pid: make_version(native[pid], game.view(pid)) for pid in game.ids}
        row['initial_legal_view_hashes'] = {pid: digest(game.view(pid)) for pid in game.ids}
        cpdir = source_root / 'checkpoints' / source_file.stem
        checkpoint = json_read(cpdir/'state.json') if (cpdir/'state.json').exists() else None
        if source_file.suffix == '.json' and not checkpoint:
            raise Mismatch('archive_missing', 'checkpoint', 'source checkpoint', None)
        events = record['events']; decisions = record.get('decisions', [])

        def flush():
            nonlocal cursor
            for e in game.events[cursor:]:
                if e['seq'] > len(events):
                    raise Mismatch('event_missing', 'events', e, None, e.get('record_id'))
                equal(events[e['seq']-1], e, 'event_projection_mismatch', 'events', e.get('record_id'))
                checks['events'] += 1
                if e['kind'] in PUBLIC_KINDS:
                    public = context_record(e)
                    for observer in observers.values():
                        observer.observe(deepcopy(public))
                cursor = e['seq']

        flush()
        while game.phase != 'ended':
            if checkpoint:
                if checks['commits'] >= len(checkpoint['commits']):
                    break
                t = checkpoint['commits'][checks['commits']]
                equal(t['action_hash'], digest([t['method'],t['args'],t['kwargs']]),
                      'archive_corrupt', 'commit.action_hash', f'after_seq:{cursor}')
            else:
                t = source_transaction(game, decisions, dc)
            for index in range(dc, t['decisions_through']):
                d = decisions[index]; pid = d['observer_id']; view = game.view(pid)
                equal((pid, game.phase, cursor), (d['observer_id'],d['phase'],d['after_seq']),
                      'event_order_mismatch', f'decisions[{index}].schedule', f'after_seq:{cursor}')
                for key, value in d['view'].items():
                    if key != 'legal_public_history':
                        equal(value, view.get(key), 'legal_projection_mismatch', f'decisions[{index}].view.{key}', f'after_seq:{cursor}')
                checks['legal_views'] += 1
                actual = observers[pid].marginals(); expected = d['marginals']
                delta = max(abs(actual[p][k]-expected[p][k]) for p in actual for k in actual[p])
                if delta != 0:
                    raise Mismatch('posterior_mismatch', f'decisions[{index}].marginals',expected,actual,f'after_seq:{cursor}',delta)
                checks['marginals'] += 1
                full_view = d['view']
                if checkpoint:
                    context_path = cpdir/'contexts'/f'{index:04d}.json'
                    if not context_path.exists():
                        raise Mismatch('archive_missing',str(context_path),'saved context',None,f'after_seq:{cursor}')
                    c = json_read(context_path); saved = checkpoint['decisions'][index]
                    equal(saved['binding']['context_hash'],digest(c),'archive_corrupt','saved_context_hash',f'after_seq:{cursor}')
                    equal(saved['binding']['state_version'],digest(c['view']),'stale_state','saved_state_hash',f'after_seq:{cursor}')
                    equal(c.get('posterior_hash'),observers[pid].snapshot()['posterior_hash'],
                          'posterior_mismatch','full_posterior_hash',f'after_seq:{cursor}')
                    equal(d['action'],saved.get('validated_action'),'decoder_result_mismatch','saved_action',f'after_seq:{cursor}')
                    full_view = c['view']; checks['full_posterior'] += 1
                    base_view = {k:v for k,v in full_view.items() if k != 'legal_public_history'}
                    equal(base_view, view, 'legal_projection_mismatch','checkpoint.view',f'after_seq:{cursor}')
                    if 'legal_public_history' in full_view:
                        from avalon.chronicle import EVIDENCE_KINDS
                        equal(full_view['legal_public_history'],[context_record(e) for e in game.events if e['kind'] in EVIDENCE_KINDS],
                              'legal_projection_mismatch','checkpoint.public_prefix',f'after_seq:{cursor}')
                if d['phase'] in {'vote','team','assassination'}:
                    before = observers[pid].snapshot()['posterior_hash']
                    # Diagnostic reads and duplicate event probes run on a copy;
                    # neither may perturb the production observer or Game.
                    probe = deepcopy(observers[pid]); last = next((context_record(e) for e in reversed(game.events) if e['kind'] in PUBLIC_KINDS),None)
                    if last: probe.observe(last)
                    equal(before, probe.snapshot()['posterior_hash'], 'probe_perturbation','duplicate_event',f'after_seq:{cursor}')
                    equal(before, observers[pid].snapshot()['posterior_hash'], 'probe_perturbation','diagnostic_read',f'after_seq:{cursor}')
                    checks['probe_checks'] += 1
                    legal = legal_menu(full_view)
                    row['cutoffs'].append({'source_run_id':source_run,'game_id':record['game_id'],
                        'decision_index':index,'observer_id':pid,'phase':d['phase'],'cutoff_seq':cursor,
                        'native_variant':native[pid],'legal_view_hash':digest(full_view),
                        'posterior_hash':before,'marginals_hash':digest(actual),
                        'legal_menu_hash':digest(legal),'public_prefix_hash':digest([context_record(e) for e in game.events if e['kind'] in PUBLIC_KINDS]),
                        'full_posterior_verified':bool(checkpoint), 'verified':True,
                        'action_hash':digest(d['action'])})
            dc = t['decisions_through']
            getattr(game,t['method'])(*t['args'],**t['kwargs'])
            checks['commits'] += 1
            flush()
        equal(record['events'],game.events,'event_order_mismatch','complete_event_stream',f'after_seq:{cursor}')
        if game.phase == 'ended':
            equal(len(decisions),dc,'uncommitted_source_decisions','decision_count',f'after_seq:{cursor}')
        row['verification_status'] = 'BASELINE_VERIFIED' if game.phase == 'ended' else 'PARTIAL_ARCHIVE_VERIFIED_PREFIX'
        row['terminal_complete'] = game.phase == 'ended'
        if game.phase != 'ended':
            row.update(mismatch_kind='archive_missing_terminal',first_mismatch_field='terminal.RESULT/REVEAL',
                       first_mismatch_event_id=f'after_seq:{cursor}',exclusion_reason='no completed terminal; verified prefixes only')
        row['legal_cutoff_verified'] = bool(row['cutoffs'])
    except Mismatch as exc:
        row.update(exc.detail, exclusion_reason=str(exc))
    except Exception as exc:
        row.update(mismatch_kind='archive_or_replay_error',first_mismatch_field=f'decision:{dc};after_seq:{cursor}',
                   first_mismatch_event_id=f'after_seq:{cursor}',exclusion_reason=f'{type(exc).__name__}: {exc}')
    row['checks'] = checks
    row['last_verified_seq'] = cursor
    return row
