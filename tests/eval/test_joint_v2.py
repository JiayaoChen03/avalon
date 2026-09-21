"""Deterministic mathematical, isolation, replay, and export checks for opt-in v2."""
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import pytest

from avalon.cognition import BeliefEngine
from avalon.engine import Game, Player, mission_rules
from avalon.evidence import LikelihoodConfig, Observation
from avalon.joint_beliefs import JointHypothesis, JointBeliefState, BeliefContradiction
from avalon.mission_likelihood import MissionOutcomeLikelihood, MissionLikelihoodConfig, public_outcome
from avalon.eval.simulation import policy_context, ControlledClient
from avalon.eval.v2.adapters import VARIANTS, make_version
from avalon.eval.v2.experiments import run_scenario, run_pair_spec, replay_to_files, frozen_plan, fixed_snapshot_actions
from avalon.eval.v2.metrics import rank_metrics, score
from avalon.eval.v2.population import PopulationClient, PROFILES
from avalon.eval.v2.reporting import (write_csv, read_csv, endpoints_and_episodes, paired_outcomes,
                                     active_summary, group_comparisons)

ROOT=Path(__file__).resolve().parents[2]
TRUTH={'P1':'GOOD','P2':'GOOD','P3':'MERLIN','P4':'EVIL','P5':'ASSASSIN'}


def view(pid='P1'):
    return Game([Player(p,p,r) for p,r in TRUTH.items()],seed=101).view(pid)


def engine(tau=1,gamma=1):
    v=view();v['rules']['fail_threshold']=tau
    e=BeliefEngine(v,likelihood_config=LikelihoodConfig(mission=MissionLikelihoodConfig(enabled=True,q=.5,gamma=gamma)))
    other={**TRUTH,'P2':'EVIL','P4':'GOOD'}
    e.beliefs.hypotheses=[JointHypothesis(TRUTH,.5),JointHypothesis(other,.5)]
    e.beliefs.normalize()
    return e


def mission(count=0,tau=1,seq=101,round_no=1):
    event={'kind':'MISSION','seq':seq,'round':round_no,'attempt':1,'team':['P2'],'success':True,'fail_threshold':tau}
    if count is not None:event['fail_count']=count;event['success']=count<tau
    return event


def dist(e):return {h.key:h.probability for h in e.beliefs.hypotheses}


def test_success_is_soft_two_thirds_and_nonzero_dirty():
    e=engine();e.observe(mission())
    assert e.P_alignment('P2','GOOD')==pytest.approx(2/3)
    assert e.P_alignment('P2','EVIL')==pytest.approx(1/3)
    assert len(e.beliefs.hypotheses)==2
    assert sum(x.feature=='mission_outcome' for x in e.beliefs.update_records[-1].evidence)==1


def test_tau_two_hidden_success_equal_likelihood_is_noop():
    e=engine(tau=2);before=dist(e);e.observe(mission(None,2))
    assert dist(e)==before
    exact=engine(tau=2);exact.observe(mission(0,2))
    assert exact.P_alignment('P2','GOOD')==pytest.approx(2/3)


def test_exact_count_hard_exclusion_boolean_does_not_steal_hidden_count():
    exact=engine(tau=2);exact.observe(mission(1,2))
    assert exact.P_alignment('P2','EVIL')==1
    hidden=engine(tau=2);hidden.observe(mission(None,2))
    assert hidden.P_alignment('P2','EVIL')==.5


@pytest.mark.parametrize('k',range(5))
@pytest.mark.parametrize('tau',(1,2,3))
def test_count_likelihood_normalizes_and_coarsening_sums(k,tau):
    rules={**mission_rules(5,1),'fail_threshold':tau}
    model=MissionOutcomeLikelihood(MissionLikelihoodConfig(enabled=True,q=.37,gamma=1))
    outcome=public_outcome({'team':['a','b','c','d'],'success':True},rules)
    probs=model.count_distribution(k,outcome)
    assert sum(probs.values())==pytest.approx(1)
    assert model.probability(k,outcome)==pytest.approx(sum(p for f,p in probs.items() if f<tau))
    failed={**outcome,'success':False}
    assert model.probability(k,outcome)+model.probability(k,failed)==pytest.approx(1)


def test_duplicate_summary_and_count_bool_not_double_weighted():
    e=engine();event=mission();e.observe(event);one=dist(e)
    e.observe(event);assert dist(e)==one
    # Same public mission recovered via snapshot with a different event ID.
    e._process(Observation.from_mission({'round':1,'attempt':1,'team':['P2'],'success':True,'fail_count':0,'fail_threshold':1}))
    assert dist(e)==one
    e.observe({'kind':'SOCIAL','seq':102,'round':1,'attempt':1,'actor':'P4','target':'P2','card':'HEDGE',
               'reason':'mission_record','public_writing':'The mission succeeded.','citations':[]})
    assert dist(e)==one


