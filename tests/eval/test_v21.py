"""Offline regression for actual live failures, state transactions and attribution."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import patch
import pytest

from avalon.engine import Game,make_players
from avalon.llm import COGNITION_PROTOCOL, Settings,ChatClient,LLMError
from avalon.eval.simulation import policy_context,play_game,ControlledClient,digest
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2.v21_contract import (legal_menu,menu_context,decode_menu,validate_legal_action,
    enrich_context,POLICY_CURRENT,POLICY_CANDIDATE,vote_context,configure_transport,MENU_PROTOCOL,correction_feedback)
from avalon.eval.v2.v21_runtime import Session,StaleState,DurableBudget,MenuClient,json_read
from avalon.eval.v2.v21_reporting import cluster_delta,pairing
from avalon.eval.v2.v21_audit import reproduce_fixture,load_lines,legacy_decisions


def context(seed=1):
    g=Game(make_players(5,seed),seed=seed);v=g.view(g.leader)
    return g,enrich_context(policy_context(v,make_version('joint_v2',v)),make_version('joint_v2',v))


def response(supplied,choice=0,params=None):
    return {'belief_updates':[],'interpretation':[],'public_stance_change':None,
        'recommended_action':{'action_id':supplied['action_menu'][choice]['action_id'],'parameters':params or {}},
        'short_rationale':'observe'}


def test_menu_all_teams_equal_between_beliefs_and_no_truth():
    g,c=context();view=deepcopy(c['view'])
    a=enrich_context(policy_context(view,make_version('joint_v1',view)),make_version('joint_v1',view))
    c['truth']='NEVER';c['policy_label']='NEVER';c['variant']='NEVER'
    sa,sb=menu_context(a),menu_context(c)
    assert sa['action_menu']==sb['action_menu'] and len(sa['action_menu'])==10
    assert 'NEVER' not in json.dumps(sb)
    assert all(set(p)=={'id','name'} for p in sb['game']['players'])


@pytest.mark.parametrize('team',[['P1'],['P1','P1'],['P1','P9'],['P1','P2','P3']])
def test_illegal_teams_never_repaired(team):
    _,c=context()
    with pytest.raises(ValueError):validate_legal_action({'team':team},c['view'])


@pytest.mark.parametrize('bad',[None,{},'garbage',{'recommended_action':{}}, {'belief_updates':[{'evil':1}]}])
def test_bad_schema_cannot_mutate_state(bad):
    g,c=context();before=Session.game_hash(g);ch=digest(c)
    with pytest.raises(ValueError):decode_menu(bad,c,menu_context(c))
    assert Session.game_hash(g)==before and digest(c)==ch


def test_resource_and_stale_menu_checks():
    _,c=context();sup=menu_context(c);r=response(sup)
    c['view']['attempt']+=1
    with pytest.raises(ValueError,match='stale'):decode_menu(r,c,sup)
    c['view']['phase']='vote';c['view']['legal_actions']=['VOTE'];c['view']['resolve'][c['view']['self']]=0
    with pytest.raises(ValueError,match='resource'):validate_legal_action({'approve':True,'strong':True},c['view'])


def discussion_context(seed=31):
    g,c=context(seed)
    g.propose(g.leader,['P1','P2'])
    actor=g.next_actor
    view=g.view(actor)
    observer=make_version('joint_v2',view)
    return g,enrich_context(policy_context(view,observer),observer)


def test_social_menu_declares_citations_as_array_and_accepts_array():
    _,c=discussion_context()
    supplied=menu_context(c)
    option=next(m for m in supplied['action_menu'] if m['action']['kind'] in {'SOCIAL','COMMITTED_SOCIAL'})
    schema=option['parameters']['social']['citations']
    assert schema['type']=='array'
    assert schema['items']=='record_id string'
    assert 'ids' not in schema
    assert set(schema['example'])<=set(schema['allowed_ids'])
    target=next(p['id'] for p in c['view']['players'] if p['id']!=c['view']['self'])
    raw=response(supplied,supplied['action_menu'].index(option),{
        'social':{'card':'HEDGE','target':target,'reason':'observe',
                  'public_writing':'仍待观察。','citations':[]}})
    action,details=decode_menu(raw,c,supplied)
    assert action['social']['citations']==[]
    assert details['normalization']=='identity'
    assert set(supplied['response_contract'])=={
        'recommended_action','belief_updates','interpretation','public_stance_change','short_rationale'}


def test_social_citation_object_is_rejected_without_repair():
    _,c=discussion_context()
    supplied=menu_context(c)
    option=next(m for m in supplied['action_menu'] if m['action']['kind'] in {'SOCIAL','COMMITTED_SOCIAL'})
    target=next(p['id'] for p in c['view']['players'] if p['id']!=c['view']['self'])
    raw=response(supplied,supplied['action_menu'].index(option),{
        'social':{'card':'DEFEND','target':target,'reason':'observe',
                  'public_writing':'仍待观察。','citations':{'ids':[]}}})
    with pytest.raises(ValueError,match='Invalid public evidence references'):
        decode_menu(raw,c,supplied)


def test_provider_json_object_metadata_is_explicitly_normalized_only():
    _,c=context()
    supplied=menu_context(c)
    raw=response(supplied)
    raw['type']='json_object'
    action,details=decode_menu(raw,c,supplied)
    assert action==supplied['action_menu'][0]['action']
    assert details['normalization']=='provider json_object metadata'
    malformed=dict(raw);malformed['type']='json'
    with pytest.raises(ValueError,match='schema'):
        decode_menu(malformed,c,supplied)
    extra=dict(raw);extra['unexpected']='value'
    with pytest.raises(ValueError,match='schema'):
        decode_menu(extra,c,supplied)


def test_action_adapter_removes_conflicting_language_protocol():
    transport=configure_transport(ChatClient(Settings(api_key='test',model='mock')))
    assert COGNITION_PROTOCOL not in transport._system_prompts[False]
    assert MENU_PROTOCOL in transport._system_prompts[False]


@pytest.mark.parametrize('fixture',json.loads((Path(__file__).parent/'fixtures/v21_menu_failures.json').read_text()),
    ids=lambda f:f['name'])
def test_recorded_menu_failures_have_precise_feedback_without_action_repair(fixture):
    c=fixture['context'];raw=fixture['raw_response'];sup=menu_context(c)
    before=digest([c,raw,sup])
    if fixture['name']=='json_type_metadata':
        _,details=decode_menu(raw,c,sup)
        assert details['normalization']=='provider json_object metadata'
        return
    with pytest.raises(ValueError,match=fixture['original_validation_reason']):
        decode_menu(raw,c,sup)
    feedback=correction_feedback(raw,sup,fixture['original_validation_reason'])
    assert digest([c,raw,sup])==before
    assert feedback['issues']
    if fixture['name']=='fixed_parameter_repeated':
        issue=next(i for i in feedback['issues'] if i['path']=='$.recommended_action.parameters')
        assert issue['expected_value']=={} and issue['expected_fields']==[]
        # A new model response may remove the redundant fields. The decoder did not.
        corrected=deepcopy(raw);corrected['recommended_action']['parameters']={}
        action,_=decode_menu(corrected,c,sup)
        assert action==next(m['action'] for m in sup['action_menu']
                           if m['action_id']==corrected['recommended_action']['action_id'])
    elif fixture['name'].startswith('mismatched_evidence_kind'):
        issue=next(i for i in feedback['issues'] if 'at_least_one_of' in i)
        assert issue['at_least_one_of']
        option=next(m for m in sup['action_menu'] if m['action_id']==raw['recommended_action']['action_id'])
        assert set(issue['at_least_one_of'])<=set(option['parameters']['social']['citations']['allowed_ids'])
        events={e['record_id']:e for e in sup['game']['recent_events']}
        assert issue['cited_records'] and not any(e['matches_required_kind'] for e in issue['cited_records'])
        assert all(e['kind']==events[e['record_id']]['kind'] for e in issue['cited_records'])
    elif fixture['name']=='content_wrapper':
        assert feedback['issues'][0]['path']=='$'


def test_atomic_game_commit_idempotence_and_rejection(tmp_path):
    g,c=context();s=Session(tmp_path/'state.json',{'game_id':'g','config':'x'})
    with pytest.raises(ValueError):s.submit(g,'invalid','propose',(g.leader,['P9','P1']),{})
    assert g.phase=='team'
    s.data['pending_commit']=None;s.save()
    assert s.submit(g,'k','propose',(g.leader,['P1','P2']),{})
    before=Session.game_hash(g)
    assert s.submit(g,'k','propose',(g.leader,['P1','P2']),{}) is False
    assert Session.game_hash(g)==before
    with pytest.raises(StaleState):s.submit(g,'k','propose',(g.leader,['P1','P3']),{})


def test_stale_async_response_cannot_be_accepted(tmp_path):
    s=Session(tmp_path/'state.json',{'game_id':'g'})
    s.current={'new':'state'}
    with pytest.raises(StaleState):s.accept({'old':'state'},{'kind':'PASS'})


def test_resume_replays_accepted_decisions_without_new_calls_and_same_events(tmp_path):
    def run(session,client):
        return play_game(117,'joint_v2',belief_factory=make_version,client_factory=lambda _:client,
            session=session,context_enricher=enrich_context,capture_decisions=True)
    uninterrupted=run(None,ControlledClient(117))
    s=Session(tmp_path/'g/state.json',{'game_id':'g','config':'x'},stop_after=12)
    partial=run(s,ControlledClient(117));assert partial[0]['status']=='failed'
    resumed=Session(tmp_path/'g/state.json',{'game_id':'g','config':'x'})
    client=ControlledClient(117);actual=run(resumed,client)
    assert actual[0]['status']=='completed' and resumed.cached==12
    assert actual[2]['events']==uninterrupted[2]['events']
    assert [d['action'] for d in actual[2]['decisions']]==[d['action'] for d in uninterrupted[2]['decisions']]
    assert client.calls==len(actual[2]['decisions'])-12
    with pytest.raises(ValueError,match='incompatible'):Session(tmp_path/'g/state.json',{'game_id':'g','config':'changed'})


def test_sealed_votes_stay_one_atomic_commit(tmp_path):
    s=Session(tmp_path/'g/state.json',{'game_id':'g'})
    row,_,record=play_game(19,'joint_v2',belief_factory=make_version,client_factory=lambda _:ControlledClient(19),session=s)
    assert row['status']=='completed'
    commits=[c for c in s.data['commits'] if c['method']=='vote']
    assert commits and all(len(c['args'][0])==5 for c in commits)
    assert len(commits)==sum(e['kind']=='TEAM_VOTE' for e in record['events'])


def test_unknown_reservation_survives_restart(tmp_path):
    _,c=context();s=Settings(api_key='test',model='mock',max_tokens=100)
    b=DurableBudget(tmp_path,5,10);uid,r=b.begin(ChatClient(s).request_payload(menu_context(c)),{'decision_id':'d'})
    restored=DurableBudget(tmp_path,5,10)
    assert restored.calls==1 and restored.unknown==1 and restored.charged==r['cny']
    assert restored.usage=={}


def test_separate_transport_and_schema_retries_and_no_fallback(tmp_path):
    _,c=context();seen=[]
    def respond(t,s):
        seen.append(deepcopy(s));t.last_call={'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}
        if len(seen)==1:raise LLMError('connection_error')
        if len(seen)==2:return {'invalid':'schema'}
        return response(s)
    client=MenuClient(Settings(api_key='test',model='mock',retry_delay=0),DurableBudget(tmp_path,5,10),{})
    client.bind({'decision_id':'d','game_id':'g','observer_id':c['view']['self'],'state_version':digest(c['view']),'context_hash':digest(c)})
    with patch.object(ChatClient,'complete',respond):assert client.complete(c)['team']
    rows=[json_read(p) for p in tmp_path.glob('requests/*.response.json')]
    assert len(rows)==3 and sum(r['accepted'] for r in rows)==1
    assert seen[0]==seen[1] and 'validation_feedback' in seen[2]
    assert seen[2]['validation_feedback']['issues'][0]['path']=='$'
    assert all(not r['fallback'] for r in rows)


def test_private_context_cache_isolation(tmp_path):
    g,c=context();s=Session(tmp_path/'g/state.json',{'game_id':'g','config':'v1'})
    s.choose(c,ControlledClient(1))
    other=Session(tmp_path/'g/state.json',{'game_id':'g','config':'v1'})
    changed=deepcopy(c);changed['view']['self']='P5' if c['view']['self']!='P5' else 'P4'
    with pytest.raises(StaleState):other.choose(changed,ControlledClient(1))
    with pytest.raises(ValueError):Session(tmp_path/'g/state.json',{'game_id':'other','config':'v1'})


def test_policy_candidate_only_changes_vote_context():
    g,c=context();assert menu_context(c,POLICY_CURRENT)==menu_context(c,POLICY_CANDIDATE)
    g.propose(g.leader,['P1','P2'])
    while g.phase=='discussion':g.act(g.next_actor,{'kind':'PASS'})
    g.act(g.leader,{'kind':'LOCK'})
    v=g.view('P1');o=make_version('joint_v2',v);c=enrich_context(policy_context(v,o),o)
    a,b=menu_context(c,POLICY_CURRENT),menu_context(c,POLICY_CANDIDATE)
    assert b.pop('decision_context')==vote_context(c) and a==b
    assert c['posterior_hash']==o.snapshot()['posterior_hash']


def test_grouped_denominators_and_unstarted_samples():
    plan={'active':[{'experiment':'A','scenario_id':str(i),'scope':'single_seat','phase':'main','order':['joint_v1','joint_v2']} for i in range(3)],'fixed':[],'repeats':[]}
    jobs=[{'experiment':'A','scenario_id':'0','variant':'joint_v1','status':'completed'},
          {'experiment':'A','scenario_id':'0','variant':'joint_v2','status':'failed'},
          {'experiment':'A','scenario_id':'1','variant':'joint_v1','status':'failed'}]
    rows=pairing(plan,jobs)
    assert sum(r['one_side_completed'] for r in rows)==1
    assert sum(r['fully_paired'] for r in rows)==0
    assert sum(r['status']=='not_run' for r in rows)==1


def test_degenerate_bootstrap_not_equivalence_and_game_clustering():
    assert cluster_delta([('g',0,1)])['status']=='insufficient_sample'
    assert cluster_delta([(str(i),1,1) for i in range(20)])['status']=='degenerate_resampling'
    a=cluster_delta([('a',0,1)]*50+[('b',1,0)]*50)
    assert a['paired_clusters']==2 and a['reference']['denominator']==100
    assert a['equivalence_test']=='not_run'


def test_real_saved_failure_fixtures_reproduce():
    paths=list(Path('results/joint_belief_v2_1/20260918-v21-prechange/historical_audit').glob('*/failure_fixtures.jsonl'))
    if not paths:pytest.skip('Historical run fixtures unavailable in this checkout')
    results=[reproduce_fixture(f) for p in paths for f in load_lines(p)]
    assert len(results)>=5 and all(r['historical_reason_matches'] and r['state_unchanged'] for r in results)


def test_generated_text_never_commits_language_evidence():
    _,c=context();sup=menu_context(c);old=digest(c)
    r=response(sup);r['short_rationale']='I suspect a player.'
    decode_menu(r,c,sup)
    assert digest(c)==old
    r['interpretation']=[{'evidence':[],'summary':'new factor'}]
    with pytest.raises(ValueError):decode_menu(r,c,sup)


def test_same_snapshot_team_order_is_only_semantic_normalization():
    _,c=context();sup=menu_context(c);raw=response(sup)
    action,details=decode_menu(raw,c,sup)
    assert set(action['team'])==set(sup['action_menu'][0]['action']['team'])
    assert details['validated_action']==action


def test_frozen_configuration_rejects_policy_or_dataset_change():
    from avalon.eval.v2.v21_runner import configuration_fingerprint
    c={k:'frozen' for k in ('source_fingerprint','settings','budget_cny','max_calls','adapter_revision',
        'policies','system_sha256','contract_normalization','transport_retries','schema_corrections')}
    original=configuration_fingerprint(c,{'scenes':[1]})
    assert original!=configuration_fingerprint(c,{'scenes':[2]})
    c['policies']='changed';assert original!=configuration_fingerprint(c,{'scenes':[1]})


def test_no_live_opt_in_or_missing_budget_is_rejected(tmp_path):
    from avalon.eval.v2.v21_runner import main
    with pytest.raises(ValueError,match='Explicit'):
        main(['--mode','main','--run-dir',str(tmp_path),'--budget-cny','50'])
    with pytest.raises(ValueError,match='Explicit'):
        main(['--mode','smoke','--run-dir',str(tmp_path),'--live'])


def test_server_repetition_requires_independent_uncached_exact_payloads():
    from avalon.eval.v2.v21_reporting import independent_repeat
    a={'attempt_uid':'a','client_cache_hit':False,'transport':{'request_sha256':'sha'}}
    b={**a,'attempt_uid':'b'}
    assert independent_repeat(a,b)
    assert not independent_repeat(a,a)
    assert not independent_repeat(a,{**b,'client_cache_hit':True})
    assert not independent_repeat(a,{**b,'transport':{'request_sha256':'different'}})


def test_frozen_corpus_content_cannot_change_under_same_manifest(tmp_path):
    from avalon.eval.v2.v21_runner import verify_corpus
    records=[{'scene':'frozen'}]
    f=tmp_path/'source_replays.jsonl';f.write_text(json.dumps(records[0])+'\n')
    plan={'source_replays_sha256':digest(records)}
    verify_corpus(tmp_path,plan)
    f.write_text(json.dumps({'scene':'different'})+'\n')
    with pytest.raises(ValueError,match='corpus changed'):verify_corpus(tmp_path,plan)
