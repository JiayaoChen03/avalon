"""Versioned action menu and vote-only DecisionContext. No referee access."""
from copy import deepcopy
from itertools import combinations
import math

from avalon.chronicle import EVIDENCE_KINDS, involves
from avalon.engine import CARDS, REASONS, RESOLVE_COSTS, EVIL_ROLES, validate_action
from avalon.agents import _guard_public_speech
from avalon.llm import COGNITION_PROTOCOL, SYSTEM, RESOLVE_PROTOCOL, VALIDATION_HINTS
from avalon.eval.simulation import digest
from .live import model_context, visible_evidence

# r7 supplies a single exact envelope and field-specific correction feedback,
# including the actual public event kinds of rejected citations.
# The only response normalization remains the declared JSON-mode metadata and
# team ordering; invalid choices are returned to the model, never repaired.
ADAPTER_REVISION='legal-menu-v21-r7'
POLICY_CURRENT='menu-current-r1'
POLICY_CANDIDATE='vote-consequences-r1'
ENVELOPE_FIELDS=frozenset({'belief_updates','interpretation','public_stance_change',
    'recommended_action','short_rationale'})
MENU_PROTOCOL='''Private current-state decision protocol.
Return this exact JSON envelope, without a content wrapper:
{"belief_updates":[],"interpretation":[],"public_stance_change":null,"recommended_action":{"action_id":"<supplied ID>","parameters":{}},"short_rationale":"<short label>"}.
Select one supplied action_id. Fill only its listed parameters; keep {} for a
parameter-free option. Its action fields are already fixed: do not repeat them
in parameters. IDs are bound to this state. Never invent players, evidence, or options. Do not return a
full multi-phase plan. All legal teams and ballots remain available. Beliefs are
uncalibrated model estimates, not truth. Preserve roles and private knowledge.
Public social writing must be short printable Chinese, <=240 characters, based
on public facts; do not expose private roles, tactics, or internal probabilities.
For SOCIAL, COMMITTED_SOCIAL, RESPOND, or REACT, parameters.social must contain
exactly card, target, reason, public_writing, and citations. citations is a JSON
array of zero to three supplied record-id strings, for example ["R1-006"]. It is
never an object such as {"ids":["R1-006"]}; do not add an ids wrapper or fields.
For mission_record cite a supplied MISSION; for vote_pattern cite a supplied vote
event; the host rejects a reason when its required event kind is absent. Other
reasons may cite any supplied public event. No text interpretation changes
beliefs. No retrieval is needed.
Assassination retains native probability argmax; ranking only breaks ties.
'''


def configure_transport(transport):
    # A new adapter revision, consistently applied to every arm. World text and
    # production ChatClient are reused; obsolete multi-phase schema is removed.
    # The production cognition protocol describes a different, language-aware
    # envelope and conflicts with this action-only contract (it permits
    # interpretation entries and extra fields). Remove it rather than asking a
    # model to reconcile two schemas. No belief or language feature is enabled.
    transport._system_prompts={k:v.replace(SYSTEM,MENU_PROTOCOL)
                              .replace(RESOLVE_PROTOCOL,'')
                              .replace(COGNITION_PROTOCOL,'')
                              for k,v in transport._system_prompts.items()}
    return transport


def evidence(view):
    records={e['record_id']:e for e in visible_evidence({'recent_events':view.get('recent_events',[]),
        'focused_events':view.get('focused_events',[]),'missions':view.get('missions',[])})}
    for e in view.get('objective_state',{}).get('public_votes',[]):records[e['record_id']]=e
    for e in view.get('legal_public_history',[]):records[e['record_id']]=e
    return [deepcopy(e) for e in records.values() if e['kind'] in EVIDENCE_KINDS]


