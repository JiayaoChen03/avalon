"""Reuse the production game loop and legal-view replay boundary."""
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, replace
import csv
import gzip
import json
from pathlib import Path
import time

from avalon.chronicle import PUBLIC_KINDS, context_record
from avalon.engine import make_players, EVIL_ROLES
from avalon.eval.beliefs import UPDATE_KINDS
from avalon.eval.joint_belief import CSVOutput, write_json
from avalon.eval.simulation import (play_game, validate_replay, digest, canonical, initial_event, ControlledClient,
                                   policy_context)
from .adapters import VARIANTS, make_version
from .metrics import score
from .population import PopulationClient, PROFILES


def frozen_plan(profile):
    full = profile=="offline_full"
    replay=[]
    for j,(name,split) in enumerate(zip(PROFILES,("development","development","validation","validation","held_out_test","held_out_test"))):
        count = (30 if split=="held_out_test" else 10) if full else 1
        replay += [{"seed":910000+j*1000+i,"profile":name,"split":split,"phase":"replay_source",
                    "scope":"generation","focal":"P1"} for i in range(count)]
    active=[]
    for j,name in enumerate(PROFILES):
        active += [{"seed":920000+j*1000+i,"profile":name,"split":"smoke","phase":"smoke",
                    "scope":"single_seat","focal":f"P{i%5+1}"} for i in range(5 if full else 1)]
    roles=("GOOD","MERLIN","EVIL","ASSASSIN")
    for i in range(200 if full else 8):
        active.append({"seed":940000+i,"profile":("heldout_blend","heldout_patient")[i//4%2],
                       "split":"held_out_test","phase":"main","scope":"single_seat",
                       "focal":f"P{i%5+1}","focal_role":roles[i%4]})
    for i in range(20 if full else 2):
        active.append({"seed":950000+i,"profile":("heldout_blend","heldout_patient")[i%2],
                       "split":"held_out_test","phase":"main","scope":"whole_table","focal":"P1"})
    for s in replay+active:
        s["scenario_id"] = f"{s['phase']}-{s['scope']}-{s['seed']}"
    return {"frozen_before_generation":True,"replay":replay,"active":active,
            "old_corpus":"historical_diagnostic","split_unit":"game/scenario",
            "heldout_mechanisms":"Unseen camouflage/dissent/revision parameter combinations; shared legal action alphabet",
            "policy_parameters":PROFILES,"no_test_tuning":True}


def scenario_players(spec):
    players=make_players(5,spec["seed"])
    if "focal_role" in spec:
        focal=next(p for p in players if p.id==spec["focal"])
        other=next(p for p in players if p.role==spec["focal_role"])
        players=[replace(p,role=other.role) if p.id==focal.id else
                 replace(p,role=focal.role) if p.id==other.id else p for p in players]
    return players


def run_scenario(spec, variant):
    generation=spec["scope"]=="generation"
    row,trace,record=play_game(spec["seed"],variant,phase=spec["phase"],
        player_setup=scenario_players(spec),focal=spec["focal"],all_seats=generation or spec["scope"]=="whole_table",
        belief_factory=make_version,
        client_factory=lambda s:PopulationClient(s,spec["profile"],None if generation else spec["focal"]),
        capture_decisions=True if generation else "compact")
    for data in (row,record):
        data.update({k:spec[k] for k in ("scenario_id","profile","split","scope")})
    row["pair_id"]=spec["scenario_id"]
    row["pair_signature"]=digest({"game_signature":row["pair_signature"],"spec":spec,
                                  "policy_parameters":PROFILES[spec["profile"]]})
    record["status"],record["error"]=row["status"],row["error"]
    truth={p["id"]:p["role"] for p in record["players"]}
    events=record["events"]
    for label,teams in (("proposed",[e for e in events if e["kind"] in {"TEAM","TEAM_REVISE"}]),
                        ("approved",[e for e in events if e["kind"]=="TEAM_VOTE" and e["approved"]]),
                        ("executed",[e for e in events if e["kind"]=="MISSION"])):
        row[label+"_clean_teams"]=sum(all(truth[p] not in EVIL_ROLES for p in e["team"]) for e in teams)
        row[label+"_team_count"]=len(teams)
    for decision in record.get("decisions",[]):
        decision.update({k:row[k] for k in ("game_id","scenario_id","profile","split","scope","variant")})
        decision["validation"]="accepted_by_game" if row["status"]=="completed" else "game_failed_see_error"
    return row,trace,record


def run_pair_spec(spec):
    order=("joint_v1","joint_v2") if spec["seed"]%2==0 else ("joint_v2","joint_v1")
    out={v:run_scenario(spec,v) for v in order}
    if len({x[0]["pair_signature"] for x in out.values()})!=1: raise ValueError("Pair controls differ")
    return [out[v] for v in ("joint_v1","joint_v2")]


def replay_to_files(task):
    record,folder=task
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=False)
    game,truth=validate_replay(record)
    public=[context_record(e) for e in record["events"] if e["kind"] in PUBLIC_KINDS]
    trace=CSVOutput(folder/"belief_trace.csv",["game_id","variant"])
    missions=CSVOutput(folder/"mission_update_audit.csv",["game_id","variant"])
    audits=[]
    with gzip.open(folder/"hypothesis_trace.jsonl.gz","wt") as hypotheses:
        for pid in game.ids:
            view=game.view(pid)
            for variant in VARIANTS:
                observer=make_version(variant,deepcopy(view))
                previous=None; available=True; received=[]
                for event in [initial_event(),*public]:
                    t=time.perf_counter()
                    if event["kind"]!="PRIOR":
                        supplied=deepcopy(event); received.append(supplied)
                        observer.observe(supplied)
                    elapsed=(time.perf_counter()-t)*1000
                    if event["kind"] in {"ASSASSINATE","RESULT"}: available=False
                    context={"game_id":record["game_id"],"seed":record["seed"],"split":record["split"],
                             "profile":record["profile"],"phase":"replay","variant":variant,"observer_id":pid,
                             "observer_role":observer.role,"event_id":event.get("record_id",str(event["seq"])),
                             "event_seq":event["seq"],"event_kind":event["kind"],"round":event["round"],
                             "attempt":event.get("attempt",0),"decision_available":int(available)}
                    if event["kind"] in UPDATE_KINDS|{"PRIOR"}:
                        metrics=score(observer,truth,previous)
                        trace.append([{**context,"belief_update_ms":elapsed,**metrics}]); previous=metrics
                        hypotheses.write(canonical({**context,**observer.snapshot()})+"\n")
                    if observer.last_audit:
                        missions.append([{**context,**observer.last_audit}])
                    if event["kind"]!="PRIOR":
                        before=(observer.distribution(),observer.marginals())
                        observer.observe(deepcopy(event))
                        if before!=(observer.distribution(),observer.marginals()):
                            raise ValueError(f"Duplicate changed {variant} {record['game_id']}")
                        if observer.last_audit: missions.append([{**context,**observer.last_audit}])
                if received!=public: raise ValueError("Observer mutated legal stream")
                audits.append({"game_id":record["game_id"],"observer_id":pid,"variant":variant,
                    "initial_view_digest":digest(view),"observation_stream_digest":digest(received),
                    "observations":len(received),"duplicate_delivery_check":"passed",
                    "private_input_boundary":"Game.view(pid); public context_record only"})
    trace.close();missions.close();write_json(folder/"audit.json",audits)
    return str(folder)


