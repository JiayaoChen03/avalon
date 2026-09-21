from avalon.eval.v2.live_session_report import compare


def test_fixed_policy_comparison_preserves_paired_game_units_and_unavailable():
    result=compare({'g1':1,'g2':0,'g3':None},{'g1':1,'g2':1,'g3':0},'clean_team')
    assert result['reference_numerator']==1 and result['reference_denominator']==2
    assert result['candidate_numerator']==2 and result['candidate_denominator']==2
    assert result['absolute_delta']==.5
    assert result['paired_clusters']==3 and result['eligible_clusters']==2


def test_zero_eligible_is_unavailable_not_zero():
    result=compare({'g1':None},{'g1':1},'clean_team')
    assert result['reference'] is None and result['candidate'] is None
    assert result['reference_denominator']==0 and result['delta_ci95'] is None