def legal_menu(view):
    """Entire discrete legal action space, with grammar for free social text."""
    pid=view['self'];ids=[p['id'] for p in view['players']];events=evidence(view)
    actions=[]
    for option in view['legal_options']:
        kind=option['kind']
        if kind=='PROPOSE':
            actions += [{'action':{'team':list(t)},'parameters':{}} for t in combinations(option['candidates'],option['team_size'])]
        elif kind in {'VOTE','STRONG_VOTE'}:
            actions += [{'action':{'approve':b,'strong':kind=='STRONG_VOTE'},'parameters':{}} for b in (False,True)]
        elif kind=='MISSION':actions += [{'action':{'card':c},'parameters':{}} for c in option['cards']]
        elif kind=='ASSASSINATE':
            actions.append({'action':{},'parameters':{'assassin_rank':{'permutation_of':ids}},
                'policy_mapping':'Native Merlin probability argmax; ranking only breaks exact ties.',
                'legal_targets':option['targets']})
        elif kind=='NOMINATE_EXILE':actions += [{'action':{'target':p},'parameters':{}} for p in option['targets']]
        elif kind=='EXILE_VOTE':actions += [{'action':{'choice':p},'parameters':{}} for p in option['choices']]
        elif kind=='REVISE':
            actions += [{'action':{'kind':kind,'removed':a,'added':b},'parameters':{}} for a in option['remove_from'] for b in option['add_from']]
        elif kind in {'CITE','CHALLENGE'}:
            if kind=='CITE' and events:
                actions.append({'action':{'kind':kind},'parameters':{'evidence':{'allowed_ids':[e['record_id'] for e in events]}}})
            if kind=='CHALLENGE':
                by_target={p:[e['record_id'] for e in events if involves(e,p)] for p in ids if p!=pid}
                by_target={p:refs for p,refs in by_target.items() if refs}
                if by_target:actions.append({'action':{'kind':kind},'parameters':{'target':list(by_target),'evidence':{'allowed_ids_by_target':by_target}}})
        elif kind in {'SOCIAL','COMMITTED_SOCIAL','RESPOND','REACT'}:
            allowed_ids=[e['record_id'] for e in events]
            actions.append({'action':{'kind':kind},'parameters':{'social':{
                'card':{'type':'string','allowed_values':list(CARDS)},
                'target':{'type':'string','allowed_values':ids},
                'reason':{'type':'string','allowed_values':list(REASONS)},
                'public_writing':{'type':'string','min_length':1,'max_length':240,'printable':True},
                'citations':{'type':'array','items':'record_id string','min_items':0,'max_items':3,
                    'unique_items':True,'allowed_ids':allowed_ids,
                    'mission_record_requires':[e['record_id'] for e in events if e['kind']=='MISSION'],
                    'vote_pattern_requires':[e['record_id'] for e in events if e['kind'] in {'VOTE','TEAM_VOTE','STRONG_VOTE','EXILE_VOTE','EXILE_RESULT'}],
                    'example':allowed_ids[:1]}}}})
        else:actions.append({'action':{'kind':kind},'parameters':{}})
    # View-only state ID: both belief versions share IDs and ordering on one view.
    state=digest(view)
    return [{'action_id':f'{state[:20]}:{i:03d}',**a} for i,a in enumerate(actions)]


def enrich_context(context, observer):
    c=deepcopy(context);v=c['view'];ids=[p['id'] for p in v['players']]
    if 'public_event_history' in c:
        v['legal_public_history']=[e for e in c.pop('public_event_history') if e['kind'] in EVIDENCE_KINDS]
    if v['phase'] in {'team','vote'}:
        teams=list(combinations(ids,v['team_size']))
        c['joint_team_queries']=[{'team':list(t),**observer.team_query(t,v['rules'])} for t in teams]
        c['probability_model']={'q':.5,'independent_saboteur_cards':True,'fail_threshold':v['rules']['fail_threshold'],
            'note':'Frozen modelling assumption, not opponent policy or calibrated win probability.'}
    c['posterior_hash']=observer.snapshot()['posterior_hash']
    return c


def vote_context(c):
    v=c['view'];queries=c['joint_team_queries'];team=set(v['team'])
    current=next(q for q in queries if set(q['team'])==team)
    ids=[p['id'] for p in v['players']];step=1 if v['speaking_direction']=='clockwise' else -1
    nxt=ids[(ids.index(v['leader'])+step)%len(ids)]
    # Uniform future team is explicitly an assumption, never privileged opponent
    # parameters. No claim about exact game win probability or others' ballots.
    future=math.fsum(q['mission_failure_probability'] for q in queries)/len(queries)
    return {'exact_public_facts':{'mission_score':{'good':v['successes'],'evil':v['failures']},
        'proposal_number':v['attempt'],'rejections_so_far':v['attempt']-1,'max_proposals':v['rules']['max_proposals'],
        'reject_at_limit_winner':'EVIL','next_leader':nxt,'observer_is_next_leader':v['self']==nxt,
        'self_resolve':v['resolve'][v['self']],'strong_vote_cost':RESOLVE_COSTS['STRONG_VOTE'],
        'resolve_refresh_on_rejection':False,'approval_threshold':v['required_approvals'],
        'vote_is_not_unilateral':True},'current_team_model':current,
        'future_model_assumption':{'name':'uniform legal next team; unchanged present belief',
            'expected_mission_failure':future,'not_exact_win_probability':True,'next_proposal_guaranteed':False},
        'decision_comparison':'Compare accepting this mission with another proposal, remaining rejection capacity, next leader and resource costs. No mandatory risk threshold; use your role objective. Approval rate is not an accuracy label.'}


