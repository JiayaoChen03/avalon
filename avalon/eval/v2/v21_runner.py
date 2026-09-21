"""Joint Belief v2.1: audit, resumable action experiments and raw-only reports."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from copy import deepcopy
from dataclasses import asdict,replace
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import threading

from avalon.engine import EVIL_ROLES
from avalon.llm import Settings
from avalon.eval.joint_belief import ROOT,snapshot_sources,git_info
from avalon.eval.simulation import play_game,digest,canonical
from .adapters import make_version
from .experiments import scenario_players
from .runner import tests,package
from .v21_runtime import MenuClient,Session,DurableBudget,atomic_json,json_read,Cancelled
from .v21_contract import ADAPTER_REVISION,POLICY_CURRENT,POLICY_CANDIDATE,enrich_context,menu_context,legal_menu
from .v21_data import prepare_data,population,input_for
from .v21_audit import audit_run,load_lines,reproduce_fixture

PRECHANGE=ROOT/'results/joint_belief_v2_1/20260918-v21-prechange'
HISTORY=('20260917-deepseek-v2-contract','20260917-deepseek-v2-legal-context')
FROZEN_CORE=('avalon/engine.py','avalon/cognition.py','avalon/evidence.py','avalon/joint_beliefs.py',
             'avalon/mission_likelihood.py','avalon/eval/v2/adapters.py','avalon/agents.py','prompts/corrupted_castle_system.md')


def current_fingerprint():
    files=sorted(ROOT.glob('avalon/**/*.py'))+[ROOT/'prompts/corrupted_castle_system.md']
    return digest({str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files})


def configuration_fingerprint(config,plan):
    return digest({k:config[k] for k in ('source_fingerprint','settings','budget_cny','max_calls','adapter_revision',
        'policies','system_sha256','contract_normalization','transport_retries','schema_corrections')}|{'dataset':digest(plan)})


def verify_corpus(out,plan):
    # This manifest field hashes canonical decoded records (not NDJSON spacing).
    if digest(load_lines(out/'source_replays.jsonl'))!=plan['source_replays_sha256']:
        raise ValueError('incompatible_resume: frozen source corpus changed')


def prepare(args):
    out=args.run_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    hashes=snapshot_sources(out)
    prompt=ROOT/'prompts/corrupted_castle_system.md'
    dest=out/'source/prompts'/prompt.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(prompt,dest)
    hashes[str(prompt.relative_to(ROOT))]=hashlib.sha256(prompt.read_bytes()).hexdigest()
    for source in [ROOT/'tests/eval/fixtures/v21_menu_failures.json',ROOT/'docs/joint-belief-v21.md']:
        relative=source.relative_to(ROOT);dest=out/'source'/relative
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
        hashes[str(relative)]=hashlib.sha256(source.read_bytes()).hexdigest()
    pre=json_read(PRECHANGE/'source_manifest.json')['sha256']
    for name in FROZEN_CORE:
        if hashes[name]!=pre[name]:raise ValueError('Frozen production core changed: '+name)
    atomic_json(out/'source_manifest.json',{'git':git_info(),'sha256':hashes,'fingerprint':current_fingerprint(),
        'prechange':str(PRECHANGE),'frozen_core':FROZEN_CORE,'adapter_revision':ADAPTER_REVISION})
    shutil.copy2(PRECHANGE/'prechange_audit.md',out/'prechange_audit.md')
    for name in HISTORY:audit_run(ROOT/'results/joint_belief_v2'/name,out/'historical_audit'/name)
    if args.data_from:
        prior=json_read(args.data_from/'source_manifest.json')['sha256']
        for name in FROZEN_CORE:
            if name in prior and hashes[name]!=prior[name]:raise ValueError('Source corpus core changed')
        for name in ('source_replays.jsonl','dataset_manifest.json','source_scenario_plan.json'):
            shutil.copy2(args.data_from/name,out/name)
    else:prepare_data(out,min(args.workers,4))
    settings=replace(Settings.load(),temperature=0.,max_tokens=900)
    from .v21_runtime import MenuClient
    from .v21_contract import configure_transport
    from avalon.llm import ChatClient
    transport=configure_transport(ChatClient(settings))
    safe={k:v for k,v in asdict(settings).items() if k!='api_key'}
    config={'run_id':out.name,'created_utc':datetime.now(timezone.utc).isoformat(),'status':'prepared',
        'source_fingerprint':current_fingerprint(),'settings':safe,'budget_cny':args.budget_cny,'max_calls':args.max_calls,
        'budget_authorization':'Explicit user cap for this new run; no historic spending allowance reused',
        'adapter_revision':ADAPTER_REVISION,'policies':[POLICY_CURRENT,POLICY_CANDIDATE],
        'system_sha256':digest(transport._system_prompts[False]),
        'contract_normalization':['provider json_object metadata only','team member sort only'],
        'transport_retries':2,'schema_corrections':2,'fallback':False,'language_evidence':'not_run',
        'recursive_tom':'not_run','cross_game_memory':'not_run','tests':{},
        'B_primary':'Paired focal wins (8 scenes; exploratory), vote outcomes stratified by role/stage; no correctness label for approval',
        'request_repeats':'8 representative heldout snapshots, two additional independently sent requests each',
        'new_heldout_use':'Frozen before any model responses; no outcome-dependent sample or parameter replacement'}
    plan=json_read(out/'dataset_manifest.json');verify_corpus(out,plan)
    config['configuration_fingerprint']=configuration_fingerprint(config,plan)
    if args.tests_from:
        old=json_read(args.tests_from/'config.json')
        if old['source_fingerprint']!=config['source_fingerprint']:raise ValueError('Cannot reuse tests across source changes')
        if json_read(args.tests_from/'source_manifest.json')['sha256']!=hashes:raise ValueError('Cannot reuse gates across changed tests or source files')
        for kind in ('unit','regression'):
            if old['tests'].get(kind,{}).get('exit_code')!=0:raise ValueError('Missing passed test gate')
            config['tests'][kind]={**old['tests'][kind],'reused_from':str(args.tests_from),'reason':'Identical complete source fingerprint; same-session test results'}
            for suffix in ('xml','log'):shutil.copy2(args.tests_from/(kind+'_tests.'+suffix),out/(kind+'_tests.'+suffix))
    atomic_json(out/'config.json',config)
    (out/'frozen_system_prompt.txt').write_text(transport._system_prompts[False])
    return config


def compatible(out):
    c=json_read(out/'config.json')
    if c['source_fingerprint']!=current_fingerprint():raise ValueError('incompatible_resume: source/config/contract changed; use a new run_id')
    if c['configuration_fingerprint']!=configuration_fingerprint(c,json_read(out/'dataset_manifest.json')):raise ValueError('incompatible_resume: config or dataset changed')
    verify_corpus(out,json_read(out/'dataset_manifest.json'))
    return c


class Hybrid:
    def __init__(self,spec,live):
        self.spec=spec;self.live=live;self.other=population(spec['seed'],spec['profile'])
        self.calls=self.context_bytes=0
    def bind(self,b):self.live.bind(b)
    def complete(self,c):
        self.calls+=1;self.context_bytes+=len(canonical(c))
        return self.live.complete(c) if self.spec['scope']=='whole_table' or c['view']['self']==self.spec['focal'] else self.other.complete(c)


def arm_policy(experiment,arm):
    return ('joint_v2' if experiment=='B' else arm,
            POLICY_CANDIDATE if arm=='policy_candidate' else POLICY_CURRENT)


def job_id(spec,arm):return digest([spec['experiment'],spec['scenario_id'],arm])[:24]


def meta_for(out,spec,arm):
    return {'run_id':out.name,'experiment':spec['experiment'],'scenario_id':spec['scenario_id'],
        'source_game_id':spec.get('source_game_id'),'observer_id':spec.get('observer_id',spec.get('focal')),
        'variant':arm,'policy_revision':arm_policy(spec['experiment'],arm)[1],
        'adapter_revision':ADAPTER_REVISION,'scope':spec['scope'],'stage':spec['phase'],
        'snapshot_id':spec.get('snapshot_id'),'repeat_index':spec.get('repeat_index',0)}


def active_job(out,spec,arm,settings,budget,cancel):
    meta=meta_for(out,spec,arm);key=job_id(spec,arm);path=out/'jobs'/(key+'.json')
    if path.exists() and json_read(path)['status'] in {'completed','failed'}:return json_read(path)
    atomic_json(path,{**meta,'status':'running','started_utc':datetime.now(timezone.utc).isoformat()})
    variant,policy=arm_policy(spec['experiment'],arm)
    client=MenuClient(settings,budget,meta,policy,cancel);hybrid=Hybrid(spec,client)
    session=Session(out/'checkpoints'/key/'state.json',{'game_id':f'{out.name}:{key}','config':json_read(out/'config.json')['configuration_fingerprint'],'metadata':meta})
    def factory(v,view,_=None):return make_version('joint_v2' if v.startswith('policy_') else v,view)
    row,_,record=play_game(spec['seed'],arm,phase=f"{spec['experiment']}-{spec['phase']}-{spec['scope']}",
        model=settings.model,temperature=settings.temperature,player_setup=scenario_players(spec),focal=spec['focal'],
        all_seats=spec['scope']=='whole_table',belief_factory=factory,client_factory=lambda _:hybrid,
        capture_decisions=True,session=session,context_enricher=enrich_context)
    row.update(meta,belief_variant=variant,pair_id=spec['scenario_id'],policy_revision=policy,
        pair_signature=digest({'spec':spec,'settings':json_read(out/'config.json')['settings'],'experiment':spec['experiment']}))
    row['external_model_calls']=client.external_calls
    row['model_tokens']=None  # Report joins durable per-attempt usage, including pre-crash calls.
    if row['status']!='completed':
        if 'BudgetStop' in row['error']:row['status']='budget_stopped'
        elif 'Cancelled' in row['error']:row['status']='cancelled'
    truth={p['id']:p['role'] for p in record['players']}
    for label,kinds in [('proposed',{'TEAM','TEAM_REVISE'}),('approved',{'TEAM_VOTE'}),('executed',{'MISSION'})]:
        events=[e for e in record['events'] if e['kind'] in kinds and (label!='approved' or e['approved'])]
        row[label+'_clean_teams']=sum(all(truth[p] not in EVIL_ROLES for p in e['team']) for e in events)
        row[label+'_team_count']=len(events)
    row['rejection_terminal']=row.get('terminal_reason')=='five_rejections'
    row['checkpoint_replayed_decisions']=session.cached
    record.update(meta,status=row['status'],error=row['error'])
    atomic_json(out/'active_replays'/(key+'.json'),record)
    atomic_json(path,row);return row


def fixed_job(out,spec,arm,settings,budget,cancel,records):
    meta=meta_for(out,spec,arm);key=job_id(spec,arm);path=out/'jobs'/(key+'.json')
    if path.exists() and json_read(path)['status'] in {'completed','failed'}:return json_read(path)
    atomic_json(path,{**meta,'status':'running','started_utc':datetime.now(timezone.utc).isoformat()})
    contexts,truth,observers=input_for(spec,records);variant,policy=arm_policy(spec['experiment'],arm)
    c=contexts[variant];client=MenuClient(settings,budget,meta,policy,cancel)
    session=Session(out/'checkpoints'/key/'state.json',{'game_id':f'{out.name}:{key}','config':json_read(out/'config.json')['configuration_fingerprint'],'metadata':meta})
    row={**meta,'belief_variant':variant,'phase':spec['phase'],'observer_role':spec['observer_role'],
        'legal_view_hash':digest(c['view']),'posterior_hash':c['posterior_hash'],
        'joint_state':observers[variant].snapshot(),'context':c,'legal_menu':legal_menu(c['view']),
        'menu_hash':digest(legal_menu(c['view'])),'model_context_hash':digest(menu_context(c,policy)),
        'status':'completed','error':None,'executed_action':None,'counterfactual':'not executed in source game'}
    try:
        row['action']=session.choose(c,client)
        if spec['phase']=='team':
            row['clean_team']=int(all(truth[p] not in EVIL_ROLES for p in row['action']['team']))
            row['legal_clean_team_exists']=any(all(truth[p] not in EVIL_ROLES for p in m['action']['team']) for m in row['legal_menu'])
        elif spec['phase']=='vote':
            row['approve']=int(row['action']['approve']);row['strong']=int(row['action']['strong'])
            row['last_chance']=c['view']['attempt']==c['view']['rules']['max_proposals']
            row['proposed_team_clean_offline']=int(all(truth[p] not in EVIL_ROLES for p in c['view']['team']))
    except (RuntimeError,ValueError,TypeError,KeyError) as e:
        row.update(status='budget_stopped' if 'BudgetStop' in type(e).__name__ else 'cancelled' if isinstance(e,Cancelled) else 'failed',error=type(e).__name__+': '+str(e))
    atomic_json(path,row);return row


def run_jobs(out,specs,settings,budget,workers,cancel,records):
    def pair(spec):
        result=[]
        for arm in spec['order']:
            if cancel.is_set():break
            fn=fixed_job if spec['scope'].startswith('fixed') else active_job
            result.append(fn(out,spec,arm,settings,budget,cancel,records) if fn==fixed_job else fn(out,spec,arm,settings,budget,cancel))
        return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(pair,s) for s in specs]
        try:
            for i,f in enumerate(as_completed(futures)):
                rows=f.result();atomic_json(out/'budget.json',budget.snapshot())
                print(f'Finished {i+1}/{len(specs)} pairs/jobs; calls={budget.calls}; reserved+charged CNY={budget.charged+budget.pending:.3f}; statuses={[r["status"] for r in rows]}',flush=True)
        except BaseException:
            cancel.set()
            for f in futures:f.cancel()
            raise


def live(args):
    if not args.live or args.budget_cny is None or args.budget_cny<=0:raise ValueError('Explicit --live and approved --budget-cny required')
    out=args.run_dir.resolve();c=compatible(out)
    if c['budget_cny']!=args.budget_cny:raise ValueError('Budget/config mismatch; no silent budget extension')
    if not c['tests'].get('unit',{}).get('passed') or not c['tests'].get('regression',{}).get('passed'):raise ValueError('Both local gates required')
    settings=Settings(**{**c['settings'],'api_key':Settings.load().api_key})
    if not settings.ready or settings.base_url.rstrip('/')!='https://api.deepseek.com' or settings.model not in {'deepseek-v4-flash','deepseek-flash'}:raise ValueError('Configured official DeepSeek Flash required')
    budget=DurableBudget(out,c['budget_cny'],c['max_calls']);cancel=threading.Event()
    records={r['game_id']:r for r in load_lines(out/'source_replays.jsonl')};plan=json_read(out/'dataset_manifest.json')
    c.update(status='running',last_started_utc=datetime.now(timezone.utc).isoformat());atomic_json(out/'config.json',c)
    try:
        smoke=[s for s in plan['active'] if s['phase']=='smoke']
        run_jobs(out,smoke,settings,budget,args.workers,cancel,records)
        smoke_rows=[json_read(out/'jobs'/(job_id(s,a)+'.json')) for s in smoke for a in s['order']]
        if not all(r['status']=='completed' for r in smoke_rows):
            c['stop_reason']='smoke_gate_failed';return
        if args.mode=='smoke':c['stop_reason']='requested_smoke_only';return
        run_jobs(out,[s for s in plan['active'] if s['experiment']=='A' and s['phase']=='main'],settings,budget,args.workers,cancel,records)
        run_jobs(out,plan['fixed'],settings,budget,args.workers,cancel,records)
        run_jobs(out,plan['repeats'],settings,budget,args.workers,cancel,records)
        run_jobs(out,[s for s in plan['active'] if s['experiment']=='B'],settings,budget,args.workers,cancel,records)
        c['stop_reason']='planned_jobs_drained'
    except KeyboardInterrupt:c['stop_reason']='active_cancellation';cancel.set()
    except BaseException as e:c.update(stop_reason='orchestration_exception',error=type(e).__name__+': '+str(e));raise
    finally:
        c.update(status='stopped',ended_utc=datetime.now(timezone.utc).isoformat());atomic_json(out/'config.json',c)
        atomic_json(out/'budget.json',budget.snapshot())
        from .v21_reporting import aggregate
        aggregate(out)


def offline(out):
    from .v21_contract import decode_menu
    plan=json_read(out/'dataset_manifest.json');records={r['game_id']:r for r in load_lines(out/'source_replays.jsonl')}
    checks=[]
    for s in plan['fixed']:
        contexts,_,observers=input_for(s,records)
        arms=[]
        for arm in s['order']:
            v,p=arm_policy(s['experiment'],arm);c=contexts[v];sup=menu_context(c,p)
            for m in sup['action_menu']:
                if m['parameters']:continue
                r={'belief_updates':[],'interpretation':[],'public_stance_change':None,
                    'recommended_action':{'action_id':m['action_id'],'parameters':{}},'short_rationale':'fixture'}
                decode_menu(r,c,sup)
            arms.append((digest(c['view']),digest(sup['action_menu']),c['posterior_hash']))
        assert arms[0][:2]==arms[1][:2]
        if s['experiment']=='B':assert arms[0][2]==arms[1][2]
        checks.append({'scenario_id':s['scenario_id'],'experiment':s['experiment'],'status':'passed','same_menu_and_view':True,
            'same_posterior':arms[0][2]==arms[1][2]})
    atomic_json(out/'offline_snapshot_audit.json',checks)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',required=True,choices=['audit','fixtures','prepare','unit','regression','offline','smoke','main','report-only'])
    p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--data-from',type=Path);p.add_argument('--tests-from',type=Path)
    p.add_argument('--workers',type=int,default=8);p.add_argument('--live',action='store_true')
    p.add_argument('--budget-cny',type=float);p.add_argument('--max-calls',type=int,default=6500)
    a=p.parse_args(argv);out=a.run_dir.resolve()
    if not 1<=a.workers<=16:raise ValueError('workers must be 1..16')
    if a.mode=='prepare':prepare(a)
    elif a.mode=='audit':
        for name in HISTORY:audit_run(ROOT/'results/joint_belief_v2'/name,out/'historical_audit'/name)
    elif a.mode=='fixtures':
        rows=[reproduce_fixture(f) for path in (out/'historical_audit').glob('*/failure_fixtures.jsonl') for f in load_lines(path)]
        atomic_json(out/'fixture_replay.json',rows)
        if not rows or not all(r['historical_reason_matches'] for r in rows):raise ValueError('Failure fixture mismatch')
    elif a.mode in {'unit','regression'}:
        compatible(out);c=json_read(out/'config.json')
        c['tests'][a.mode]=tests(out,a.mode+'_tests',['tests/eval','tests/test_llm.py'] if a.mode=='unit' else ['tests'])
        atomic_json(out/'config.json',c)
        if c['tests'][a.mode]['exit_code']:raise SystemExit(1)
    elif a.mode=='offline':compatible(out);offline(out)
    elif a.mode in {'smoke','main'}:live(a)
    elif a.mode=='report-only':
        from .v21_reporting import aggregate
        before=(out/'summary.json').read_bytes() if (out/'summary.json').exists() else None
        aggregate(out)
        if before is not None and before!=(out/'summary.json').read_bytes():raise ValueError('Summary did not reproduce')
        atomic_json(out/'report_reproduction.json',{'summary_byte_identical':before is not None,'network_calls':0})
        package(out)


if __name__=='__main__':main()
