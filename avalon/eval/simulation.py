"""Paired controlled games and passive replay, using the unchanged Game rules."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import time

from avalon.chronicle import PUBLIC_KINDS, context_record, record_id
from avalon.engine import CARDS, EVIL_ROLES, MAX_RESOLVE, RESOLVE_COSTS, Game, Player, make_players
from avalon.evidence import LikelihoodConfig

from .beliefs import UPDATE_KINDS, make_beliefs, score_beliefs


POLICY_CONFIG = {
    "version": "controlled-v1", "vote_risk_threshold": .8, "approve_last": True,
    "early_fail_probability": .75, "later_fail_probability": .9,
    "opponents": "baseline beliefs with the same controlled-v1 decision policy",
    "treatment": "P1 belief architecture only; no shared evil strategy manager",
    "team_utility": "minimize probability of at least one Evil (independent/native joint query)",
    "assassination_utility": "maximize own Merlin marginal",
    "language_evidence": "none; formal public actions still supply behavioral evidence",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def keyed_uniform(seed, *key):
    # A common random number at each semantic decision coordinate. Divergent
    # games cannot shift a shared mutable PRNG stream or affect later tie breaks.
    n = int(hashlib.sha256(canonical([seed, *key]).encode()).hexdigest()[:13], 16)
    return (n + .5) / 16 ** 13


class ControlledClient:
    """Small, deterministic complete(context) mock; no API, environment, or truth.

    Both architectures call exactly this policy. Temperature adds keyed Gumbel
    noise to candidate utilities. The policy never receives a variant name.
    """

    def __init__(self, seed, temperature=0, responses=None, model="controlled-v1"):
        self.seed, self.temperature, self.responses, self.model = seed, temperature, responses, model
        self.calls = self.context_bytes = 0

    def complete(self, context):
        self.calls += 1
        self.context_bytes += len(canonical(context).encode())
        v, b = context["view"], context["marginals"]
        pid, phase = v["self"], v["phase"]
        coordinate = (pid, v["round"], v["attempt"], phase)
        if self.model == "fixture-v1":
            key = ":".join(map(str, coordinate))
            response = self.responses.get(key, self.responses.get(phase))
            if response is None:
                raise ValueError(f"Missing controlled response: {key}")
            return deepcopy(response)

        def pick(candidates, utility, label):
            def score(candidate):
                u = keyed_uniform(self.seed, *coordinate, label, candidate)
                noise = -math.log(-math.log(u))
                return utility(candidate) + self.temperature * noise, u
            return max(candidates, key=score)

        ids = [p["id"] for p in v["players"]]
        evil = v["role"] in EVIL_ROLES
        known = set(v["known_evil"])
        if phase == "team":
            teams = list(combinations(ids, v["team_size"]))
            if evil:
                utility = lambda team: -abs(len(set(team) & known) - 1) - .1 * (pid not in team)
            else:
                utility = lambda team: -context["team_risks"][",".join(team)]
            return {"team": list(pick(teams, utility, "team"))}
        if phase == "vote":
            risk = context["team_risk"]
            approve = bool(set(v["team"]) & known) if evil else risk <= POLICY_CONFIG["vote_risk_threshold"]
            return {"approve": approve or v["attempt"] == 5, "strong": False}
        if phase == "mission":
            dirty = sorted(set(v["team"]) & known)
            probability = POLICY_CONFIG["early_fail_probability" if v["round"] == 1 else "later_fail_probability"]
            fail = (evil and pid == dirty[0] and (v["successes"] == 2
                    or keyed_uniform(self.seed, *coordinate, "fail") < probability))
            return {"card": "FAIL" if fail else "SUCCESS"}
        if phase == "assassination":
            candidates = [p for p in ids if p not in known and p != pid]
            return {"target": pick(candidates, lambda p: b[p]["merlin"], "assassination")}
        if phase in {"discussion", "council_discussion"}:
            if v["resolve"][pid] == 0:
                return {"kind": "PASS"}
            candidates = [p for p in ids if p != pid]
            if evil:
                defend = keyed_uniform(self.seed, *coordinate, "defend") < .35
                candidates = [p for p in candidates if (p in known) == defend]
                target = pick(candidates, lambda p: b[p]["merlin"], "speech")
                card = "DEFEND" if defend else "ACCUSE"
            else:
                target = pick(candidates, lambda p: b[p]["evil"], "speech")
                card = "ACCUSE" if b[target]["evil"] > .55 else "HEDGE"
            writing = {"ACCUSE": f"I question {target}'s choices on this proposal.",
                       "DEFEND": f"I support {target}'s participation on this proposal.",
                       "HEDGE": f"I am still uncertain about {target}."}[card]
            return {"kind": "SOCIAL", "social": {"card": card, "target": target, "reason": "observe",
                                                     "public_writing": writing, "citations": []}}
        if phase in {"revision", "reaction", "challenge"}:
            return {"kind": {"revision": "LOCK", "reaction": "SKIP", "challenge": "DECLINE"}[phase]}
        if phase == "exile_nomination":
            candidates = [p for p in v["exile_candidates"] if p != pid] or v["exile_candidates"]
            return {"target": pick(candidates, lambda p: b[p]["evil"] * (-1 if evil else 1), "exile")}
        if phase == "exile_vote":
            target = v["exile_nominee"]
            approve = target not in known if evil else b[target]["evil"] > .75
            return {"choice": "APPROVE" if approve else "ABSTAIN"}
        raise ValueError(f"Unhandled game phase: {phase}")


def policy_context(view, beliefs):
    context = {"view": deepcopy(view), "marginals": beliefs.marginals()}
    ids = [p["id"] for p in view["players"]]
    if view["phase"] == "team":
        context["team_risks"] = {",".join(t): beliefs.team_risk(t) for t in combinations(ids, view["team_size"])}
    elif view["phase"] == "vote":
        context["team_risk"] = beliefs.team_risk(view["team"])
    return context


def trace_row(game_id, seed, phase, variant, observer, event, metrics, *, changed=True, elapsed=0, decision=True):
    return {"game_id": game_id, "seed": seed, "phase": phase, "round": event["round"],
            "attempt": event.get("attempt", 0), "event_id": event.get("record_id", record_id(event)),
            "event_kind": event["kind"], "variant": variant, "observer_id": observer.pid,
            "observer_role": observer.role, "belief_changed": int(changed),
            "decision_available": int(decision), "belief_update_ms": elapsed * 1000, **metrics}


def initial_event():
    return {"round": 0, "attempt": 0, "seq": 0, "kind": "PRIOR", "record_id": "INITIAL_PRIVATE_KNOWLEDGE"}


def play_game(seed, variant, *, phase="tournament", players=5, temperature=0, model="controlled-v1",
              likelihood=None, responses=None, belief_factory=None, client_factory=None,
              player_setup=None, focal="P1", all_seats=False, capture_decisions=False,
              session=None, context_enricher=None):
    """Only the focal seat changes between variants. Errors are recorded, not repaired."""
    started = time.perf_counter()
    game = Game(player_setup or make_players(players, seed), seed=seed)
    game_id = f"{phase}-{seed}-{variant}"
    truth = {pid: p.role for pid, p in game.players.items()}
    base_views = {pid: game.view(pid) for pid in game.ids}
    factory = belief_factory or make_beliefs
    observers = {pid: factory(variant if pid == focal or all_seats else
                                 "reference" if variant == "reference" else "baseline", view, likelihood)
                 for pid, view in base_views.items()}
    client = client_factory(seed) if client_factory else ControlledClient(seed, temperature, responses, model)
    decisions = []
    signature = digest({"roles": truth, "seed": seed, "rules": base_views[focal]["rules"],
                        "direction": game.direction, "initial_leader": game.leader,
                        "cards": CARDS, "max_resolve": MAX_RESOLVE, "resolve_costs": RESOLVE_COSTS,
                        "policy": POLICY_CONFIG, "model": model, "temperature": temperature,
                        "responses": responses, "likelihood": asdict(likelihood or LikelihoodConfig())})
    previous = score_beliefs(observers[focal], truth)
    final_score = previous
    trace = [trace_row(game_id, seed, phase, variant, observers[focal], initial_event(), previous)]
    cursor, observations, update_seconds, update_calls = 0, [], 0.0, 0
    status, error, invalid, failures, operation = "completed", "", 0, 0, "belief"
    decision_available = True

    def flush():
        nonlocal cursor, previous, final_score, update_seconds, update_calls, decision_available, operation
        operation = "belief"
        for raw in game.chronicle.since(cursor):
            cursor = raw["seq"]
            if raw["kind"] not in PUBLIC_KINDS:
                continue
            event = context_record(raw)
            if event["kind"] in {"ASSASSINATE", "RESULT"}:
                decision_available = False
            observations.append(event)
            for pid, observer in observers.items():
                t = time.perf_counter()
                changed = observer.observe(deepcopy(event))
                elapsed = time.perf_counter() - t
                if pid != focal:
                    continue
                update_seconds += elapsed
                update_calls += 1
                if event["kind"] in UPDATE_KINDS:
                    metrics = score_beliefs(observer, truth, previous)
                    trace.append(trace_row(game_id, seed, phase, variant, observer, event, metrics,
                                           changed=changed, elapsed=elapsed, decision=decision_available))
                    previous = metrics
                    if decision_available:
                        final_score = metrics

    def choose(pid):
        nonlocal operation
        operation = "action"
        context = policy_context(game.view(pid), observers[pid])
        if context_enricher is not None:
            context['public_event_history'] = deepcopy(observations)
            context = context_enricher(context, observers[pid])
        action = session.choose(context, client) if session is not None else client.complete(context)
        if capture_decisions:
            saved_view = deepcopy(context["view"])
            if capture_decisions == "compact" or game.phase not in {"team", "vote", "assassination"}:
                saved_view = {k: v for k, v in saved_view.items() if k in {
                    "self", "role", "known_evil", "players", "round", "attempt", "phase", "team",
                    "team_size", "rules", "successes", "failures", "legal_options", "legal_actions",
                    "resolve", "resolve_costs", "max_resolve", "private_knowledge"}}
            # Host-only diagnostic archive; never supplied back to any client.
            decisions.append({"observer_id": pid, "after_seq": cursor,
                "phase": game.phase, "round": game.round, "attempt": game.attempt,
                "view": saved_view, "input_hash": digest(context),
                "marginals": deepcopy(context["marginals"]),
                "team_risks": context.get("team_risks"), "team_risk": context.get("team_risk"),
                "action": deepcopy(action)})
        return action

    def submit(method, *args, **kwargs):
        if session is not None:
            return session.commit(game, method, *args, **kwargs)
        return getattr(game, method)(*args, **kwargs)

    try:
        flush()
        for _ in range(1500):
            if game.phase == "ended":
                break
            phase_now = game.phase
            if phase_now == "team":
                submit("propose", game.leader, choose(game.leader)["team"])
            elif phase_now in {"discussion", "council_discussion", "revision", "reaction", "challenge"}:
                submit("act", game.next_actor, choose(game.next_actor))
            elif phase_now == "vote":
                # All choices are collected before any sealed vote is published.
                ballots = {pid: choose(pid) for pid in game.ids}
                submit("vote", {p: b["approve"] for p, b in ballots.items()},
                          strong={p: b["strong"] for p, b in ballots.items()})
            elif phase_now == "mission":
                cards = {pid: choose(pid)["card"] for pid in game.team}
                submit("resolve_mission", cards)
            elif phase_now == "exile_nomination":
                submit("nominate_exile", game.leader, choose(game.leader)["target"])
            elif phase_now == "exile_vote":
                submit("vote_exile", {pid: choose(pid)["choice"] for pid in game.ids})
            elif phase_now == "council_result":
                submit("finish_council")
            elif phase_now == "assassination":
                assassin = next(pid for pid, role in truth.items() if role == "ASSASSIN")
                submit("assassinate", assassin, choose(assassin)["target"])
            else:
                raise ValueError(f"Unsupported phase: {phase_now}")
            flush()
        else:
            raise RuntimeError("Game exceeded the action limit")
    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        invalid, failures = int(operation == "action"), int(operation == "belief")

    events = game.events
    teams = [e for e in events if e["kind"] in {"TEAM", "TEAM_REVISE"}]
    good_led = [e for e in teams if truth[e["actor"]] not in EVIL_ROLES]
    focal_led = [e for e in good_led if e["actor"] == focal]
    attacks = [e for e in events if e["kind"] == "ASSASSINATE"]
    hit = int(bool(attacks) and truth[attacks[-1]["target"]] == "MERLIN")
    alignment = "EVIL" if truth[focal] in EVIL_ROLES else "GOOD"
    row = {
        "game_id": game_id, "pair_id": f"{phase}-{seed}", "phase": phase, "seed": seed,
        "variant": variant, "status": status, "error": error, "pair_signature": signature,
        "roles": canonical(truth), "focal_id": focal, "focal_role": truth[focal], "focal_alignment": alignment,
        "winner": game.winner, "focal_win": int(game.winner == alignment) if status == "completed" else None,
        "terminal_reason": next((e.get("reason", "unspecified") for e in reversed(events)
                                  if e["kind"] == "RESULT"), None),
        "good_win": int(game.winner == "GOOD") if status == "completed" else None,
        "evil_win": int(game.winner == "EVIL") if status == "completed" else None,
        "assassination_opportunities": len(attacks), "merlin_assassinated": hit,
        "quest_count": len(game.missions), "successful_quests": game.successes, "failed_quests": game.failures,
        "proposed_teams": len(teams), "proposed_team_slots": sum(len(e["team"]) for e in teams),
        "good_proposed_slots": sum(truth[p] not in EVIL_ROLES for e in teams for p in e["team"]),
        "good_led_teams": len(good_led), "good_led_slots": sum(len(e["team"]) for e in good_led),
        "evil_in_good_led_slots": sum(truth[p] in EVIL_ROLES for e in good_led for p in e["team"]),
        "dirty_good_led_teams": sum(any(truth[p] in EVIL_ROLES for p in e["team"]) for e in good_led),
        "focal_good_led_slots": sum(len(e["team"]) for e in focal_led),
        "focal_good_led_evil_slots": sum(truth[p] in EVIL_ROLES for e in focal_led for p in e["team"]),
        "invalid_actions": invalid, "belief_engine_failures": failures,
        "game_length_rounds": game.round, "game_length_events": len(events),
        "game_seconds": time.perf_counter() - started,
        "belief_update_ms": update_seconds * 1000, "belief_observations": update_calls,
        "mock_calls": client.calls, "context_bytes": client.context_bytes,
        "external_model_calls": 0, "model_tokens": None, "model_cost": None,
        "observation_digest": digest(observations),
    }
    row.update({f"final_{k}": v for k, v in final_score.items()})
    for flag in ("entropy_down_truth_down", "overconfident_wrong_world", "overconfident_wrong_marginals",
                 "distribution_collapsed", "truth_probability_collapsed"):
        row[f"{flag}_updates"] = sum(t[flag] for t in trace if t["decision_available"])
    record = {"schema_version": 1, "game_id": game_id, "seed": seed, "direction": game.direction,
              "players": [asdict(p) for p in game.players.values()], "events": events}
    if capture_decisions:
        record["decisions"] = decisions
    return row, trace, record


def run_pair(task):
    seed, phase, settings = task
    # Counterbalance order to limit warm-up and machine-load bias in latency.
    variants = list(settings["variants"])
    order = variants if seed % 2 == 0 else list(reversed(variants))
    kwargs = {k: v for k, v in settings.items() if k != "variants"}
    results = {v: play_game(seed, v, phase=phase, **kwargs) for v in order}
    if len({result[0]["pair_signature"] for result in results.values()}) != 1:
        raise ValueError("Pair configuration mismatch")
    return [(results[v][0], results[v][1]) for v in variants]


def validate_replay(record):
    """Validate a completed host archive; rebuild private views rather than trust saved views."""
    if record.get("schema_version") != 1 or not isinstance(record.get("game_id"), str):
        raise ValueError("Replay requires schema_version=1 and game_id")
    if type(record.get("seed")) is not int:
        raise ValueError("Replay requires an integer seed")
    players = [Player(**p) for p in record["players"]]
    game = Game(players, seed=record["seed"], direction=record["direction"])
    truth = {p.id: p.role for p in players}
    events = record["events"]
    if not events or events[0]["kind"] != "START":
        raise ValueError("Replay must begin at START, before any belief evidence")
    seqs = [e["seq"] for e in events]
    if seqs != list(range(1, len(events) + 1)):
        raise ValueError("Replay events must have unique, contiguous chronological sequence IDs")
    reveals = [e for e in events if e["kind"] == "REVEAL"]
    results = [e for e in events if e["kind"] == "RESULT"]
    if (len(reveals) != 1 or reveals[0].get("roles") != truth or len(results) != 1
            or results[0].get("winner") not in {"GOOD", "EVIL"}
            or events[-1]["kind"] != "REVEAL" or events[-2]["kind"] != "RESULT"):
        raise ValueError("Replay needs one terminal RESULT/REVEAL matching ground-truth roles")
    for event in events:
        if event.get("record_id", record_id(event)) != record_id(event):
            raise ValueError("Replay record ID disagrees with its sequence")
        if event["kind"] == "MISSION":
            capacity = sum(truth[p] in EVIL_ROLES for p in event["team"])
            if not 0 <= event["fail_count"] <= capacity:
                raise ValueError("Replay mission contradicts ground-truth roles")
    return game, truth


def load_replays(path):
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if not records or len({r["game_id"] for r in records}) != len(records):
        raise ValueError("Replay corpus must contain distinct completed games")
    for record in records:
        validate_replay(record)
    return records


def replay_game(record, variants, likelihood=None):
    """Both variants see equal detached observations. No replay controller exists."""
    game, truth = validate_replay(record)
    public = [context_record(e) for e in record["events"] if e["kind"] in PUBLIC_KINDS]
    traces, audits = [], []
    for pid in game.ids:
        view = game.view(pid)
        observers = {v: make_beliefs(v, deepcopy(view), likelihood) for v in variants}
        previous, received = {}, {v: [] for v in variants}
        for variant, observer in observers.items():
            previous[variant] = score_beliefs(observer, truth)
            traces.append(trace_row(record["game_id"], record["seed"], "replay", variant,
                                    observer, initial_event(), previous[variant]))
        decision_available = True
        for event in public:
            if event["kind"] in {"ASSASSINATE", "RESULT"}:
                decision_available = False
            for variant, observer in observers.items():
                supplied = deepcopy(event)
                received[variant].append(supplied)
                t = time.perf_counter()
                changed = observer.observe(supplied)
                elapsed = time.perf_counter() - t
                if event["kind"] in UPDATE_KINDS:
                    metrics = score_beliefs(observer, truth, previous[variant])
                    traces.append(trace_row(record["game_id"], record["seed"], "replay", variant, observer,
                                            event, metrics, changed=changed, elapsed=elapsed,
                                            decision=decision_available))
                    previous[variant] = metrics
                # A repeated delivery must not move probabilities, including at
                # the history-buffer boundary. This audits BOTH replay variants.
                before = (observer.distribution(), observer.marginals())
                observer.observe(deepcopy(event))
                if before != (observer.distribution(), observer.marginals()):
                    raise ValueError(f"Duplicate evidence changed {variant} in {record['game_id']}")
        for variant in variants:
            if received[variant] != public:
                raise ValueError("An observer mutated or received a different replay stream")
            audits.append({"game_id": record["game_id"], "observer_id": pid, "variant": variant,
                           "observation_digest": digest(received[variant]), "observations": len(public),
                           "initial_view_digest": digest(view), "duplicate_delivery_check": "passed"})
    return traces, audits