def test_impossible_result_raises_atomically_no_reset():
    e=engine();before=dist(e)
    bad={**mission(),'team':['P1'],'fail_count':1,'success':False}
    with pytest.raises(BeliefContradiction):e.observe(bad)
    assert dist(e)==before


def test_repeated_soft_low_likelihood_preserves_legal_worlds_and_hard_zero():
    e=engine()
    for i in range(1100):e.observe(mission(seq=101+i,round_no=i+1))
    assert len(e.beliefs.hypotheses)==2
    assert all(h.probability>0 and math.isfinite(h.log_probability) for h in e.beliefs.hypotheses)
    e2=engine();e2.observe(mission(1))
    eliminated=set(e2.beliefs.eliminated_keys)
    for i in range(10):e2.observe(mission(seq=202+i,round_no=i+2))
    assert not eliminated.intersection(dist(e2))


def test_semantics_for_forced_evil_and_unsupported_good():
    rules=mission_rules(5,1);model=MissionOutcomeLikelihood(MissionLikelihoodConfig(enabled=True))
    forced=public_outcome({'team':['a'],'success':True},{**rules,'evil_may_succeed':False})
    assert not model.feasible(1,forced)
    unsupported=public_outcome({'team':['a'],'success':True},{**rules,'good_may_fail':True})
    assert model.skip_reason(unsupported)=='unsupported_good_sabotage_semantics'
    assert model.evaluate(1,unsupported)==1


@pytest.mark.parametrize('variant',VARIANTS)
def test_ablation_facts_and_duplicate_audit(variant):
    observer=make_version(variant,view())
    event={**mission(1),'team':['P2','P4']}
    observer.observe(event);before=observer.distribution()
    if variant!='legacy_baseline':
        assert all(any(dict(w)[p] in {'EVIL','ASSASSIN'} for p in event['team']) for w in before)
        assert 'mission:1:1' in observer.engine._applied_signals
    observer.observe(event)
    assert observer.distribution()==before
    assert observer.last_audit['skip_reason']=='duplicate_event_or_factor'


def test_no_social_switch_keeps_events_and_other_factors():
    a=make_version('joint_v2',view());b=make_version('joint_v2_no_social_soft',view())
    social={'kind':'SOCIAL','seq':10,'round':1,'attempt':1,'actor':'P2','target':'P4','card':'ACCUSE','reason':'observe','public_writing':'Question','citations':[]}
    before=b.distribution();a.observe(social);b.observe(social)
    assert a.distribution()!=b.distribution()
    assert b.distribution()==before
    assert b.engine.state.observations[-1].event_id==a.engine.state.observations[-1].event_id
    assert b.engine._applied_signals==a.engine._applied_signals
    team={'kind':'TEAM','seq':11,'round':1,'attempt':1,'actor':'P2','team':['P2','P4']}
    b.observe(team);assert b.distribution()!=before


def test_no_success_ablation_keeps_successful_tau_two_hard_fact():
    o=make_version('joint_v2_no_success_soft',view())
    o.observe(mission(1,2))
    assert o.engine.P_alignment('P2','EVIL')==pytest.approx(1)
    assert o.last_audit['skip_reason']=='success_soft_disabled'
    assert o.last_audit['applied']==0


def test_audit_constant_certain_and_disabled_reasons():
    for v,reason in [('joint_v1','no_mission_soft_factor_v1'),('joint_hard_only','configuration_disabled'),
                     ('joint_v2_no_success_soft','success_soft_disabled')]:
        o=make_version(v,view());o.observe(mission());assert o.last_audit['skip_reason']==reason
    o=make_version('joint_v2',view('P3'));o.observe(mission())
    assert o.last_audit['applied']==1 and o.last_audit['posterior_tv']<1e-12
    assert o.last_audit['skip_reason']=='equal_likelihood_on_surviving_support'


def test_complete_config_evil_set_and_merlin_ties_scored_separately():
    o=make_version('joint_hard_only',view());s=score(o,TRUTH)
    assert s['configuration_top_ties']>1 and s['configuration_in_top']==1
    assert s['configuration_unique_correct']==0
    assert s['configuration_tie_expected_hit']==pytest.approx(1/s['configuration_top_ties'])
    assert s['evil_set_probability']>s['configuration_probability']
    assert sum(json.loads(s['merlin_distribution_json']).values())==pytest.approx(1)
    assert s['unknown_targets']==4
    assert score(make_version('joint_hard_only',view('P3')),TRUTH)['unknown_brier_score'] is None
    assert rank_metrics({'a':.5,'b':.5},'a','')['midrank']==1.5
    assert rank_metrics({'a':1},'b','')['log_loss']==pytest.approx(-math.log(1e-15))


