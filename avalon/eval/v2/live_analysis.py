"""Raw-only supplemental analysis; does not alter any experiment or primary score."""
from collections import defaultdict
import json
from pathlib import Path

from avalon.eval.statistics import Metric,paired_comparisons
from avalon.eval.joint_belief import write_json
from .reporting import write_csv


def semantic_action(action):
    action=dict(action or {})
    if 'team' in action:action['team']=sorted(action['team'])
    return action


def analyze(folder):
    folder=Path(folder)
    records=[json.loads(l) for l in (folder/'fixed_snapshot_results.jsonl').read_text().splitlines()]
    pairs=defaultdict(dict)
    repeats=[]
    for r in records:
        if r['stage']=='fixed_snapshot':pairs[r['snapshot_id']][r['variant']]=r
        else:repeats.append(r)
    rows=[]
    for key,byv in sorted(pairs.items()):
        if len(byv)!=2:continue
        a,b=byv['joint_v1'],byv['joint_v2']
        ok=a['status']==b['status']=='completed'
        row={'snapshot_id':key,'game_id':a['game_id'],'phase':a['phase'],'profile':a['profile'],
             'v1_status':a['status'],'v2_status':b['status'],'denominator':int(ok),
             'identical_legal_view':a['legal_view_hash']==b['legal_view_hash'],
             'identical_model_context':a['model_context_hash']==b['model_context_hash'],
             'raw_action_changed':int(a.get('action')!=b.get('action')) if ok else None,
             'semantic_action_changed':int(semantic_action(a.get('action'))!=semantic_action(b.get('action'))) if ok else None,
             'v1_action':json.dumps(a.get('action'),sort_keys=True), 'v2_action':json.dumps(b.get('action'),sort_keys=True)}
        for metric in ('clean_team','merlin_hit','approve'):
            row['v1_'+metric]=a.get(metric);row['v2_'+metric]=b.get(metric)
        rows.append(row)
    write_csv(folder/'fixed_paired_outcomes.csv',rows)
    metrics={}
    for phase,metric in [('team','clean_team'),('assassination','merlin_hit'),('vote','approve')]:
        selected=[r for r in rows if r['phase']==phase]
        data=[]
        for r in selected:
            for v,alias in [('v1','baseline'),('v2','joint_belief')]:
                data.append({'pair_id':r['game_id'],'pair_signature':r['game_id'],'variant':alias,metric:r[v+'_'+metric]})
        if data:
            stats=paired_comparisons(data,{metric:Metric(metric,direction='descriptive' if phase=='vote' else 'higher')},resamples=2000,seed=99173)[metric]
            for old,new in [('baseline','joint_v1'),('joint_belief','joint_v2')]:
                for suffix in ('','_ci95','_denominator'):stats[new+suffix]=stats.pop(old+suffix)
            for v in ('joint_v1','joint_v2'):
                stats[v+'_numerator']=stats[v]*stats[v+'_denominator'] if stats[v] is not None else None
            stats['semantic_action_changed']=sum(r['semantic_action_changed'] or 0 for r in selected)
            stats['paired_action_denominator']=sum(r['denominator'] for r in selected)
            stats['identical_model_contexts']=sum(r['identical_model_context'] for r in selected)
            metrics[phase]=stats
    rr=[]
    for r in repeats:
        a=pairs.get(r['snapshot_id'],{}).get('joint_v1')
        if a:
            ok=a['status']==r['status']=='completed'
            rr.append({'snapshot_id':r['snapshot_id'],'same_context':a['model_context_hash']==r['model_context_hash'],
                       'denominator':int(ok),'semantic_action_changed':int(semantic_action(a.get('action'))!=semantic_action(r.get('action'))) if ok else None})
    result={'fixed_metrics':metrics,'identical_input_repeats':rr,
            'action_equivalence':'Team order canonicalized; original raw action-change counts preserved separately.',
            'attribution':'Between-request differences can include service nondeterminism. No causal subtraction of repeat noise.',
            'unit':'one frozen game per phase; paired whole-game bootstrap; no new games played'}
    write_json(folder/'fixed_snapshot_comparisons.json',result)
    return result


if __name__=='__main__':
    import sys
    print(json.dumps(analyze(Path(sys.argv[1])),ensure_ascii=False,indent=2))
