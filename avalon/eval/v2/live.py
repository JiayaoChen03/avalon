"""Explicitly paid, action-only experiment using the existing model transport.

Only legal per-seat contexts enter this module. Truth, variant and policy labels
are host-only journal metadata. Language interpretations never update beliefs.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import re
from pathlib import Path
import threading
import time

from avalon.agents import PROFILE_FIELDS, _discussion_action, _guard_public_speech, validate_plan
from avalon.cognition import BeliefEngine
from avalon.engine import EVIL_ROLES, RESOLVE_COSTS, validate_action
from avalon.llm import ChatClient, LLMError
from avalon.memory import bounded_game_view
from avalon.eval.simulation import canonical, digest
from .population import PopulationClient

PRICING = {"source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
    "verified_date": "2026-09-17", "currency": "CNY", "per_tokens": 1000000,
    "peak": {"hit": .04, "miss": 2., "output": 8.},
    "off_peak": {"hit": .02, "miss": 1., "output": 4.},
    "peak_utc": "Monday-Friday 01:00-04:00 and 06:00-10:00",
    "alias_note": "deepseek-v4-flash is documented to route to V4.1-Flash; returned metadata retained"}


class BudgetStop(RuntimeError):
    pass


def token_cost(usage, rates):
    prompt, output = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(prompt) is not int or type(output) is not int:
        return None
    hit = usage.get("prompt_cache_hit_tokens", 0)
    if not 0 <= hit <= prompt or output < 0:
        raise ValueError("Invalid provider usage")
    return (hit*rates["hit"] + (prompt-hit)*rates["miss"] + output*rates["output"])/1e6


def price_period(utc):
    d = datetime.fromisoformat(utc)
    return "peak" if d.weekday() < 5 and (1 <= d.hour < 4 or 6 <= d.hour < 10) else "off_peak"


class BudgetLedger:
    """Reserve a conservative byte/token bound atomically before every HTTP attempt.

    Unknown usage remains charged at its entire reservation. No estimates are
    silently converted into reported provider token counts or invoice charges.
    """
    def __init__(self, cny, max_calls):
        if not math.isfinite(cny) or cny <= 0 or max_calls < 1:
            raise ValueError("A positive budget and call limit are required")
        self.limit, self.max_calls = cny, max_calls
        self.lock = threading.Lock()
        self.calls = self.unknown = 0
        self.charged = self.pending = self.estimated = 0.
        self.usage = {}; self.halted = False

    def reserve(self, payload):
        # UTF-8 byte length exceeds token count for byte-level tokenizer text;
        # add 1024 for the two messages' framing and future protocol overhead.
        tokens = sum(len(m["content"].encode("utf-8")) for m in payload["messages"])+1024
        output = payload.get("max_tokens", payload.get("max_completion_tokens"))
        bound = (tokens*PRICING["peak"]["miss"]+output*PRICING["peak"]["output"])/1e6
        with self.lock:
            if self.halted or self.calls >= self.max_calls or self.charged+self.pending+bound > self.limit:
                raise BudgetStop("Live budget/call ceiling reached; no additional request sent")
            self.calls += 1; self.pending += bound
        return {"cny":bound,"prompt_tokens_upper_bound":tokens,"output_tokens_upper_bound":output}

    def settle(self, reservation, usage, utc):
        upper = token_cost(usage, PRICING["peak"])
        estimate = token_cost(usage, PRICING[price_period(utc)])
        with self.lock:
            self.pending -= reservation["cny"]
            if upper is None:
                self.charged += reservation["cny"]; self.unknown += 1
            else:
                self.charged += upper; self.estimated += estimate
                if (usage["prompt_tokens"] > reservation["prompt_tokens_upper_bound"]
                        or usage["completion_tokens"] > reservation["output_tokens_upper_bound"]):
                    self.halted = True
                for k,v in usage.items(): self.usage[k] = self.usage.get(k,0)+v
        return {"estimated_cny":estimate,"budget_charged_cny":upper if upper is not None else reservation["cny"],
                "pricing_period":price_period(utc),"usage_status":"reported" if upper is not None else "unavailable"}

    def snapshot(self):
        with self.lock:
            return {"budget_cny":self.limit,"max_calls":self.max_calls,"http_attempts":self.calls,
                "estimated_cny_from_reported_usage":self.estimated,"conservative_budget_charged_cny":self.charged,
                "pending_reserved_cny":max(0.,self.pending),"unknown_usage_attempts":self.unknown,
                "provider_usage":dict(self.usage),"token_bound_violation":self.halted,
                "invoice_cost_cny":None,"cost_note":"Token-price estimate, not an account invoice; peak rates guard budget"}


class Journal:
    def __init__(self, path):
        self.path = Path(path); self.lock=threading.Lock()
    def write(self, value):
        with self.lock, self.path.open("a") as f: f.write(canonical(value)+"\n")


def model_context(context):
    """Identical schema/system for both treatments, with code-owned marginals."""
    view = context["view"]
    game = bounded_game_view(view)
    belief = {"marginals":deepcopy(context["marginals"]),
              "weight_status":"NORMALIZED_POSTERIOR_UNCALIBRATED_LIKELIHOODS"}
    for k in ("team_risk", "team_risks"):
        if k in context: belief[k]=deepcopy(context[k])
    result = {"game":game,"private_knowledge":deepcopy(view["private_knowledge"]),
        "rules":deepcopy(view["rules"]),"private_beliefs":belief,
        "current_resolve":view["resolve"][view["self"]],"legal_actions":deepcopy(view["legal_options"]),
        "memory":{"beliefs":deepcopy(context["marginals"]),"profiles":{
            p["id"]:{k:.5 for k in sorted(PROFILE_FIELDS)} for p in view["players"]}},
        "memory_status":"code_derived_estimates", "pending_language_observations":[],
        "language_interpretation_complete":True,"retrieval_complete":True,"retrieved_chronicle":[]}
    if view["phase"] in {"challenge","reaction"}: result["decision"]="window"
    if view["phase"] in {"exile_nomination","exile_vote"}: result["decision"]=view["phase"]
    result["response_contract"] = response_contract(view)
    return result


def response_contract(view):
    """Machine action schema in user data, matching existing strict validators.

    This resolves the full-plan/special-phase ambiguity without changing the
    author's system prompt, choosing an action, repairing an output, or relaxing
    production legality. No interpretation pass is requested in action-only mode.
    """
    ids=[p["id"] for p in view["players"]]
    def obj(properties):
        return {"type":"object","properties":properties,"required":list(properties),"additionalProperties":False}
    rank={"type":"array","items":{"enum":ids},"minItems":len(ids),"maxItems":len(ids),"uniqueItems":True}
    citations=[e['record_id'] for e in visible_evidence(bounded_game_view(view))]
    social=obj({"card":{"enum":["ACCUSE","DEFEND","HEDGE","PRESSURE","BAIT"]},
        "target":{"enum":ids},"reason":{"enum":["observe","mission_record","vote_pattern","support","test_reaction","team_risk","last_chance","strategy"]},
        "public_writing":{"type":"string","minLength":1,"maxLength":240},
        "citations":{"type":"array","items":{"enum":citations},"maxItems":3,"uniqueItems":True}})
    simple=lambda kind:obj({"kind":{"const":kind}})
    discussion={"oneOf":[simple(k) for k in ("PASS","SOCIAL","COMMITTED_SOCIAL","HOLD")]+[
        obj({"kind":{"const":"CITE"},"evidence":{"enum":citations}}),
        obj({"kind":{"const":"CHALLENGE"},"target":{"enum":[p for p in ids if p!=view['self']]},"evidence":{"enum":citations}})]}
    revision={"oneOf":[simple("LOCK"),obj({"kind":{"const":"REVISE"},"removed":{"enum":view['team']},
                                                        "added":{"enum":[p for p in ids if p not in view['team']]}})]}
    phase=view['phase']
    if phase=='exile_vote':action=obj({'choice':{'enum':view['exile_choices']}})
    elif phase=='exile_nomination':action=obj({'target':{'enum':view['exile_candidates']}})
    elif phase in {'reaction','challenge'}:
        action=obj({'action':{'oneOf':[simple(k) if k in {'SKIP','DECLINE'} else
            obj({'kind':{'const':k},'social':social}) for k in view['legal_actions']]}})
    else:
        action=obj({'strategy':{'enum':['observe','probe','protect','misdirect']},'team_rank':rank,
            'vote_threshold':{'type':'number','minimum':0,'maximum':1},'approve_last':{'type':'boolean'},
            'mission':{'enum':['SUCCESS','FAIL'] if view['role'] in EVIL_ROLES else ['SUCCESS']},
            'social':{'anyOf':[{'type':'null'},social]},'assassin_rank':rank,'discussion':discussion,
            'revision':revision,'strong_vote':{'type':'boolean'}})
    return {'purpose':'Return one JSON instance of this schema, not the schema itself; obey current legal actions. No extra keys or cost annotations.',
            'schema':obj({'belief_updates':{'type':'array','maxItems':0},'interpretation':{'type':'array','maxItems':0},
                         'public_stance_change':{'type':'null'},'recommended_action':action,
                         'short_rationale':{'type':'string','minLength':1,'maxLength':240}})}


def visible_evidence(game):
    """All cited facts actually visible in the bounded prompt, including missions.

    A production mission summary retains its original canonical record ID. Decode
    its sequence solely for the existing evidence validator; never insert this
    projection into a belief engine or create a replay event. Game validates the
    chosen citation against its actual Chronicle again before accepting an action.
    """
    records={e['record_id']:deepcopy(e) for e in game['recent_events']+game['focused_events']}
    for m in game.get('missions',[]):
        match=re.fullmatch(r'R(\d+)-(\d+)',m.get('record_id',''))
        if match is None or int(match[1])!=m['round']:raise ValueError('Invalid canonical public mission reference')
        records.setdefault(m['record_id'],{**deepcopy(m),'seq':int(match[2]),'kind':'MISSION'})
    return list(records.values())


def forced_action(view):
    options=view["legal_options"]
    if view["phase"]=="mission" and len(options)==1 and len(options[0]["cards"])==1:
        return {"card":options[0]["cards"][0]}
    if len(options)==1 and options[0]["kind"] in {"PASS","LOCK","SKIP","DECLINE"}:
        return {"kind":options[0]["kind"]}
    return None


def decode_action(raw, context, supplied):
    """Production envelope/plan/action/privacy validation; no model belief writes."""
    view=context["view"]; pid=view["self"]; phase=view["phase"]
    ids=[p["id"] for p in view["players"]]
    events=visible_evidence(supplied['game'])
    if not isinstance(raw,dict) or raw.get("belief_updates") != [] or "recommended_action" not in raw:
        raise ValueError("Invalid cognition response")
    validator=BeliefEngine(view)
    plan,envelope=validator.unwrap_response(raw,events)
    if phase in {"reaction","challenge"}:
        if set(plan)!={"action"}: raise ValueError("Invalid resource action")
        action=plan["action"]
    elif phase=="exile_nomination":
        if set(plan)!={"target"} or plan["target"] not in view["exile_candidates"]:
            raise ValueError("Invalid council decision")
        action=plan
    elif phase=="exile_vote":
        if set(plan)!={"choice"} or plan["choice"] not in view["exile_choices"]:
            raise ValueError("Invalid council decision")
        action=plan
    else:
        if "beliefs" in plan or "profiles" in plan: raise ValueError("Invalid cognition response")
        plan=validate_plan({**plan,"beliefs":context["marginals"],"profiles":supplied["memory"]["profiles"]},ids,events)
        _guard_public_speech(plan["social"])
        if phase=="team": action={"team":plan["team_rank"][:view["team_size"]]}
        elif phase=="vote":
            risk=(0. if set(view["team"]) & set(view["known_evil"]) else 1.) if view["role"] in EVIL_ROLES else context["team_risk"]
            action={"approve":(view["attempt"]==view["rules"]["max_proposals"] and plan["approve_last"])
                               or risk<=plan["vote_threshold"],
                    "strong":plan["strong_vote"] and view["resolve"][pid]>=RESOLVE_COSTS["STRONG_VOTE"]}
        elif phase=="mission": action={"card":plan["mission"]}
        elif phase=="assassination":
            candidates=[p for p in plan["assassin_rank"] if p not in view["known_evil"] and p!=pid]
            action={"target":max(candidates,key=lambda p:(context["marginals"][p]["merlin"],-plan["assassin_rank"].index(p)))}
        elif phase in {"discussion","council_discussion"}: action=_discussion_action(plan)
        elif phase=="revision": action=deepcopy(plan["revision"])
        else: raise ValueError("Invalid resource action")
    if phase in {"discussion","council_discussion","reaction","challenge","revision"}:
        validate_action(action,ids,events,require_statement=True)
        if action["kind"] not in view["legal_actions"] or RESOLVE_COSTS[action["kind"]]>view["resolve"][pid]:
            raise ValueError("Invalid resource action")
        if action["kind"]=="REVISE" and (action["removed"] not in view["team"] or action["added"] in view["team"]):
            raise ValueError("Invalid resource target")
        if action["kind"]=="CHALLENGE" and action["target"]==pid: raise ValueError("Invalid resource target")
        if "social" in action: _guard_public_speech(action["social"])
    if phase=="mission" and action["card"] not in view["legal_options"][0]["cards"]:
        raise ValueError("Invalid policy")
    validator.validate_stance_intent(envelope,action,phase)
    return action


class LiveClient:
    """No referee state, truth, policy parameters or variant enter complete()."""
    def __init__(self, settings, budget, journal, metadata):
        self.transport=ChatClient(settings); self.settings=settings
        self.budget,self.journal,self.metadata=budget,journal,metadata
        self.calls=self.context_bytes=self.external_calls=self.forced=self.retries=0
        self.usage={}; self.estimated_cost=0.; self.usage_unknown=0

    def complete(self, context):
        self.calls+=1; self.context_bytes+=len(canonical(context).encode())
        immediate=forced_action(context["view"])
        if immediate is not None:
            self.forced+=1; return immediate
        supplied=model_context(context)
        for attempt in range(self.settings.max_retries+1):
            payload=self.transport.request_payload(supplied)
            reservation=self.budget.reserve(payload)
            utc=datetime.now(timezone.utc).isoformat(); started=time.perf_counter()
            self.external_calls+=1; self.retries+=int(attempt>0)
            row={**self.metadata,"observer_id":context["view"]["self"],"phase":context["view"]["phase"],
                "round":context["view"]["round"],"attempt":context["view"]["attempt"],"retry_index":attempt,
                "started_utc":utc,"context":deepcopy(supplied),"context_sha256":digest(supplied),
                "system_sha256":digest(payload["messages"][0]["content"]),"reservation":reservation,
                "fallback":False,"accepted":False}
            error=None;raw=None
            try:
                raw=self.transport.complete(supplied)
                row["response"]=raw
                action=decode_action(raw,context,supplied)
                row.update(accepted=True,action=deepcopy(action))
            except (LLMError,ValueError,TypeError,KeyError) as cause:
                error=cause if isinstance(cause,LLMError) else LLMError("invalid_plan",validation_reason=str(cause))
                row.update(error=str(error),validation_reason=error.validation_reason)
            finally:
                telemetry=deepcopy(self.transport.last_call)
                usage=telemetry.get("usage",{})
                accounting=self.budget.settle(reservation,usage,utc)
                for k,v in usage.items(): self.usage[k]=self.usage.get(k,0)+v
                self.estimated_cost+=accounting["estimated_cny"] or 0.
                self.usage_unknown+=int(accounting["usage_status"]=="unavailable")
                row.update(transport=telemetry,**accounting,elapsed_seconds=time.perf_counter()-started)
                self.journal.write(row)
            if error is None: return action
            if not error.retryable or attempt==self.settings.max_retries: raise error
            if error.retry_feedback:
                supplied["validation_feedback"]={**error.retry_feedback,
                    'rejected_recommended_action':deepcopy(raw.get('recommended_action')) if isinstance(raw,dict) else None,
                    'allowed_action_options':deepcopy(context['view']['legal_options']),
                    'allowed_citation_ids':[e['record_id'] for e in visible_evidence(supplied['game'])],
                    'repair_attempt':attempt+1}
            time.sleep(min(self.settings.retry_delay*2**attempt,30))
        raise AssertionError("unreachable")


class HybridClient:
    def __init__(self, seed, profile, focal, all_seats, live):
        self.population=PopulationClient(seed,profile,None)
        self.focal,self.all_seats,self.live=focal,all_seats,live
        self.calls=self.context_bytes=0
    def complete(self, context):
        self.calls+=1; self.context_bytes+=len(canonical(context).encode())
        if self.all_seats or context["view"]["self"]==self.focal: return self.live.complete(context)
        return self.population.complete(context)
