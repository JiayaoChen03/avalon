"""Offline v2.2 diagnosis. No live CLI and no API-key loading path."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import socket
import time
from unittest.mock import patch

from avalon.eval.joint_belief import ROOT, snapshot_sources, git_info
from avalon.eval.simulation import digest, canonical
from .v21_runtime import atomic_json, json_read
from .v21_runner import configuration_fingerprint
from .v22_diagnostics import diagnose_basic, read_lines
from .v22_replay import replay_trajectory
from .v22_analysis import finish_diagnostics, select_bottleneck

DEFAULT_SOURCE = ROOT / 'results/joint_belief_v2_1/20260918-v21-r7-live-75'


@contextmanager
def offline_guard():
    from avalon.llm import Settings, ChatClient
    error = RuntimeError('v2.2 offline-only: network and Settings.load are disabled')
    with patch.object(socket.socket, 'connect', side_effect=error), \
         patch.object(socket, 'create_connection', side_effect=error), \
         patch.object(socket, 'getaddrinfo', side_effect=error), \
         patch.object(Settings, 'load', side_effect=error), \
         patch.object(ChatClient, 'complete', side_effect=error):
        yield


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()


def input_inventory(source):
    return {str(p.relative_to(source)): {'sha256': sha(p), 'size': p.stat().st_size}
            for p in sorted(source.rglob('*')) if p.is_file()}


def validate_paths(source, out):
    source, out = source.resolve(), out.resolve()
    if source == out or source in out.parents or out in source.parents:
        raise ValueError('Output must be an independent directory outside the read-only source')
    return source, out


def verify_source(source, out, full=False):
    source, out = validate_paths(source, out)
    config = json_read(source / 'config.json'); manifest = json_read(source / 'source_manifest.json')
    plan = json_read(source / 'dataset_manifest.json'); startup = json_read(source / 'startup_audit.json')
    if config['run_id'] != source.name: raise ValueError('Source run_id mismatch')
    for name, expected in manifest['sha256'].items():
        if sha(source / 'source' / name) != expected or sha(ROOT / name) != expected:
            raise ValueError('Frozen r7 code changed: ' + name)
    if configuration_fingerprint(config, plan) != config['configuration_fingerprint']:
        raise ValueError('Source configuration fingerprint mismatch')
    if digest(plan) != startup['dataset_hash']: raise ValueError('Source plan hash mismatch')
    if digest(list(read_lines(source / 'source_replays.jsonl'))) != plan['source_replays_sha256']:
        raise ValueError('Source corpus canonical hash mismatch')
    if full:
        old = json_read(out / 'source_input_manifest.json')['files']
        new = input_inventory(source)
        if old != new: raise ValueError('Read-only r7 files changed since prechange audit')
    return {'status': 'passed', 'source_run_id': source.name, 'frozen_files': len(manifest['sha256']),
        'dataset_hash': digest(plan), 'configuration_fingerprint': config['configuration_fingerprint'],
        'full_input_inventory_unchanged': full, 'network_calls': 0}


def prepare(source, out):
    source, out = validate_paths(source, out); out.mkdir(parents=True, exist_ok=False)
    atomic_json(out / 'source_input_manifest.json', {'source_run': str(source),
        'scope': 'New audit-time hashes; historical_audit is hashed but not used for data', 'files': input_inventory(source)})
    atomic_json(out / 'source_audit.json', verify_source(source, out, True))
    pre = out / 'prechange'; pre.mkdir()
    hashes = snapshot_sources(pre)
    atomic_json(out / 'prechange_source_manifest.json', {'git': git_info(), 'sha256': hashes})
    atomic_json(out / 'config.json', {'run_id': out.name, 'source_run': str(source), 'source_run_id': source.name,
        'live': False, 'budget_cny': None, 'candidate_enabled': False, 'status': 'prepared',
        'bootstrap_resamples': 2000, 'bootstrap_seed': 21871,
        'new_model_samples': 0, 'attachment_status': 'Only explicit user message available; no v2.2 attachment located'})
    (out / 'prechange_audit.md').write_text(
        '# v2.2 prechange audit\n\nRead-only source: ' + str(source) + '\n\n'
        'Modules: v21_contract/runtime/runner/reporting/data; frozen_v1, v2 adapters/metrics; Game. '
        'Frozen file hashes, corpus and config verified before diagnosis. No AGENTS.md found in the repository or its parents. '
        'The explicit user message defines this task; no separate v2.2 attachment was found. '
        'v2.1 already supplies current-team risk, rejection/score/AP facts and uniform next-team risk. '
        'First audit all planned completions, common information/action/state divergences, both beliefs on each actual trajectory, '
        'team funnels, Merlin losses, B vote changes and existing repeats/failures. '
        'Only then select one disabled candidate. No API calls, no prior budget, no hidden-truth policy input.\n')


def worker(task):
    with offline_guard(): return replay_trajectory(task)


def diagnose(source, out, workers=4, resume=False):
    verify_source(source, out, full=True)
    config = json_read(out / 'config.json')
    if config.get('live') is not False or config.get('budget_cny') is not None:
        raise ValueError('This run must be offline with a null budget')
    start = time.perf_counter()
    plan, jobs, sources, active = diagnose_basic(source, out)
    saved_posteriors = {}
    specs = {(s['experiment'], s['scenario_id']): s for s in plan['fixed']}
    for j in jobs:
        if j['scope'] != 'fixed': continue
        spec = specs[j['experiment'], j['scenario_id']]
        saved_posteriors.setdefault(j['source_game_id'], {}).setdefault(spec['decision_index'], {})[
            j['belief_variant']] = j['posterior_hash']
    tasks = []
    for r in active + list(sources.values()):
        is_active = 'run_id' in r
        key = digest([r['experiment'], r['scenario_id'], r['variant']])[:24] if is_active else None
        checkpoint = source / 'checkpoints' / key / 'state.json' if key else None
        meta = {'corpus': 'active' if is_active else 'fixed_source', 'source_arm': r.get('variant', 'joint_v2'),
            'experiment': r.get('experiment', 'source'), 'scenario_id': r['scenario_id'], 'scope': r['scope'],
            'source_run_id': source.name, 'analysis_split': 'development/diagnostic'}
        path = out / 'trajectories' / digest(r['game_id'])[:24]
        if path.exists():
            if not resume: raise ValueError('Trajectory output exists; use --resume after frozen-code verification')
            if (path / 'audit.json').exists(): continue
            # Preserve incomplete diagnostics, never delete source or user files.
            path.rename(path.with_name(path.name + '-incomplete-' + datetime.now(timezone.utc).strftime('%H%M%S%f')))
        tasks.append((r, checkpoint, path, meta, saved_posteriors.get(r['game_id'], {})))
    replay_code = {name: sha(ROOT / 'avalon/eval/v2' / name) for name in ('v22_replay.py', 'v22_diagnostics.py', 'v22_analysis.py')}
    marker = out / 'diagnostic_code.json'
    if marker.exists() and json_read(marker) != replay_code:
        raise ValueError('Diagnostic source changed; start a separate output instead of mixing replay revisions')
    atomic_json(marker, replay_code)
    errors = []; done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(worker, t): t[0]['game_id'] for t in tasks}
        for future in as_completed(pending):
            try: future.result()
            except Exception as e:
                errors.append({'trajectory_id': pending[future], 'error': type(e).__name__ + ': ' + str(e)})
            done += 1
            if done % 10 == 0 or done == len(tasks): print(f'Offline trajectories {done}/{len(tasks)}, errors {len(errors)}', flush=True)
    atomic_json(out / 'diagnostic_errors.json', errors)
    if errors: raise ValueError(f'{len(errors)} trajectory diagnostics failed; retained in diagnostic_errors.json')
    finish_diagnostics(out, active, plan)
    select_bottleneck(out)
    atomic_json(out / 'source_readonly_verification.json', verify_source(source, out, full=True))
    config.update(status='diagnosed', diagnostic_seconds=time.perf_counter() - start, diagnostic_trajectories=len(active) + len(sources))
    atomic_json(out / 'config.json', config)


def freeze_delivery(out):
    hashes = snapshot_sources(out)
    for rel in ('docs/joint-belief-v22.md',):
        p = ROOT / rel
        if p.exists():
            dest = out / 'source' / rel; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dest)
            hashes[rel] = sha(p)
    atomic_json(out / 'source_manifest.json', {'git': git_info(), 'sha256': hashes,
        'source_run_id': json_read(out / 'config.json')['source_run_id'], 'purpose': 'Actual v2.2 delivered source; r7 unchanged'})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', required=True, choices=('prepare', 'diagnose', 'candidate', 'report-only', 'tests'))
    p.add_argument('--source-run', type=Path, default=DEFAULT_SOURCE)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--resume', action='store_true')
    a = p.parse_args(argv); source, out = validate_paths(a.source_run, a.run_dir)
    if a.workers < 1: p.error('--workers must be positive')
    with offline_guard():
        if a.mode == 'prepare': prepare(source, out)
        elif a.mode == 'diagnose': diagnose(source, out, a.workers, a.resume)
        elif a.mode == 'candidate':
            from .v22_vote import evaluate_snapshots
            from .v22_reporting import finalize_metadata
            evaluate_snapshots(out); finalize_metadata(out); freeze_delivery(out)
        elif a.mode == 'report-only':
            from .v22_reporting import aggregate
            aggregate(out)
        elif a.mode == 'tests':
            from .runner import tests
            c = json_read(out / 'config.json')
            c['tests'] = {'unit': tests(out, 'unit', ['tests/eval/test_v22.py']),
                          'regression': tests(out, 'regression', ['tests'])}
            atomic_json(out / 'config.json', c)
            if any(t['exit_code'] for t in c['tests'].values()): raise RuntimeError('Offline tests failed')


if __name__ == '__main__': main()
