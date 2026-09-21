"""Predeclared source splits and legal snapshot coverage, independent of LLM outcomes."""
from collections import Counter,defaultdict
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import random

from avalon.eval.simulation import play_game,canonical,digest
from .adapters import make_version
from .population import PopulationClient,PROFILES
from .experiments import scenario_players
from .live_runner import freeze_plan,REFERENCE,snapshot_inputs
from .v21_contract import enrich_context,POLICY_CURRENT,POLICY_CANDIDATE
from .v21_runtime import atomic_json

NEW_PROFILES={
 'v21_development':dict(hedge=.3,defend=.25,early_pass=.65,dissent=.35,clean_support=.7,revision=.2),
 'v21_validation':dict(hedge=.4,defend=.35,early_pass=.7,dissent=.52,clean_support=.8,revision=.45),
 'v21_heldout_a':dict(hedge=.42,defend=.17,early_pass=.95,dissent=.65,clean_support=.87,revision=.60),
 'v21_heldout_b':dict(hedge=.18,defend=.44,early_pass=.60,dissent=.58,clean_support=.93,revision=.50)}


def population(seed,profile,focal=None):
    if profile in PROFILES:return PopulationClient(seed,profile,focal)
    c=PopulationClient(seed,'mixed',focal);c.profile=profile;c.parameters=deepcopy(NEW_PROFILES[profile]);return c


def source_plan():
    out=[]
    for j,(profile,count,split) in enumerate([('v21_development',12,'development'),('v21_validation',8,'validation'),
        ('v21_heldout_a',30,'held_out_test'),('v21_heldout_b',30,'held_out_test')]):
        for i in range(count):
            seed=1031000+j*1000+i
            out.append({'seed':seed,'profile':profile,'split':split,'phase':'v21_source','scope':'generation',
                'focal':'P1','scenario_id':f'v21-source-{seed}'})
    return out


def source_game(spec):
    row,_,record=play_game(spec['seed'],'joint_v2',phase=spec['phase'],player_setup=scenario_players(spec),
        all_seats=True,belief_factory=make_version,client_factory=lambda s:population(s,spec['profile']),capture_decisions=True)
    if row['status']!='completed':raise RuntimeError('Source game failed: '+row['error'])
    record.update(spec);record['status']=row['status'];return record


def coverage_tags(d):
    v=d['view'];risk=d.get('team_risk')
    if risk is None and d.get('team_risks'):risk=sum(d['team_risks'].values())/len(d['team_risks'])
    tier='certain_low' if risk is not None and risk<.05 else 'certain_high' if risk is not None and risk>.95 else 'uncertain'
    return [f"role:{v['role']}",f"attempt:{v['attempt']}",f"risk:{tier}",
        f"ap:{v['resolve'][v['self']]}",f"score:{v['successes']}-{v['failures']}",
        f"leader_self:{v['leader']==v['self']}"]


def select_new(records):
    selected=[]
    for phase in ('team','vote'):
        candidates=[]
        for r in records:
            if r['split']!='held_out_test':continue
            for index,d in enumerate(r['decisions']):
                if d['phase']!=phase:continue
                candidates.append({'snapshot_id':f"{r['game_id']}:{d['observer_id']}:{d['after_seq']}:{phase}",
                    'source_game_id':r['game_id'],'decision_index':index,'phase':phase,'observer_role':d['view']['role'],
                    'observer_id':d['observer_id'],'split':r['split'],'profile':r['profile'],'tags':coverage_tags(d)})
        used=set();counts=Counter();games=Counter()
        for role in ('GOOD','MERLIN','EVIL','ASSASSIN'):
            eligible=[c for c in candidates if c['observer_role']==role]
            for _ in range(25):
                available=[c for c in eligible if c['snapshot_id'] not in used and games[c['source_game_id']]<4]
                if not available:break
                best=max(available,key=lambda c:(sum(1/(1+counts[t]) for t in c['tags']),digest(c['snapshot_id'])))
                selected.append(best);used.add(best['snapshot_id']);games[best['source_game_id']]+=1;counts.update(best['tags'])
    return selected