def menu_context(context, policy=POLICY_CURRENT):
    result=model_context(context)
    result.pop('response_contract',None)
    result['game']['recent_events']=evidence(context['view'])
    result['game']['focused_events']=[]
    result['action_menu']=legal_menu(context['view'])
    result['state_version']=digest(context['view'])
    result['response_contract']={'recommended_action':{'action_id':'one exact menu action_id','parameters':'exact fields listed for that option, {} when none'},
        'belief_updates':[],'interpretation':[],'public_stance_change':None,'short_rationale':'short label / supplied public evidence ID; never internal reasoning'}
    if 'joint_team_queries' in context:
        result['private_beliefs']['joint_team_queries']=deepcopy(context['joint_team_queries'])
        result['private_beliefs']['probability_model']=deepcopy(context['probability_model'])
    if policy==POLICY_CANDIDATE and context['view']['phase']=='vote':result['decision_context']=vote_context(context)
    elif policy not in {POLICY_CURRENT,POLICY_CANDIDATE}:raise ValueError('Unknown policy revision')
    return result


def decode_menu(raw, context, supplied):
    v=context['view'];ids=[p['id'] for p in v['players']]
    if digest(v)!=supplied['state_version']:raise ValueError('stale_state')
    normalization=[]
    # Some DeepSeek JSON-mode responses echo the transport response-format
    # discriminator inside the content. It is not a decision field. Allow
    # exactly this predeclared key/value and retain the raw response in the
    # request/response audit; all other extra fields remain schema errors.
    if (isinstance(raw,dict) and set(raw)==ENVELOPE_FIELDS|{'type'}
        and raw.get('type')=='json_object'):
        raw=deepcopy(raw)
        raw.pop('type')
        normalization.append('provider json_object metadata')
    if (not isinstance(raw,dict) or set(raw)!=ENVELOPE_FIELDS
        or raw['belief_updates']!=[] or raw['interpretation']!=[] or raw['public_stance_change'] is not None
        or not isinstance(raw['short_rationale'],str) or not 0<len(raw['short_rationale'])<=240):raise ValueError('schema')
    a=raw['recommended_action']
    if not isinstance(a,dict) or set(a)!={'action_id','parameters'} or not isinstance(a['parameters'],dict):raise ValueError('schema')
    option=next((m for m in legal_menu(v) if m['action_id']==a['action_id']),None)
    if option is None:raise ValueError('unknown_or_stale_action_id')
    params=a['parameters']
    if set(params)!=set(option['parameters']):raise ValueError('schema')
    action=deepcopy(option['action'])
    mapping=None
    if 'assassin_rank' in params:
        rank=params['assassin_rank']
        if not isinstance(rank,list) or len(rank)!=len(ids) or set(rank)!=set(ids):raise ValueError('schema')
        legal=option['legal_targets'];best=max(context['marginals'][p]['merlin'] for p in legal)
        action={'target':next(p for p in rank if p in legal and context['marginals'][p]['merlin']==best)}
        mapping='existing_native_merlin_argmax_with_model_tiebreak'
    elif params:action.update(deepcopy(params))
    validate_legal_action(action,v)
    normalized=deepcopy(action)
    if 'team' in normalized:
        normalized['team']=sorted(normalized['team'])
        if action!=normalized:normalization.append('team member sort')
    normalization_text='; '.join(normalization) if normalization else 'identity'
    return normalized,{'parsed_action':deepcopy(a),'normalized_action':deepcopy(normalized),
        'validated_action':deepcopy(normalized),'normalization':normalization_text,
        'policy_mapping':mapping}


