"""No paid API calls: transport, legal-input and budget contracts."""
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import patch

import pytest

from avalon.engine import Game,make_players
from avalon.llm import ChatClient,Settings,LLMError
from avalon.eval.simulation import policy_context
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2.live import (BudgetLedger,BudgetStop,LiveClient,Journal,
                               model_context,decode_action,forced_action,token_cost,PRICING)
from tests.test_llm import endpoint,envelope


def fixture():
    game=Game(make_players(5,1),seed=1)
    v=game.view(game.leader)
    return policy_context(v,make_version('joint_v2',v))


def answer(c):
    ids=[p['id'] for p in c['view']['players']]
    return {'belief_updates':[],'interpretation':[],'public_stance_change':None,
            'recommended_action':{'strategy':'observe','team_rank':ids,'vote_threshold':.8,
             'approve_last':True,'mission':'SUCCESS','social':None,'assassin_rank':ids,
             'discussion':{'kind':'PASS'},'revision':{'kind':'LOCK'},'strong_vote':False},
            'short_rationale':'Observe public actions.'}


def test_payload_default_compatible_and_temperature_explicit():
    s=Settings(api_key='credential-test-sentinel-873' ,model='test')
    c=ChatClient(s)
    assert 'temperature' not in c.request_payload({})
    c=ChatClient(replace(s,temperature=0))
    p=c.request_payload({})
    assert p['temperature']==0 and 'credential-test-sentinel-873' not in json.dumps(p)


def test_usage_survives_invalid_content_and_reasoning_excluded():
    b=envelope('bad json'); b['usage']={'prompt_tokens':100,'completion_tokens':10,'total_tokens':110}
    with endpoint(b) as (url,_):
        c=ChatClient(Settings(api_key='private-key',base_url=url,model='test'))
        with pytest.raises(LLMError):c.complete({})
    assert c.last_call['usage']['total_tokens']==110
    assert 'PRIVATE_SENTINEL' not in json.dumps(c.last_call)
    assert 'private-key' not in json.dumps(c.last_call)


def test_budget_pending_and_missing_usage_fail_closed():
    c=ChatClient(Settings(model='test',max_tokens=100))
    payload=c.request_payload({})
    b=BudgetLedger(.05,1); r=b.reserve(payload)
    with pytest.raises(BudgetStop):b.reserve(payload)
    b.settle(r,{},'2026-09-17T02:00:00+00:00')
    assert b.snapshot()['conservative_budget_charged_cny']==r['cny']
    assert b.snapshot()['provider_usage']=={}
    assert b.snapshot()['invoice_cost_cny'] is None
    with pytest.raises(BudgetStop):BudgetLedger(.0000001,10).reserve(payload)


def test_cache_and_peak_costs():
    assert token_cost({'prompt_tokens':1000000,'prompt_cache_hit_tokens':500000,'completion_tokens':1000000},PRICING['peak'])==9.02


def test_legal_context_and_no_referee_or_variant_labels():
    c=fixture(); c['truth']='sentinel';c['variant']='joint_v2';c['profile']='heldout_patient'
    supplied=model_context(c)
    assert not any(k in supplied for k in ('truth','variant','profile'))
    assert 'sentinel' not in json.dumps(supplied)
    assert all(set(p)=={'id','name'} for p in supplied['game']['players'])
    assert supplied['pending_language_observations']==[]
    before=deepcopy(c)
    assert len(decode_action(answer(c),c,supplied)['team'])==c['view']['team_size']
    assert before==c


def test_model_cannot_write_beliefs_or_add_language_factors():
    c=fixture();r=answer(c);r['belief_updates']=[{'target':'P1'}]
    with pytest.raises(ValueError):decode_action(r,c,model_context(c))
    r=answer(c);r['recommended_action']['beliefs']={}
    with pytest.raises(ValueError):decode_action(r,c,model_context(c))


