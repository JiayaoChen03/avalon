"""Opt-in v2 suite. Test -> frozen replay -> paired smoke -> main -> P2 -> report."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import datetime,timezone
import gzip
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

from avalon.engine import CARDS, MAX_RESOLVE, RESOLVE_COSTS, mission_rules
from avalon.eval.joint_belief import CSVOutput, ROOT, git_info, snapshot_sources, write_json
from avalon.eval.simulation import canonical, digest
from .adapters import VARIANTS, configuration
from .experiments import frozen_plan, run_scenario, run_pair_spec, replay_to_files, fixed_snapshot_actions
from .reporting import aggregate, read_csv

PRECHANGE=ROOT/'results/joint_belief_v2/20260917-prechange'
HISTORICAL=ROOT/'results/joint_belief/20260917-local500/replays.jsonl'


def tests(output,name,paths):
    print(f"Running {name}",flush=True)
    xml=output/(name+'.xml')
    env={**os.environ,'PYTHONHASHSEED':'0','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
    with (output/(name+'.log')).open('w') as log:
        result=subprocess.run([sys.executable,'-m','pytest','-q',*paths,f'--junitxml={xml}'],cwd=ROOT,
                              stdout=log,stderr=subprocess.STDOUT,env=env,check=False)
    if not xml.exists():raise RuntimeError(f'{name}: pytest did not produce XML')
    suites=list(ET.parse(xml).getroot().iter('testsuite'))
    counts={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    counts['passed']=counts['tests']-counts['failures']-counts['errors']-counts['skipped']
    counts['exit_code']=result.returncode
    print(name,counts,flush=True)
    return counts


def merge_replay_files(folders,output):
    for name in ('belief_trace.csv','mission_update_audit.csv'):
        writer=CSVOutput(output/name,['game_id','variant'])
        for folder in folders:writer.append(read_csv(Path(folder)/name))
        writer.close()
    with (output/'hypothesis_trace.jsonl.gz').open('wb') as dest:
        for folder in folders:
            with (Path(folder)/'hypothesis_trace.jsonl.gz').open('rb') as src:shutil.copyfileobj(src,dest)
    audits=[]
    for folder in folders:audits.extend(json.loads((Path(folder)/'audit.json').read_text()))
    grouped={}
    for a in audits:
        k=(a['game_id'],a['observer_id'])
        h=(a['initial_view_digest'],a['observation_stream_digest'])
        if k in grouped and grouped[k]!=h:raise ValueError('Unequal version input hashes')
        grouped[k]=h
    write_json(output/'replay_audit.json',audits)


def package(output):
    archive=output.parent/(output.name+'.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(output.rglob('*')):
            if path.is_file() and '.env' not in path.parts and '_work' not in path.parts:
                z.write(path,str(Path(output.name)/path.relative_to(output)))
    return str(archive)


def execute(args):
    if args.profile=='report_only':
        if not args.run_dir:raise ValueError('report_only requires --run-dir')
        output=args.run_dir.resolve()
        old=(output/'summary.json').read_bytes()
        summary=aggregate(output)
        identical=old==(output/'summary.json').read_bytes()
        validation=json.loads((output/'export_validation.json').read_text())
        validation['summary_byte_identical_after_reaggregation']=identical
        write_json(output/'export_validation.json',validation)
        if not identical:raise ValueError('Raw reaggregation changed summary; inspect actual diff')
        package(output)
        print(f'Report reproduced: {output}',flush=True)
        return summary
    run_id=args.run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+args.profile
    if not run_id.replace('-','').replace('_','').isalnum():raise ValueError('Invalid run id')
    output=(args.output_dir/run_id).resolve();output.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    manifest=frozen_plan(args.profile)
    prior_run=getattr(args,'correctness_rerun_of',None)
    if prior_run:
        prior_run=prior_run.resolve()
        prior_plan=json.loads((prior_run/'dataset_manifest.json').read_text())
        if any(manifest[k]!=prior_plan[k] for k in ('replay','active','policy_parameters')):
            raise ValueError('A correctness rerun must retain exactly the frozen scenarios and policies')
        manifest['correctness_rerun_of']=str(prior_run)
        manifest['test_reuse_disclosure']='Post-test numerical correctness repair; not a new independent unseen dataset or sample'
    write_json(output/'dataset_manifest.json',manifest)
    hashes=snapshot_sources(output)
    for source in (ROOT/'docs/joint-belief-v2.md',ROOT/'avalon/eval/frozen_v1/provenance.json'):
        relative=source.relative_to(ROOT);target=output/'source'/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        hashes[str(relative)]=hashlib.sha256(source.read_bytes()).hexdigest()
    # Capture exact frozen provenance and prechange evidence, excluding secrets.
    for name in ('prechange_audit.md','historical_review.json','historical_mission_audit.csv'):
        if (PRECHANGE/name).exists():shutil.copy2(PRECHANGE/name,output/name)
    for source in (ROOT/'avalon/eval/frozen_v1/provenance.json',Path('/Users/jiayaochen/Downloads/codex_joint_belief_v2_instructions.md')):
        if source.exists():shutil.copy2(source,output/('reference_'+source.name))
    write_json(output/'source_manifest.json',{'git':git_info(),'sha256':hashes,'frozen_v1':json.loads((ROOT/'avalon/eval/frozen_v1/provenance.json').read_text()),
        'prechange_manifest':json.loads((PRECHANGE/'source_manifest.json').read_text()),'candidate_default':'opt-in; production mission.enabled=False'})
    config={'suite':'joint_v2','profile':args.profile,'status':'running','started_utc':datetime.now(timezone.utc).isoformat(),
        'python':platform.python_version(),'dependencies':{p:version(p) for p in ('numpy','matplotlib','pytest')},
        'command':sys.argv,'workers':args.workers,'bootstrap_resamples':args.bootstrap_resamples,
        'variants':{v:asdict(configuration(v)) for v in VARIANTS},'rules':mission_rules(5,1),'cards':CARDS,
        'max_resolve':MAX_RESOLVE,'resolve_costs':RESOLVE_COSTS,'primary_metrics':['GOOD unknown_brier_score','GOOD unknown_log_loss'],
        'primary_split':'held_out_test','primary_comparison':'joint_v2 - joint_v1','tie_relative':1e-9,'tie_absolute':1e-12,
        'score_epsilon':1e-15,'live_belief_to_action':{'status':'not_run','reason':'no explicit opt-in; adapter not exercised'},
        'language_parser':{'status':'not_run','reason':'structured observations only'},
        'counterfactual_policy':'P2 snapshot comparison only; no alternative-policy tournament',
        'modeling_assumption':'independent flexible saboteurs q=.5, gamma=.5; not calibrated opponent probabilities',
        'tests':{}}
    if prior_run:
        config['correctness_rerun']={'prior_run':str(prior_run),
            'reason':'Constant mission log offsets perturbed exact argmax ties through rounding; skip analytically constant mission factors',
            'q_gamma_policy_scores_splits_unchanged':True,'pool_with_prior_run':False,
            'initial_config_sha256':hashlib.sha256((prior_run/'initial_config.json').read_bytes()).hexdigest()}
    write_json(output/'config.json',config)
    (output/'metrics_definitions.md').write_text('''# Frozen metric definitions

Primary: held_out_test ordinary GOOD unknown-target Brier, with binary log loss. The unknown mask comes from initial legal knowledge. Score at the last checkpoint before ASSASSINATE/RESULT, never terminal truth. First average observers within each game, then average games; paired bootstrap resamples whole games (2,000 by default). Role wins are downstream, other scores exploratory. No noninferiority margin.

Alignment uses raw marginals. Evil-set mass aggregates every matching complete world. Merlin is a multiclass distribution from native joint worlds; legacy Merlin from the separately labeled scoring projection, with original raw Merlin marginals and an additional normalized-raw log score retained. Configuration score uses all canonical assignments. Tie tolerance: relative 1e-9, absolute 1e-12. Midrank=1+higher+(tied-1)/2. Top-group membership is not unique identification. Uniform tie expected hit is 1/top_count only if truth belongs to the top group.

Only logarithmic scoring clips at epsilon=1e-15; probability exports preserve exact zero. Floor hits are exported. Unavailable denominators are null/empty, never zero scores. Entropy is descriptive; shrinking entropy is not a success criterion. Calibration bins are fixed tenths, with target count and distinct-game count, and no inference from Brier alone.

Active pairs match initial conditions and keyed random sources, not later trajectories. Single-seat focal wins and whole-table good-alignment wins are separate. Conditional rates bootstrap both numerators and denominators. P2 fixed snapshots are counterfactual action comparisons, not new wins. The original policy already uses native joint clean-team probability.

Pathology episodes count preterminal checkpoints, first event/type, sequence duration, recovery and terminal persistence; unique-game counts are separate from updates and affected targets. entropy_down_truth_down is a diagnostic, not necessarily an error. All variants receive every legal event; ablations switch weights only.
''')
    try:
        config['tests']['unit']=tests(output,'unit_tests',['tests/test_joint_beliefs.py','tests/test_cognition.py','tests/eval'])
        if config['tests']['unit']['exit_code']:raise RuntimeError('Unit gate failed')
        config['tests']['regression']=tests(output,'regression_tests',['tests'])
        if config['tests']['regression']['exit_code']:raise RuntimeError('Regression gate failed')
        write_json(output/'config.json',config)
        records=[];games=CSVOutput(output/'games.csv',['game_id','variant','scope'])
        decisions=(output/'decisions.jsonl').open('w')
        print('Generating pre-registered multi-policy corpus',flush=True)
        with (output/'replays.jsonl').open('w') as replayfile:
            if HISTORICAL.exists():
                for line in HISTORICAL.read_text().splitlines():
                    r=json.loads(line);r.update(split='historical_diagnostic',profile='transparent',scope='historical')
                    records.append(r);replayfile.write(canonical(r)+'\n')
            for i,spec in enumerate(manifest['replay']):
                row,trace,r=run_scenario(spec,'joint_v1')
                games.append([row]);records.append(r);replayfile.write(canonical(r)+'\n');replayfile.flush()
                for d in r.get('decisions',[]):decisions.write(canonical(d)+'\n')
                if row['status']!='completed':raise RuntimeError(f"Corpus generation failed, retained: {row['error']}")
                if (i+1)%10==0:print(f'Generated {i+1}/{len(manifest["replay"])}',flush=True)
        manifest['records']=[{'game_id':r['game_id'],'seed':r['seed'],'split':r['split'],'profile':r['profile'],
                              'sha256':digest(r)} for r in records]
        manifest['replays_sha256']=hashlib.sha256((output/'replays.jsonl').read_bytes()).hexdigest()
        if prior_run:
            manifest['same_frozen_corpus_after_correction']=manifest['replays_sha256']==prior_plan['replays_sha256']
            if not manifest['same_frozen_corpus_after_correction']:
                raise ValueError('Correctness rerun changed the frozen replay corpus')
        write_json(output/'dataset_manifest.json',manifest)
        print(f'Passive replay: {len(records)} games x {len(VARIANTS)} versions x 5 observers',flush=True)
        tasks=[(r,str(output/'_work'/f'{i:04d}')) for i,r in enumerate(records)]
        if args.workers==1:folders=[replay_to_files(t) for t in tasks]
        else:
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                folders=[]
                for folder in pool.map(replay_to_files,tasks):
                    folders.append(folder)
                    if len(folders)%10==0:print(f'Passive completed {len(folders)}/{len(records)}',flush=True)
        merge_replay_files(folders,output)
        # Only begin active comparisons after every passive observer passes.
        with (output/'active_replays.jsonl').open('w') as activefile:
            for phase in ('smoke','main'):
                specs=[s for s in manifest['active'] if s['phase']==phase]
                print(f'Active {phase}: {len(specs)} paired scenarios',flush=True)
                with ProcessPoolExecutor(max_workers=args.workers) as pool:
                    for i,results in enumerate(pool.map(run_pair_spec,specs)):
                        failed=False
                        for row,trace,record in results:
                            games.append([row]);activefile.write(canonical(record)+'\n');activefile.flush()
                            for d in record.get('decisions',[]):decisions.write(canonical(d)+'\n')
                            failed|=row['status']!='completed'
                        if failed:raise RuntimeError('Active correctness failure; both results retained, gate closed')
                        if (i+1)%10==0:print(f'{phase}: {i+1}/{len(specs)} pairs',flush=True)
        games.close();decisions.flush()
        print('P2: fixed legal snapshots, unchanged posterior per policy comparison',flush=True)
        for r in records:
            for d in fixed_snapshot_actions(r):decisions.write(canonical(d)+'\n')
        decisions.close()
        config.update(status='completed',wall_seconds=time.perf_counter()-started)
        write_json(output/'config.json',config)
        print('Reaggregating raw exports, drawing plots, validating paired outcomes',flush=True)
        summary=aggregate(output)
        shutil.rmtree(output/'_work')
        archive=package(output)
        print(f'Completed: {output}\nArchive: {archive}',flush=True)
        return summary
    except Exception as exc:
        config.update(status='failed',error=f'{type(exc).__name__}: {exc}',wall_seconds=time.perf_counter()-started)
        write_json(output/'config.json',config)
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=('smoke','offline_full','report_only'),default='smoke')
    parser.add_argument('--output-dir',type=Path,default=Path('results/joint_belief_v2'))
    parser.add_argument('--run-id');parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--correctness-rerun-of',type=Path,help='Record a numerical correctness repair using the exact prior scenarios; never pool samples')
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--bootstrap-resamples',type=int,default=2000)
    args=parser.parse_args(argv)
    if args.workers<1 or args.bootstrap_resamples<10:parser.error('workers >=1 and bootstrap-resamples >=10 required')
    execute(args)