def correction_feedback(raw, supplied, reason):
    """Explain the failed constraint using only the supplied legal contract.

    Feedback neither chooses an alternative action nor changes raw output. The
    next independently billed model response still passes the same validator.
    """
    feedback={'constraint':reason,
        'instruction':'Return the corrected full envelope. Keep the unchanged action_menu; the host will not repair your action.',
        'envelope_fields':sorted(ENVELOPE_FIELDS)}
    parsed=raw if isinstance(raw,dict) else {}
    fields=set(parsed)-({'type'} if parsed.get('type')=='json_object' else set())
    issues=[]
    if fields!=ENVELOPE_FIELDS:
        issues.append({'path':'$','expected_fields':sorted(ENVELOPE_FIELDS),
            'provided_fields':sorted(fields),'rule':'Place the five envelope fields directly at the root. No content wrapper or other fields.'})
    else:
        for name,value in (('belief_updates',[]),('interpretation',[]),('public_stance_change',None)):
            if parsed[name]!=value:issues.append({'path':'$.'+name,'expected_value':value})
        if not isinstance(parsed['short_rationale'],str) or not 0<len(parsed['short_rationale'])<=240:
            issues.append({'path':'$.short_rationale','rule':'Use a nonempty string of at most 240 characters.'})
    selected=parsed.get('recommended_action')
    if isinstance(selected,dict):
        if set(selected)!={'action_id','parameters'}:
            issues.append({'path':'$.recommended_action','expected_fields':['action_id','parameters']})
        option=next((m for m in supplied['action_menu'] if m['action_id']==selected.get('action_id')),None)
        if option is not None:
            params=selected.get('parameters')
            if not isinstance(params,dict) or set(params)!=set(option['parameters']):
                issue={'path':'$.recommended_action.parameters','expected_fields':sorted(option['parameters']),
                    'rule':'Return only the fields listed in this option.parameters; action fields are fixed by action_id and must not be repeated.'}
                if not option['parameters']:issue['expected_value']={}
                issues.append(issue)
            if isinstance(params,dict) and 'social' in option['parameters']:
                social=params.get('social');schema=option['parameters']['social']
                if not isinstance(social,dict) or set(social)!=set(schema):
                    issues.append({'path':'$.recommended_action.parameters.social','expected_fields':sorted(schema),
                        'rule':'Use exactly these fields; do not add resolve_cost, resolve_after or notes.'})
                if isinstance(social,dict):
                    refs=schema['citations']
                    if reason=='Invalid public evidence references':
                        issues.append({'path':'$.recommended_action.parameters.social.citations','expected_schema':refs})
                    if reason=='The reason must cite matching public history':
                        needed=refs.get(social.get('reason','')+'_requires',[])
                        records={e['record_id']:e for e in supplied['game']['recent_events']}
                        cited=social.get('citations',[])
                        issues.append({'path':'$.recommended_action.parameters.social.citations',
                            'reason':social.get('reason'),'at_least_one_of':needed,
                            'cited_records':[{'record_id':ref,'kind':records[ref]['kind'],
                                'matches_required_kind':ref in needed} for ref in cited if ref in records],
                            'rule':'None of these cited records matches the required event kind. A nomination is not a vote. Return a different reason/citation combination that passes the constraint; do not repeat the rejected combination. Choose the correction yourself.'})
        else:issues.append({'path':'$.recommended_action.action_id','rule':'Choose one exact ID from the unchanged action_menu.'})
    else:issues.append({'path':'$.recommended_action','expected_fields':['action_id','parameters']})
    if reason in VALIDATION_HINTS:feedback['production_validation_hint']=VALIDATION_HINTS[reason]
    feedback['issues']=issues
    return feedback


def validate_legal_action(action,v):
    """Local view checks, followed again by actual Game on transaction commit."""
    ids=[p['id'] for p in v['players']];phase=v['phase'];pid=v['self']
    if phase=='team':
        team=action.get('team')
        if set(action)!={'team'} or not isinstance(team,list) or len(team)!=v['team_size'] or len(set(team))!=len(team) or any(p not in ids for p in team):raise ValueError('illegal_team')
    elif phase=='vote':
        if set(action)!={'approve','strong'} or any(type(action[k]) is not bool for k in action):raise ValueError('schema')
        if action['strong'] and 'STRONG_VOTE' not in v['legal_actions']:raise ValueError('insufficient_resource')
    elif phase=='mission':
        if set(action)!={'card'} or action['card'] not in v['legal_options'][0]['cards']:raise ValueError('illegal_mission_card')
    elif phase in {'assassination','exile_nomination'}:
        if set(action)!={'target'} or action['target'] not in v['legal_options'][0]['targets']:raise ValueError('illegal_target')
    elif phase=='exile_vote':
        if set(action)!={'choice'} or action['choice'] not in v['exile_choices']:raise ValueError('illegal_ballot')
    else:
        validate_action(action,ids,evidence(v),require_statement=True)
        if action['kind'] not in v['legal_actions'] or RESOLVE_COSTS[action['kind']]>v['resolve'][pid]:raise ValueError('insufficient_resource')
        if action['kind']=='CHALLENGE' and action['target']==pid:raise ValueError('illegal_target')
        if action['kind']=='REVISE' and (action['removed'] not in v['team'] or action['added'] in v['team']):raise ValueError('illegal_revision')
        if 'social' in action:_guard_public_speech(action['social'])