def test_real_loopback_wrapper_journals_usage_and_response(tmp_path):
    c=fixture();b=envelope(json.dumps(answer(c)))
    b.update(model='test-returned',system_fingerprint='fp-test',usage={
        'prompt_tokens':200,'completion_tokens':100,'total_tokens':300,'prompt_cache_hit_tokens':100})
    ledger=BudgetLedger(1,2);j=Journal(tmp_path/'calls.jsonl')
    with endpoint(b) as (url,_):
        client=LiveClient(Settings(api_key='never-export-key',base_url=url,model='test',max_retries=0),ledger,j,{'variant':'joint_v2'})
        action=client.complete(c)
    record=json.loads(j.path.read_text())
    assert record['accepted'] and not record['fallback'] and record['action']==action
    assert record['transport']['usage']['total_tokens']==300
    assert 'never-export-key' not in j.path.read_text()
    assert ledger.snapshot()['http_attempts']==1


def test_forced_success_needs_no_model():
    assert forced_action({'phase':'mission','legal_options':[{'kind':'MISSION','cards':['SUCCESS']}]})=={'card':'SUCCESS'}
    assert forced_action({'phase':'mission','legal_options':[{'kind':'MISSION','cards':['SUCCESS','FAIL']}]}) is None


def test_frozen_plan_balanced_and_same_prior_scenarios():
    from avalon.eval.v2.live_runner import freeze_plan,REFERENCE
    plan=freeze_plan(REFERENCE)
    from collections import Counter
    main=[s for s in plan['selected_active'] if s['phase']=='main' and s['scope']=='single_seat']
    assert Counter(s['focal_role'] for s in main)=={'GOOD':10,'MERLIN':10,'EVIL':10,'ASSASSIN':10}
    assert len(plan['selected_active'])==50


def test_concurrent_pending_budget_never_oversubscribed():
    from concurrent.futures import ThreadPoolExecutor
    payload=ChatClient(Settings(model='test',max_tokens=100)).request_payload({})
    b=BudgetLedger(.025,100)
    def reserve(_):
        try:return b.reserve(payload)
        except BudgetStop:return None
    with ThreadPoolExecutor(8) as pool:results=list(pool.map(reserve,range(100)))
    assert 0 < b.pending <= .025
    assert sum(x is not None for x in results)==b.calls


def test_unknown_usage_does_not_fabricate_token_counts(tmp_path):
    c=fixture();ledger=BudgetLedger(1,2);journal=Journal(tmp_path/'calls.jsonl')
    with endpoint(envelope(json.dumps(answer(c)))) as (url,_):
        client=LiveClient(Settings(api_key='test',base_url=url,model='test',max_retries=0),ledger,journal,{})
        client.complete(c)
    record=json.loads(journal.path.read_text())
    assert record['estimated_cny'] is None
    assert record['usage_status']=='unavailable'
    assert ledger.snapshot()['unknown_usage_attempts']==1


def test_team_order_is_not_a_semantic_action_change():
    from avalon.eval.v2.live_analysis import semantic_action
    assert semantic_action({'team':['P2','P1']})==semantic_action({'team':['P1','P2']})
    assert semantic_action({'team':['P1','P3']})!=semantic_action({'team':['P1','P2']})


