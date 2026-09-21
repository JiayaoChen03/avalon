"""Read-only reconstruction of r7 trajectories with two frozen inference engines.

The host may use roles to construct Game and score it. Observers receive only
Game.view(pid) and context_record(public_event), exactly as in v2.1.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import gzip
import json
from pathlib import Path

from avalon.chronicle import PUBLIC_KINDS, context_record
from avalon.engine import Game, Player
from avalon.eval.simulation import canonical, digest, policy_context
from .adapters import make_version, posterior_hash
from .metrics import score
from .v21_contract import enrich_context, menu_context, POLICY_CURRENT, POLICY_CANDIDATE
from .v21_runtime import Session, atomic_json, json_read

VARIANTS = ("joint_v1", "joint_v2")
PROSE = {"public_writing", "statement", "rationale", "short_rationale"}
MECHANICAL_FIELDS = ("round", "attempt", "leader", "phase", "team_size", "team",
    "successes", "failures", "safe_round", "resolve", "lives", "discussion_stage",
    "exile_nominee", "next_actor", "legal_actions", "legal_options",
    "pending_reactions", "reaction_queue", "reaction_trigger", "challenge")


def semantic(value, key=None):
    """Structured semantics, not NLP: only prose and team ordering are ignored.

    Reason codes, citations, AP modifiers and role-exclusive cards still count.
    No public text is removed from the actual belief replay or model input.
    """
    if isinstance(value, dict):
        return {k: semantic(v, k) for k, v in value.items() if k not in PROSE}
    if isinstance(value, list):
        result = [semantic(v) for v in value]
        return sorted(result) if key == "team" else result
    return value


def mechanical_state(game):
    # Full Session.game_hash includes prose/history. This separate, explicitly
    # bounded projection measures physical/phase/legal-option consequences.
    views = {p: {k: v for k, v in game.view(p).items() if k in MECHANICAL_FIELDS}
             for p in game.ids}
    return semantic({"views": views, "spoken": sorted(game.spoken), "winner": game.winner})


def source_transaction(game, decisions, cursor):
    """Translate recorded actions into the existing Game API; never choose one."""
    phase = game.phase
    actors = (game.ids if phase in {"vote", "exile_vote"} else game.team if phase == "mission"
              else [] if phase == "council_result" else
              [next(p for p in game.ids if game.players[p].role == "ASSASSIN")] if phase == "assassination"
              else [game.leader] if phase in {"team", "exile_nomination"} else [game.next_actor])
    selected = decisions[cursor:cursor + len(actors)]
    if len(selected) != len(actors):
        raise ValueError("Source trajectory ends before its recorded transaction")
    for pid, d in zip(actors, selected):
        if (d["observer_id"], d["phase"], d["after_seq"]) != (pid, phase, len(game.events)):
            raise ValueError("Source action schedule does not match production Game")
    actions = {pid: d["action"] for pid, d in zip(actors, selected)}
    if phase == "team": method, args, kw = "propose", [game.leader, actions[game.leader]["team"]], {}
    elif phase in {"discussion", "council_discussion", "revision", "reaction", "challenge"}:
        method, args, kw = "act", [game.next_actor, actions[game.next_actor]], {}
    elif phase == "vote":
        method, args, kw = "vote", [{p: a["approve"] for p, a in actions.items()}], {
            "strong": {p: a["strong"] for p, a in actions.items()}}
    elif phase == "mission": method, args, kw = "resolve_mission", [{p: a["card"] for p, a in actions.items()}], {}
    elif phase == "exile_nomination": method, args, kw = "nominate_exile", [game.leader, actions[game.leader]["target"]], {}
    elif phase == "exile_vote": method, args, kw = "vote_exile", [{p: a["choice"] for p, a in actions.items()}], {}
    elif phase == "council_result": method, args, kw = "finish_council", [], {}
    elif phase == "assassination": method, args, kw = "assassinate", [actors[0], actions[actors[0]]["target"]], {}
    else: raise ValueError("Unsupported recorded phase: " + phase)
    return {"method": method, "args": args, "kwargs": kw, "decisions_through": cursor + len(actors)}


def replay_trajectory(task):
    """One physical source trajectory, both beliefs, no counterfactual actions."""
    record, checkpoint, output, corpus_meta, *extras = task
    saved_posteriors = extras[0] if extras else {}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    game = Game([Player(**p) for p in record["players"]], seed=record["seed"], direction=record["direction"])
    truth = {p["id"]: p["role"] for p in record["players"]}
    initial = {p: game.view(p) for p in game.ids}
    observers = {(p, v): make_version(v, initial[p]) for p in game.ids for v in VARIANTS}
    public = [context_record(e) for e in record["events"] if e["kind"] in PUBLIC_KINDS]
    meta = {"trajectory_id": record["game_id"], **corpus_meta}
    journal = gzip.open(output / "inference.jsonl.gz", "wt")
    scores = gzip.open(output / "belief_trace.jsonl.gz", "wt")
    dfile = gzip.open(output / "decisions.jsonl.gz", "wt")
    mfile = gzip.open(output / "mission_updates.jsonl.gz", "wt")
    prior = {}; endpoints = {}; cursor = 0; decision_cursor = 0; commits_checked = 0
    hashes_checked = 0; observations = 0; duplicate_checks = 0; previous_scores = {}
    posterior_checks = 0; marginal_checks = 0; snapshot_checks = 0
    current_round = 1; last_safe_event = {'seq': 0, 'kind': 'PRIOR', 'round': 1}; inference_closed = False
    occurrence = Counter(); decision_rows = []; mechanical_rows = []
    state = json_read(checkpoint) if checkpoint else None
    state_decisions = state["decisions"] if state else None
    commits = state["commits"] if state else []

    def measure(pid, variant, event, point):
        o = observers[pid, variant]
        metrics = score(o, truth, previous_scores.get((pid, variant)))
        previous_scores[pid, variant] = metrics
        row = {**meta, "observer_id": pid, "observer_role": o.role, "variant": variant,
               "event_seq": event["seq"], "event_kind": event["kind"], "round": event.get('round', game.round), "point": point,
               "posterior_hash": posterior_hash(o.distribution()), **metrics}
        scores.write(canonical(row) + "\n")
        endpoints[pid, variant] = row

    for (pid, variant), observer in observers.items():
        snap = observer.snapshot()
        prior[pid, variant] = snap["posterior_hash"]
        journal.write(canonical({**meta, "observer_id": pid, "variant": variant,
            "kind": "initial", "initial_legal_view": initial[pid], "snapshot": snap}) + "\n")
        measure(pid, variant, {"seq": 0, "kind": "PRIOR"}, "prior")

    def flush():
        nonlocal cursor, observations, duplicate_checks, current_round, last_safe_event, inference_closed
        for e in game.events[cursor:]:
            cursor = e["seq"]
            if e["kind"] not in PUBLIC_KINDS: continue
            event = context_record(e)
            if event['round'] != current_round:
                for pid, variant in observers: measure(pid, variant, last_safe_event, 'round_endpoint')
                current_round = event['round']
            # Post-assassination evidence cannot improve an action already taken.
            if event["kind"] in {"ASSASSINATE", "RESULT"}: inference_closed = True
            if inference_closed: continue
            last_safe_event = event
            for (pid, variant), o in observers.items():
                changed = o.observe(deepcopy(event)); observations += 1
                if changed:
                    journal.write(canonical({**meta, "observer_id": pid, "variant": variant,
                        "kind": "factor_delta", "event": event, "factors": o.last_factors,
                        "posterior_hash": posterior_hash(o.distribution())}) + "\n")
                if event["kind"] == "MISSION":
                    mfile.write(canonical({**meta, "observer_id": pid, **o.last_audit}) + "\n")
                    measure(pid, variant, event, "after_mission")
                before = (o.distribution(), o.marginals())
                o.observe(deepcopy(event)); duplicate_checks += 1
                if before != (o.distribution(), o.marginals()):
                    raise ValueError("Duplicate delivery changed frozen posterior")

    def capture(index, sd=None):
        nonlocal hashes_checked, posterior_checks, marginal_checks, snapshot_checks
        d = record["decisions"][index] if index < len(record["decisions"]) else None
        pid = sd["binding"]["observer_id"] if sd else d["observer_id"]
        phase = game.phase; view = game.view(pid)
        actual_variant = ('joint_v2' if record.get('variant', 'joint_v2').startswith('policy_') else record.get('variant', 'joint_v2'))
        if state and record['scope'] != 'whole_table' and pid != record['observer_id']: actual_variant = 'joint_v1'
        original = observers[pid, actual_variant]
        original_hash = posterior_hash(original.distribution())
        public_prefix = [context_record(e) for e in game.events if e['kind'] in PUBLIC_KINDS]
        actual_c = policy_context(view, original)
        actual_c['public_event_history'] = deepcopy(public_prefix)
        actual_c = enrich_context(actual_c, original)
        if sd:
            ctx_path = Path(checkpoint).parent / "contexts" / f"{index:04d}.json"
            c = json_read(ctx_path)
            if digest(c) != sd["binding"]["context_hash"] or digest(c["view"]) != sd["binding"]["state_version"]:
                raise ValueError("Saved legal input hash mismatch")
            saved = {k: v for k, v in c["view"].items() if k != "legal_public_history"}
            if saved != view: raise ValueError("Saved legal view differs from reconstructed Game")
            if original_hash != c.get('posterior_hash'):
                raise ValueError('reconstruction_mismatch: original posterior differs before decision ' + str(index))
            posterior_checks += 1
            if digest(actual_c) != sd['binding']['context_hash']:
                raise ValueError('reconstruction_mismatch: full original decision context differs')
            hashes_checked += 1
        else:
            if any(view.get(k) != v for k, v in d["view"].items() if k != "legal_public_history"):
                raise ValueError("Source corpus saved legal view mismatch")
        if d:
            if original.marginals() != d['marginals']:
                raise ValueError('reconstruction_mismatch: saved original marginals differ')
            marginal_checks += 1
        for variant, expected in saved_posteriors.get(index, {}).items():
            if posterior_hash(observers[pid, variant].distribution()) != expected:
                raise ValueError('reconstruction_mismatch: stored fixed-snapshot posterior differs')
            snapshot_checks += 1
        action = (sd.get("validated_action") if sd else d["action"])
        if d and (d["after_seq"] != cursor or d["observer_id"] != pid or d["action"] != action):
            raise ValueError("Replay decision and checkpoint disagree")
        key = (game.round, game.attempt, phase, pid); nth = occurrence[key]; occurrence[key] += 1
        row = {**meta, "decision_index": index, "observer_id": pid, "observer_role": view["role"],
            "phase": phase, "round": game.round, "attempt": game.attempt, "occurrence": nth,
            "after_seq": cursor, "status": sd["status"] if sd else "executed",
            "decision_id": sd["binding"]["decision_id"] if sd else None,
            "legal_information_hash": digest({"view": view, "public_history": public_prefix}),
            "legal_view_hash": digest(view), "original_posterior_hash": original_hash,
            "original_belief_variant": actual_variant,
            "base_context_hash": digest(actual_c),
            "model_context_hash": digest(menu_context(actual_c, POLICY_CANDIDATE if record.get('variant') == 'policy_candidate' else POLICY_CURRENT)),
            "source_run": meta.get('source_run_id'), "analysis_split": 'development/diagnostic',
            "is_focal": pid == record.get('observer_id'),
            "is_model_seat": bool(state and (record['scope'] == 'whole_table' or pid == record.get('observer_id'))),
            "proposal_id": next((e['record_id'] for e in game.events if e['kind'] == 'TEAM' and
                (e['round'], e['attempt']) == (game.round, game.attempt)), None),
            "public_prefix_hash": digest(public_prefix), "mechanical_hash": digest(mechanical_state(game)),
            "action": action, "semantic_action": semantic(action),
            "team": sorted(game.team), "leader": game.leader,
            "successes": game.successes, "failures": game.failures,
            "self_resolve": view["resolve"][pid], "required_approvals": view["required_approvals"],
            "legal_menu_options": len(menu_context(actual_c)['action_menu']),
            "evidence_level": 'derived', "reconstruction_status": 'matched_full_posterior_hash' if sd else 'matched_saved_marginals_and_available_snapshots'}
        beliefs = {}
        if phase in {"team", "vote", "assassination"}:
            for variant in VARIANTS:
                o = observers[pid, variant]
                enriched = enrich_context(policy_context(view, o), o)
                snap = o.snapshot()
                beliefs[variant] = {"posterior_hash": snap["posterior_hash"], "worlds": snap["worlds"],
                    "marginals": o.marginals(), "joint_team_queries": enriched.get("joint_team_queries"),
                    "merlin_top": sorted(p for p, m in o.marginals().items() if
                        abs(m["merlin"] - max(x["merlin"] for x in o.marginals().values())) < 1e-12)}
            row["beliefs"] = beliefs
        for variant in VARIANTS:
            measure(pid, variant, {"seq": cursor, "kind": "BEFORE_" + phase.upper()}, "decision")
        dfile.write(canonical(row) + "\n")
        decision_rows.append({k: v for k, v in row.items() if k != "beliefs"})

    try:
        flush()
        while game.phase != "ended":
            if state:
                if commits_checked == len(commits): break
                t = commits[commits_checked]
                if Session.game_hash(game) != t["before"]: raise ValueError("Transaction before hash mismatch")
                if digest([t["method"], t["args"], t["kwargs"]]) != t["action_hash"]:
                    raise ValueError("Transaction action hash mismatch")
            else:
                t = source_transaction(game, record["decisions"], decision_cursor)
            for i in range(decision_cursor, t["decisions_through"]):
                capture(i, state_decisions[i] if state else None)
            decision_cursor = t["decisions_through"]
            getattr(game, t["method"])(*t["args"], **t["kwargs"])
            if state and Session.game_hash(game) != t["after"]:
                raise ValueError("Transaction after hash mismatch")
            mechanical_rows.append({"commit_index": commits_checked, "method": t["method"],
                "event_seq": len(game.events), "mechanical_hash": digest(mechanical_state(game)),
                "mechanical_state": mechanical_state(game)})
            commits_checked += 1
            flush()
        if state:
            for i in range(decision_cursor, len(state_decisions)):
                capture(i, state_decisions[i])
        if game.events != record["events"]: raise ValueError("Reconstructed events differ from r7")
        if state and commits_checked != len(commits): raise ValueError("Unused source commits")
        if not state and decision_cursor != len(record["decisions"]): raise ValueError("Unused source decisions")
        cutoff = next((e['seq'] - 1 for e in game.events if e['kind'] in {'ASSASSINATE', 'RESULT'}), len(game.events))
        for (pid, variant), o in observers.items():
            measure(pid, variant, last_safe_event, 'round_endpoint')
            measure(pid, variant, {'seq': cutoff, 'kind': 'PRE_TERMINAL_OR_PARTIAL'}, 'endpoint')
            journal.write(canonical({**meta, "kind": "final_pre_action_cutoff", "observer_id": pid,
                "variant": variant, "snapshot": o.snapshot()}) + "\n")
        audit = {**meta, "status": "passed", "source_status": record.get("status", "completed"),
            "events_equal": True, "commits_checked": commits_checked, "decision_hashes_checked": hashes_checked,
            "original_posterior_hash_checks": posterior_checks, "original_marginal_checks": marginal_checks,
            "fixed_snapshot_posterior_checks": snapshot_checks,
            "full_posterior_archived_before_each_source_decision": bool(state),
            "source_corpus_limit": None if state else 'Other decisions store marginals, not full posterior; complete events allow deterministic reconstruction, checked at archived fixed snapshots.',
            "decisions": len(decision_rows), "public_observations_delivered": observations,
            "duplicate_checks": duplicate_checks, "source_public_stream_hash": digest(public),
            "initial_view_hashes": {p: digest(v) for p, v in initial.items()},
            "same_legal_stream_to_both_beliefs": True,
            "cutoff": "Stop before first ASSASSINATE/RESULT and exclude all later events; no terminal hindsight"}
        atomic_json(output / "audit.json", audit)
        atomic_json(output / "endpoints.json", list(endpoints.values()))
        atomic_json(output / "alignment.json", {"meta": meta, "decisions": decision_rows,
            "mechanical_states": mechanical_rows, "public_events": public})
        atomic_json(output / "legal_inputs.json", {"meta": meta, "initial_views": initial,
            "public_events": public, "last_inference_seq": cutoff,
            "rebuild": "make_version on initial legal view, then observe public events in seq order up to decision after_seq"})
        return audit
    finally:
        for f in (journal, scores, dfile, mfile): f.close()
