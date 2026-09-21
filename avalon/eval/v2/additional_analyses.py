"""Additional raw-only attribution and fixed-opportunity assassination reports.

These computations never alter an observer, a policy, a dataset, or the primary
score. They retain paired game clusters and the already frozen tie tolerance.
"""
from collections import defaultdict
import json
import math
from pathlib import Path

from avalon.eval.beliefs import EPSILON
from avalon.eval.statistics import Metric, paired_comparisons
from .metrics import rank_metrics, tied


def direct_ablation_contrasts(endpoints, metrics, lower, higher, resamples):
    out=[];groups=defaultdict(list)
    for r in endpoints:groups[(r['split'],r['observer_role'])].append(r)
    for (split,role),rows in sorted(groups.items()):
        for reference in ('joint_v1','joint_hard_only','joint_v2_no_success_soft','joint_v2_no_social_soft'):
            selected=[r for r in rows if r['variant'] in {reference,'joint_v2'}]
            tops={(r['game_id'],r['observer_id']):r['merlin_top_set'] for r in selected if r['variant']==reference}
            games=defaultdict(list)
            for r in selected:
                games[(r['game_id'],r['variant'])].append({**r,'merlin_top_set_diff_vs_v1':
                    int(r['merlin_top_set']!=tops[(r['game_id'],r['observer_id'])])})
            reduced=[]
            for (game,variant),seats in games.items():
                row={'pair_id':game,'pair_signature':game,'variant':'baseline' if variant==reference else 'joint_belief'}
                for m in metrics:
                    vals=[r[m] for r in seats if r.get(m) is not None]
                    row[m]=math.fsum(vals)/len(vals) if vals else None
                reduced.append(row)
            specs={m:Metric(m,direction='lower' if m in lower else 'higher' if m in higher else 'descriptive') for m in metrics}
            for m,v in paired_comparisons(reduced,specs,resamples=resamples,seed=61051).items():
                name='merlin_top_set_diff_vs_reference' if m=='merlin_top_set_diff_vs_v1' else m
                out.append({'split':split,'observer_role':role,'variant':'joint_v2','reference':reference,'metric':name,
                    'mean':v['joint_belief'],'reference_mean':v['baseline'],'delta':v['absolute_delta'],
                    'ci_low':v['delta_ci95'][0] if v['delta_ci95'] else None,
                    'ci_high':v['delta_ci95'][1] if v['delta_ci95'] else None,'interpretation':v['interpretation'],
                    'game_clusters':v['eligible_clusters'],'observers':sum(r['variant']=='joint_v2' for r in selected),
                    'unknown_targets':sum(r['unknown_targets'] for r in selected if r['variant']=='joint_v2'),
                    'numerator':v['joint_belief']*v['joint_belief_denominator'] if v['joint_belief'] is not None else None,
                    'denominator':v['joint_belief_denominator'],
                    'reference_numerator':v['baseline']*v['baseline_denominator'] if v['baseline'] is not None else None,
                    'reference_denominator':v['baseline_denominator'],'direction':v['direction'],
                    'contrast':'full v2 minus ablated/reference on identical frozen information',
                    'probability_source':'raw_marginals' if m.startswith('unknown_') else 'native_joint'})
    return out


def assassin_snapshot_scores(folder):
    truth={}
    with (Path(folder)/'replays.jsonl').open() as stream:
        for line in stream:
            r=json.loads(line);truth[r['game_id']]={p['id']:p['role'] for p in r['players']}
    rows=[];bykey={}
    with (Path(folder)/'decisions.jsonl').open() as stream:
        for line in stream:
            r=json.loads(line)
            if r.get('experiment')!='fixed_assassin_snapshot':continue
            merlin=next(p for p,role in truth[r['game_id']].items() if role=='MERLIN')
            distribution={c['target']:c['merlin_probability'] for c in r['candidates']}
            scores=rank_metrics(distribution,merlin,'merlin_')
            top=sorted(p for p,v in distribution.items() if tied(v,max(distribution.values())))
            row={k:r[k] for k in ('game_id','split','profile','observer_id','variant','after_seq','legal_view_hash')}
            row.update(scores,merlin_brier=math.fsum((p-float(target==merlin))**2 for target,p in distribution.items()),
                       chosen_target=r['original_action']['target'],hit=r['assassin_hit_offline'],
                       top_set=json.dumps(top),max_probability=max(distribution.values()),denominator=1)
            rows.append(row);bykey[(r['game_id'],r['observer_id'],r['after_seq'],r['variant'])]=row
    for r in rows:
        base=bykey[(r['game_id'],r['observer_id'],r['after_seq'],'joint_v1')]
        if r['legal_view_hash']!=base['legal_view_hash']:raise ValueError('Assassin opportunity mismatch')
        r['top_set_changed_vs_v1']=int(r['top_set']!=base['top_set'])
        r['target_changed_vs_v1']=int(r['chosen_target']!=base['chosen_target'])
        r['max_probability_delta_vs_v1']=r['max_probability']-base['max_probability']
    return rows


def assassin_snapshot_comparisons(rows,resamples):
    output=[]
    for split in sorted({r['split'] for r in rows}):
        # A game is the cluster even if a future rule offers repeated attempts.
        groups=defaultdict(list)
        for r in rows:
            if r['split']==split:groups[(r['game_id'],r['variant'])].append(r)
        metrics={'merlin_log_loss':Metric('merlin_log_loss',direction='lower'),
                 'merlin_brier':Metric('merlin_brier',direction='lower'),'hit':Metric('hit',direction='higher'),
                 'top_set_changed_vs_v1':Metric('top_set_changed_vs_v1'),
                 'target_changed_vs_v1':Metric('target_changed_vs_v1')}
        reduced=[]
        for (g,v),seats in groups.items():
            reduced.append({'pair_id':g,'pair_signature':g,'variant':'baseline' if v=='joint_v1' else 'joint_belief',
                            **{m:math.fsum(r[m] for r in seats)/len(seats) for m in metrics}})
        for metric,value in paired_comparisons(reduced,metrics,resamples=resamples,seed=87311).items():
            output.append({'split':split,'metric':metric,'reference':'joint_v1','candidate':'joint_v2',
                'joint_v1':value['baseline'],'joint_v2':value['joint_belief'],'delta':value['absolute_delta'],
                'ci95':value['delta_ci95'],'game_clusters':value['eligible_clusters'],
                'interpretation':value['interpretation'],'joint_v1_denominator':value['baseline_denominator'],
                'joint_v2_denominator':value['joint_belief_denominator'],
                'joint_v1_numerator':value['baseline']*value['baseline_denominator'] if value['baseline'] is not None else None,
                'joint_v2_numerator':value['joint_belief']*value['joint_belief_denominator'] if value['joint_belief'] is not None else None})
    return output