def fixed_snapshot_actions(record):
    """P2 counterfactual actions on identical legal snapshots, after P1 completes.

    Actual game outcomes are NOT attributed to these counterfactual alternatives.
    """
    if not record.get("decisions"): return []
    game,truth=validate_replay(record)
    by_pid=defaultdict(list)
    for d in record["decisions"]:
        if (d["view"]["role"]=="GOOD" and d["phase"] in {"team","vote"}
                or d["phase"]=="assassination"):
            by_pid[d["observer_id"]].append(d)
    result=[]
    public=[context_record(e) for e in record["events"] if e["kind"] in PUBLIC_KINDS]
    for pid,decisions in by_pid.items():
        observers={v:make_version(v,game.view(pid)) for v in ("joint_v1","joint_v2")}
        cursor=0
        for d in decisions:
            while cursor<len(public) and public[cursor]["seq"]<=d["after_seq"]:
                for o in observers.values():o.observe(public[cursor])
                cursor+=1
            for variant,o in observers.items():
                view=d["view"]; context=policy_context(view,o)
                client=ControlledClient(record["seed"]+700000003)
                original=client.complete(context)
                candidates=[]; independent=deepcopy(context); jointquest=deepcopy(context)
                if d["phase"] in {"team","vote"}:
                    teams=([key.split(",") for key in context["team_risks"]] if d["phase"]=="team" else [view["team"]])
                    for team in teams:
                        query=o.team_query(team,view["rules"])
                        marginalrisk=1
                        for p in team:marginalrisk*=1-o.marginals()[p]["evil"]
                        candidates.append({"team":team,**query,"independent_dirty_risk":1-marginalrisk,
                                           "actual_evil_count_offline":sum(truth[p] in EVIL_ROLES for p in team)})
                    if d["phase"]=="team":
                        independent["team_risks"]={",".join(x["team"]):x["independent_dirty_risk"] for x in candidates}
                        jointquest["team_risks"]={",".join(x["team"]):x["mission_failure_probability"] for x in candidates}
                    else:
                        independent["team_risk"]=candidates[0]["independent_dirty_risk"]
                        jointquest["team_risk"]=candidates[0]["mission_failure_probability"]
                    alternate=client.complete(jointquest); marginal_action=client.complete(independent)
                else:
                    alternate=deepcopy(original);marginal_action=deepcopy(original)
                    legal=next(x["targets"] for x in view["legal_options"] if x["kind"]=="ASSASSINATE")
                    candidates=[{"target":p,"merlin_probability":o.marginals()[p]["merlin"]} for p in legal]
                result.append({"experiment":"fixed_posterior_policy" if d["phase"]!="assassination" else "fixed_assassin_snapshot",
                    "game_id":record["game_id"],"profile":record["profile"],"split":record["split"],
                    "observer_id":pid,"observer_role":view["role"],"after_seq":d["after_seq"],"phase":d["phase"],
                    "variant":variant,"legal_view_hash":digest(view),"posterior_hash":o.snapshot()["posterior_hash"],
                    "original_action":original,"marginal_only_action":marginal_action,"joint_quest_action":alternate,
                    "action_changed":int(original!=alternate),"marginal_vs_joint_changed":int(marginal_action!=original),
                    "actual_action":d["action"],"candidates":candidates,"attempt":view["attempt"],
                    "legal_options":view["legal_options"],"resolve":view["resolve"],
                    "assassin_hit_offline":int(truth[original.get("target",pid)]=="MERLIN") if d["phase"]=="assassination" else None,
                    "counterfactual_execution":"not_run; fixed-snapshot choices only"})
    return result