def test_mock_live_policy_completes_real_game_without_truth_input(tmp_path):
    from avalon.eval.v2.live_runner import live_scenario
    from avalon.eval.v2.experiments import frozen_plan
    spec=next(s for s in frozen_plan('smoke')['active'] if s['scope']=='whole_table')
    seen=set()
    def complete(transport,supplied):
        seen.add(supplied['game']['phase'])
        assert 'truth' not in supplied and 'variant' not in supplied and 'profile' not in supplied
        assert supplied['pending_language_observations']==[]
        ids=[p['id'] for p in supplied['game']['players']]
        raw=answer({'view':{'players':supplied['game']['players']}})
        phase=supplied['game']['phase']
        if phase in {'reaction','challenge'}:
            raw['recommended_action']={'action':{'kind':'SKIP' if phase=='reaction' else 'DECLINE'}}
        elif phase=='exile_nomination':
            raw['recommended_action']={'target':supplied['game']['exile_candidates'][0]}
        elif phase=='exile_vote':raw['recommended_action']={'choice':'ABSTAIN'}
        transport.last_call={'usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200},'model':'mock'}
        return raw
    settings=Settings(api_key='mock',model='mock',max_retries=0,temperature=0)
    with patch.object(ChatClient,'complete',complete):
        row,_,record=live_scenario(spec,'joint_v2',settings,BudgetLedger(50,1000),Journal(tmp_path/'calls'),)
    assert row['status']=='completed',row['error']
    assert {'team','discussion','vote','assassination','exile_nomination','exile_vote'}<=seen
    assert row['external_model_calls']>0 and record['events'][-2]['kind']=='RESULT'


def test_special_phase_contract_does_not_request_a_full_plan():
    from avalon.eval.v2.live import response_contract
    v=fixture()['view'];v['phase']='exile_vote';v['exile_choices']=['APPROVE','REJECT','ABSTAIN']
    contract=response_contract(v)['schema']
    assert contract['properties']['recommended_action']['required']==['choice']
    assert contract['properties']['interpretation']['maxItems']==0
    assert contract['properties']['recommended_action']['additionalProperties'] is False
    v['phase']='team'
    normal=response_contract(v)['schema']['properties']['recommended_action']
    assert normal['properties']['assassin_rank']['minItems']==5
    assert normal['properties']['discussion']['oneOf'][1]['required']==['kind']


def test_earlier_visible_mission_is_valid_citation_but_not_a_new_factor():
    from avalon.eval.v2.live import visible_evidence
    c=fixture();c['view']['missions']=[{'round':1,'attempt':1,'record_id':'R1-010','team':['P1','P2'],
        'success':True,'fail_count':0,'fail_threshold':1}]
    before=deepcopy(c)
    r=answer(c);r['recommended_action']['social']={'card':'HEDGE','target':'P2','reason':'mission_record',
        'public_writing':'先前任务成功，仍待观察。','citations':['R1-010']}
    supplied=model_context(c)
    assert visible_evidence(supplied['game'])[-1]['seq']==10
    assert decode_action(r,c,supplied)['team']
    assert c==before
    r['recommended_action']['social']['citations']=['R1-999']
    with pytest.raises(ValueError):decode_action(r,c,supplied)


def test_retry_returns_rejected_action_and_legal_ranges_without_repair(tmp_path):
    c=fixture();c['view']['phase']='exile_nomination';c['view']['exile_candidates']=['P2','P3']
    c['view']['legal_options']=[{'kind':'NOMINATE_EXILE','targets':['P2','P3']}]
    seen=[]
    def respond(transport,supplied):
        seen.append(deepcopy(supplied))
        raw=answer(c);raw['recommended_action']={'target':'P1' if len(seen)==1 else 'P2'}
        transport.last_call={'usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200}}
        return raw
    with patch.object(ChatClient,'complete',respond):
        client=LiveClient(Settings(api_key='mock',model='mock',max_retries=1,retry_delay=0),BudgetLedger(5,2),Journal(tmp_path/'calls'),{})
        assert client.complete(c)=={'target':'P2'}
    assert seen[1]['validation_feedback']['rejected_recommended_action']=={'target':'P1'}
    assert seen[1]['validation_feedback']['allowed_action_options'][0]['targets']==['P2','P3']
    assert client.retries==1


def test_optional_usage_null_does_not_break_existing_transport():
    b=envelope();b['usage']=None
    with endpoint(b) as (url,_):
        c=ChatClient(Settings(api_key='mock',base_url=url,model='mock'))
        assert c.complete({})=={'ok':True}
    assert c.last_call['usage']=={}