def balanced_order(specs,arms):
    strata=defaultdict(list)
    for s in specs:strata[(s.get('phase'),s.get('scope'),s.get('focal_role',s.get('observer_role')))].append(s)
    for key,group in sorted(strata.items(),key=lambda x:str(x[0])):
        rng=random.Random(digest(key));rng.shuffle(group)
        for i,s in enumerate(group):s['order']=list(arms if i%2==0 else reversed(arms))


def prepare_data(output,workers=4):
    output=Path(output);specs=source_plan()
    atomic_json(output/'source_scenario_plan.json',{'frozen_before_generation':True,'scenarios':specs,'profiles':NEW_PROFILES})
    records=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(source_game,specs):
            records.append(r)
            if len(records)%10==0:print(f'Generated source games {len(records)}/{len(specs)}',flush=True)
    (output/'source_replays.jsonl').write_text(''.join(canonical(r)+'\n' for r in records))
    snapshots=select_new(records)
    active_a=deepcopy(freeze_plan(REFERENCE)['selected_active'])
    for s in active_a:s.update(experiment='A',policy_revision=POLICY_CURRENT,dataset_reuse='historical_diagnostic')
    balanced_order(active_a,('joint_v1','joint_v2'))
    active_b=[]
    for i in range(8):
        active_b.append({'scenario_id':f'v21-B-active-{1080000+i}','seed':1080000+i,'profile':('v21_heldout_a','v21_heldout_b')[i//4],
            'split':'held_out_test','phase':'main','scope':'single_seat','focal':f'P{i%5+1}',
            'focal_role':('GOOD','MERLIN','EVIL','ASSASSIN')[i%4],'experiment':'B','policy_revision':'paired_vote_only'})
    balanced_order(active_b,('policy_current','policy_candidate'))
    fixed=[]
    for s in snapshots:
        fixed.append({**s,'experiment':'A','scenario_id':'A:'+s['snapshot_id'],'scope':'fixed','arms':['joint_v1','joint_v2']})
        if s['phase']=='vote':fixed.append({**s,'experiment':'B','scenario_id':'B:'+s['snapshot_id'],'scope':'fixed','arms':['policy_current','policy_candidate']})
    for exp,arms in [('A',('joint_v1','joint_v2')),('B',('policy_current','policy_candidate'))]:balanced_order([s for s in fixed if s['experiment']==exp],arms)
    repeats=[]
    for role in ('GOOD','MERLIN','EVIL','ASSASSIN'):
        for phase in ('team','vote'):
            s=next((s for s in snapshots if s['observer_role']==role and s['phase']==phase),None)
            if s:
                for i in range(2):repeats.append({**s,'repeat_index':i+1,'experiment':'repeat','scenario_id':f"repeat:{s['snapshot_id']}:{i+1}", 'scope':'fixed_repeat','arms':['joint_v2'],'order':['joint_v2']})
    plan={'frozen_before_live':True,'active':active_a+active_b,'fixed':fixed,'repeats':repeats,
        'source_scenarios':specs,'profiles':NEW_PROFILES,'fixed_target_per_phase':100,
        'selected_counts':dict(Counter(s['phase'] for s in snapshots)),
        'selection':'25 per role per phase where available; coverage-weighted legal public context, max four per source game/phase; no LLM outcomes used',
        'B_change':'Vote DecisionContext only. All other phases and beliefs identical.',
        'statistics':'Source-game clustered fixed decisions; scenario-paired active decisions; 2000 resamples; degenerate intervals flagged',
        'source_replays_sha256':digest(records)}
    atomic_json(output/'dataset_manifest.json',plan)
    return plan


def input_for(spec,records):
    record=records[spec['source_game_id']];d=record['decisions'][spec['decision_index']]
    contexts,truth,observers=snapshot_inputs({'record':record,'decision':d})
    from avalon.chronicle import PUBLIC_KINDS,context_record
    public=[context_record(e) for e in record['events'] if e['kind'] in PUBLIC_KINDS and e['seq']<=d['after_seq']]
    for c in contexts.values():c['public_event_history']=public
    return {v:enrich_context(c,observers[v]) for v,c in contexts.items()},truth,observers


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if (a.output/'source_replays.jsonl').exists():raise ValueError('Source corpus already exists')
    print(prepare_data(a.output,a.workers)['selected_counts'])