def test_projection_is_explicit_not_used_by_legacy_action():
    o=make_version('legacy_baseline',view());before=policy_context(view(),o);s=score(o,TRUTH)
    assert s['merlin_probability_source']=='scoring_projection'
    assert s['legacy_raw_merlin_sum']!=pytest.approx(1)
    assert policy_context(view(),o)==before
    with pytest.raises(ValueError):o.team_query(['P1','P2'])


def correlation_state(evil_pairs):
    # Public composition has two interchangeable roles per alignment. Merlin and
    # Assassin are not required for the pure joint query to work.
    hypotheses=[JointHypothesis({p:'EVIL' if p in pair else 'GOOD' for p in 'abcd'},.5) for pair in evil_pairs]
    state=JointBeliefState(hypotheses,{'EVIL':2,'GOOD':2},{'EVIL':'EVIL','GOOD':'GOOD'});state.normalize();return state


def test_same_marginals_different_correlations_and_team_risks():
    a=correlation_state([{'a','b'},{'c','d'}]);b=correlation_state([{'a','c'},{'b','d'}])
    assert a.marginals()==b.marginals()
    model=MissionOutcomeLikelihood(MissionLikelihoodConfig(enabled=True))
    x=a.team_outcome_risk(['a','b'],mission_rules(5,1),model)
    y=b.team_outcome_risk(['a','b'],mission_rules(5,1),model)
    assert x['expected_evil_count']==y['expected_evil_count']==1
    assert x['clean_probability']==.5 and y['clean_probability']==0
    assert x['mission_failure_probability']!=y['mission_failure_probability']


def test_frozen_files_remain_exact():
    p=Path('avalon/eval/frozen_v1');m=json.loads((p/'provenance.json').read_text())
    for name,hash_ in m['sha256'].items():assert hashlib.sha256((p/name).read_bytes()).hexdigest()==hash_


def test_hidden_truth_and_profile_not_in_input_and_deterministic_actions():
    v=view();alternate={**TRUTH,'P2':'EVIL','P4':'GOOD'}
    w=Game([Player(p,p,r) for p,r in alternate.items()],seed=101).view('P1')
    assert v==w
    a,b=make_version('joint_v2',v),make_version('joint_v2',w)
    c1,c2=PopulationClient(123,'mixed'),PopulationClient(123,'mixed')
    assert c1.complete(policy_context(v,a))==c2.complete(policy_context(w,b))
    assert 'profile' not in policy_context(v,a) and 'truth' not in policy_context(v,a)
    a.observe(mission());assert a.distribution()!=b.distribution()


@pytest.fixture(scope='module')
def population_games():
    return [run_scenario({'seed':83100+i,'profile':p,'split':'development','scope':'generation','focal':'P1',
                           'phase':'unit','scenario_id':f'unit-{i}'},'joint_v1') for i,p in enumerate(PROFILES)]


def test_population_legal_overlap_and_rejections(population_games):
    actions={};rejects=reteams=evilpasses=goodaccuse=evilhedge=0
    for row,_,record in population_games:
        assert row['status']=='completed',row['error']
        for d in record['decisions']:
            role=d['view']['role'];a=d['action']
            if d['phase']=='mission':
                assert a['card'] in d['view']['legal_options'][0]['cards']
                evilpasses+=role in {'EVIL','ASSASSIN'} and a['card']=='SUCCESS'
            if a.get('kind')=='SOCIAL':
                goodaccuse+=role=='GOOD' and a['social']['card']=='ACCUSE'
                evilhedge+=role in {'EVIL','ASSASSIN'} and a['social']['card']=='HEDGE'
        rejects+=sum(e['kind']=='TEAM_VOTE' and not e['approved'] for e in record['events'])
        reteams+=sum(e['kind']=='TEAM' and e.get('attempt',1)>1 for e in record['events'])
    assert evilpasses and goodaccuse and evilhedge and rejects and reteams


