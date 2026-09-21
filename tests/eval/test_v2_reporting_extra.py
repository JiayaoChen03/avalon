"""Additional raw-only reporting checks; no candidate inference changes."""
from avalon.eval.v2.additional_analyses import direct_ablation_contrasts, assassin_snapshot_comparisons


def test_direct_ablation_uses_game_not_observer_denominator():
    rows=[]
    for game in ('a','b'):
        for observer in ('P1','P2'):
            for v,value in [('joint_v1',.3),('joint_hard_only',.4),('joint_v2_no_success_soft',.2),
                            ('joint_v2_no_social_soft',.15),('joint_v2',.1)]:
                rows.append({'game_id':game,'observer_id':observer,'observer_role':'GOOD','split':'held_out_test',
                    'variant':v,'unknown_brier_score':value,'unknown_targets':4,'merlin_top_set':'["P3"]'})
    out=direct_ablation_contrasts(rows,('unknown_brier_score',),{'unknown_brier_score'},set(),30)
    assert len(out)==4
    success=next(r for r in out if r['reference']=='joint_v2_no_success_soft')
    assert abs(success['delta']+.1)<1e-12
    assert success['game_clusters']==2 and success['denominator']==2
    assert success['observers']==4 and success['unknown_targets']==16


def test_fixed_opportunity_comparison_is_paired_by_game():
    rows=[]
    for g in ('a','b'):
        for v in ('joint_v1','joint_v2'):
            rows.append({'game_id':g,'variant':v,'split':'held_out_test','merlin_log_loss':.7,'merlin_brier':.3,
                         'hit':int(g=='a'),'top_set_changed_vs_v1':0,'target_changed_vs_v1':0})
    stats=assassin_snapshot_comparisons(rows,30)
    hit=next(r for r in stats if r['metric']=='hit')
    assert hit['joint_v1']==hit['joint_v2']==.5
    assert hit['delta']==0 and hit['ci95']==[0,0]
    assert hit['game_clusters']==2


def test_unavailable_projection_not_fabricated_as_zero_calibration():
    from avalon.eval.v2.reporting import calibration_rows
    row={'truth_roles_json':'{"P1":"MERLIN","P2":"GOOD"}', 'raw_marginals_json':'{}',
         'unknown_target_ids':'[]','merlin_distribution_json':'{"P1":0,"P2":0}',
         'merlin_brier':None,'split':'held_out_test','variant':'legacy_baseline',
         'observer_role':'GOOD','game_id':'g'}
    assert calibration_rows([row])==[]