def test_constant_mission_factor_does_not_perturb_exact_argmax(population_games):
    from avalon.chronicle import PUBLIC_KINDS, context_record
    from avalon.eval.simulation import validate_replay
    for _,_,record in population_games:
        game,truth=validate_replay(record)
        for pid,role in truth.items():
            if role not in {'EVIL','ASSASSIN','MERLIN'}:continue
            v1=make_version('joint_v1',game.view(pid));v2=make_version('joint_v2',game.view(pid))
            for raw in record['events']:
                if raw['kind'] not in PUBLIC_KINDS:continue
                event=context_record(raw);v1.observe(event);v2.observe(event)
                # Initial authorized alignment is complete in these roles.
                # Every mission has identical k in every surviving world.
                assert v1.distribution()==v2.distribution()
                assert v1.marginals()==v2.marginals()


def test_same_replay_stream_full_support_exports_and_p2(tmp_path,population_games):
    record=population_games[1][2]
    folder=Path(replay_to_files((record,str(tmp_path/'replay'))))
    audit=json.loads((folder/'audit.json').read_text())
    assert len(audit)==30
    assert len({a['observation_stream_digest'] for a in audit})==1
    for pid in TRUTH:assert len({a['initial_view_digest'] for a in audit if a['observer_id']==pid})==1
    import gzip
    with gzip.open(folder/'hypothesis_trace.jsonl.gz','rt') as f:
        first=next(r for r in map(json.loads,f) if r['observer_role']=='GOOD' and r['event_kind']=='PRIOR')
        assert len(first['worlds'])>3 and 'hard_eliminated_worlds' in first
    p2=fixed_snapshot_actions(record)
    assert p2 and all(x['legal_options'] for x in p2)
    # Rebuild both summary and prose solely from exported raw files, twice.
    from avalon.eval.v2.reporting import aggregate
    from avalon.eval.simulation import canonical
    from avalon.eval.joint_belief import write_json
    write_json(folder/'config.json',{'status':'completed','bootstrap_resamples':30})
    write_json(folder/'replay_audit.json',audit)
    (folder/'replays.jsonl').write_text(canonical(record)+'\n')
    (folder/'decisions.jsonl').write_text(''.join(canonical(r)+'\n' for r in p2))
    write_csv(folder/'games.csv',[population_games[1][0]])
    first_summary=aggregate(folder,make_plots=False)
    first_report=(folder/'report.md').read_bytes()
    assert aggregate(folder,make_plots=False)==first_summary
    assert (folder/'report.md').read_bytes()==first_report


def test_worker_count_does_not_change_scores():
    spec=frozen_plan('smoke')['active'][0]
    local=run_pair_spec(spec)
    with ProcessPoolExecutor(max_workers=2) as pool:remote=next(pool.map(run_pair_spec,[spec]))
    for x,y in zip(local,remote):
        a,b=x[0],y[0]
        for k in a:
            if k not in {'belief_update_ms','game_seconds'}:assert a[k]==b[k],k
        assert x[2]==y[2]


def test_zero_denominator_paired_outcome_reconstruction_and_failed_preservation():
    rows=[]
    for seed in range(3):
        for v in ('joint_v1','joint_v2'):
            rows.append({'pair_id':str(seed),'variant':v,'scope':'single_seat','phase':'main','profile':'mixed','game_id':str(seed)+v,
              'focal_role':'GOOD','focal_id':'P1','focal_win':None if seed==2 else int(v=='joint_v2'),
              'status':'failed' if seed==2 else 'completed','pair_signature':str(seed)})
    paired=paired_outcomes(rows)
    assert len(paired)==3 and paired[-1]['available']==0
    assert sum(r['win_difference'] or 0 for r in paired)/sum(r['denominator'] for r in paired)==1
    assert rank_metrics({},'x','')['probability'] is None


def test_pathology_episode_recovers_and_deduplicates(tmp_path):
    rows=[]
    for i,flag in enumerate((0,1,1,0,1)):
        r={'game_id':'g','variant':'joint_v2','observer_id':'P1','observer_role':'GOOD','split':'development','profile':'mixed',
           'decision_available':1,'event_id':str(i),'event_seq':i,'event_kind':'MISSION',
           'entropy_down_truth_down':0,'overconfident_wrong_world':0,'overconfident_wrong_marginals':flag,
           'distribution_collapsed':0,'truth_probability_collapsed':0}
        rows.append(r)
    write_csv(tmp_path/'trace.csv',rows)
    endpoint,episodes,n=endpoints_and_episodes(tmp_path/'trace.csv')
    assert n==5 and len(episodes)==2 and len({e['game_id'] for e in episodes})==1
    assert episodes[0]['update_count']==2 and episodes[0]['duration_events']==2 and episodes[0]['recovered']==1
    assert episodes[1]['endpoint_still_abnormal']==1
