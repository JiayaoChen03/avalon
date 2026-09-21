"""Bounded subjective memory. No model output can rewrite an archived event."""

from collections import deque
from copy import deepcopy
import re

from .chronicle import EVIDENCE_KINDS, context_record, record_id


WORKING_LIMIT = 8
LIFE_LIMIT = 3
SCAR_LIMIT = 5
COMMITMENT_LIMIT = 5


def clamp(value):
    return round(max(-1.0, min(1.0, value)), 4)


class AgentMemory:
    """Host-maintained recollections alongside the agent's existing beliefs/profiles.

    Reflection is deterministic and extractive: no extra paid call or invented
    causal story. Public nominations are associations, never proof of sabotage.
    """
    def __init__(self, pid, ids):
        self.pid = pid
        self.life = 1
        self.alive = True
        self.working = deque(maxlen=WORKING_LIMIT)
        self.relationships = {other: {"trust": 0.0, "confidence": 0.0, "reasons": []}
                              for other in ids if other != pid}
        self.lives = deque(maxlen=LIFE_LIMIT)
        self.older_lives = {"count": 0, "landmarks": []}
        self.scars = []
        self.commitments = []
        self.unresolved = []

    def _relationship(self, other, delta, event):
        if other not in self.relationships:
            return
        rel = self.relationships[other]
        rel["trust"] = clamp(rel["trust"] + delta)
        rel["confidence"] = min(0.95, round(rel["confidence"] + 0.04, 4))
        rid = record_id(event)
        rel["reasons"] = [r for r in rel["reasons"] if r != rid][-2:] + [rid]

    def _scar(self, kind, source, event, strength):
        if source not in self.relationships:
            return
        for scar in self.scars:
            if scar["type"] == kind and scar["source_character"] == source:
                scar.update(strength=min(1.0, scar["strength"] + strength / 3), origin_record=record_id(event))
                break
        else:
            self.scars.append({"type": kind, "source_character": source,
                               "strength": strength, "origin_record": record_id(event)})
        self.scars.sort(key=lambda s: s["strength"], reverse=True)
        del self.scars[SCAR_LIMIT:]

    def observe(self, event, beliefs):
        kind, actor, target = event["kind"], event.get("actor"), event.get("target")
        if kind in EVIDENCE_KINDS:
            self.working.append(context_record(event))
        if kind in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"} and "card" in event:
            card = event["card"]
            if target == self.pid and actor != self.pid:
                delta = {"ACCUSE": -0.12, "DEFEND": 0.12, "PRESSURE": -0.04}.get(card, 0)
                if delta:
                    self._relationship(actor, delta, event)
                if card == "DEFEND":
                    self._scar("defended_by", actor, event, 0.4)
                elif card == "ACCUSE":
                    self._scar("accused_by", actor, event, 0.45)
            if card == "ACCUSE" and self.pid in (actor, target):
                self.unresolved = [r for r in self.unresolved if (r["actor"], r["target"]) != (actor, target)]
                self.unresolved.append({"actor": actor, "target": target, "record_id": record_id(event),
                                        "seq": event["seq"], "round": event["round"]})
                self.unresolved = self.unresolved[-COMMITMENT_LIMIT:]
            writing = event.get("public_writing", event.get("statement", ""))
            promise = bool(re.search(r"承诺|答应|发誓|\b(?:promise|pledge|oath)\b", writing, re.IGNORECASE))
            if (event.get("committed") or promise) and actor == self.pid:
                self.commitments.append({"card": card, "target": target, "record_id": record_id(event),
                                         "writing": writing[:180]})
                self.commitments = self.commitments[-COMMITMENT_LIMIT:]
        elif kind == "MISSION":
            for other in event["team"]:
                self._relationship(other, 0.10 if event["success"] else -0.08, event)
                if event["success"]:
                    # New evidence can weaken an old suspicion; scars are not fixed grudges.
                    for scar in self.scars:
                        if scar["source_character"] == other and scar["type"] not in {"defended_by", "opposed_my_exile"}:
                            scar["strength"] = round(scar["strength"] * 0.8, 4)
        elif kind == "EXILE_NOMINATION" and target == self.pid:
            self._relationship(actor, -0.08, event)
            self._scar("nominated_for_exile", actor, event, 0.45)
        elif kind == "EXILE_VOTE" and target == self.pid:
            if event["choice"] == "APPROVE":
                self._relationship(actor, -0.12, event)
                self._scar("voted_to_exile", actor, event, 0.6)
            elif event["choice"] == "REJECT":
                self._relationship(actor, 0.10, event)
                self._scar("opposed_my_exile", actor, event, 0.4)
        elif kind == "DEATH" and target == self.pid:
            self.alive = False
            for recent in self.unresolved:
                if recent.get("target") == self.pid:
                    self._scar("accused_before_death", recent.get("actor"), recent, 0.7)
            nominator = event.get("nominated_by")
            if nominator and nominator != self.pid:
                self._relationship(nominator, -0.08, event)
                self._scar("death_association", nominator, event, 0.55)
            source = event.get("actor")
            if source:
                self._relationship(source, -0.15, event)
                self._scar("killed_by", source, event, 0.85)
            self.reflect(event, beliefs)
            self.working.clear()
        elif kind == "REBIRTH" and target == self.pid:
            self.life = event["life"]
            self.alive = True
            self.working.clear()
            self.working.append(context_record(event))
        elif kind == "ROUND":
            self.consolidate()

    def reflect(self, death, beliefs):
        refs = [record_id(death), *death.get("related_records", [])]
        refs += [s["origin_record"] for s in self.scars[:3]]
        refs = list(dict.fromkeys(refs))[:6]
        relations = sorted(self.relationships.items(), key=lambda pair: abs(pair[1]["trust"]), reverse=True)[:3]
        recollections = [f"{pid}: trust {r['trust']:+.2f}" for pid, r in relations]
        # Bound every component, including prior-life aggregates; no transcript concatenation.
        summary = (f"Life {self.life} ended in round {death['round']}: {death['cause']}. "
                   "The cause is public; responsibility is uncertain unless a killer was recorded. "
                   + "; ".join(recollections)
                   + ". Significant memories: " + "; ".join(f"{s['source_character']} {s['type']} ({s['origin_record']})"
                                                            for s in self.scars[:3])
                   + ". Earlier accusations remain claims, not established identities. "
                   "My recorded commitments and unresolved accusations survive. I may reconsider with new evidence.")[:850]
        life = {"life": self.life, "death_record": record_id(death), "summary": summary,
                "important_records": refs,
                "final_beliefs": {pid: deepcopy(beliefs[pid]) for pid, _ in relations},
                "commitments": deepcopy(self.commitments[-2:]),
                "unresolved": deepcopy(self.unresolved[-2:])}
        if len(self.lives) == LIFE_LIMIT:
            old = self.lives[0]
            self.older_lives["count"] += 1
            landmarks = self.older_lives["landmarks"] + old["important_records"][:2]
            self.older_lives["landmarks"] = list(dict.fromkeys(landmarks))[-5:]
        self.lives.append(life)
        self.consolidate()

    def consolidate(self):
        self.scars = [dict(s, strength=round(s["strength"] * 0.97, 4)) for s in self.scars
                      if s["strength"] >= 0.1]
        self.scars.sort(key=lambda s: s["strength"], reverse=True)
        self.scars = self.scars[:SCAR_LIMIT]

    def retrieval_hints(self, target=None):
        refs = [s["origin_record"] for s in self.scars
                if target is None or s["source_character"] == target]
        if self.lives:
            refs += self.lives[-1]["important_records"][:3]
        refs += [r["record_id"] for r in self.unresolved[-2:]]
        return list(dict.fromkeys(refs))[:8]

    def snapshot(self):
        return deepcopy({"life": self.life, "alive": self.alive,
                         "working_memory": list(self.working), "relationships": self.relationships,
                         "life_memories": list(self.lives), "older_lives": self.older_lives,
                         "memory_scars": self.scars, "commitments": self.commitments,
                         "unresolved_accusations": self.unresolved})


def bounded_game_view(view):
    """Apply limits at the final prompt boundary, even for custom controllers."""
    fields = {"self", "role", "known_evil", "round", "attempt", "leader", "team_size", "team",
              "speaking_direction", "speaking_order", "phase", "successes", "failures", "safe_round",
              "discussion_stage", "exile_nominee", "exile_candidates", "exile_choices", "required_approvals",
              "lives", "resolve", "max_resolve", "resolve_costs", "next_actor", "legal_actions",
              "pending_reactions", "reaction_queue", "reaction_trigger", "challenge", "discussion_status"}
    game = deepcopy({k: v for k, v in view.items() if k in fields})
    game["players"] = [{"id": p["id"], "name": p["name"]} for p in view["players"]]
    for key, limit in (("recent_events", WORKING_LIMIT), ("focused_events", 5)):
        game[key] = [context_record(e) for e in view.get(key, [])
                     if e["kind"] in EVIDENCE_KINDS][-limit:]
    mission_fields = {"round", "attempt", "record_id", "team", "success", "fail_count", "fail_threshold",
                      "successes", "failures", "safe_round"}
    game["missions"] = [{k: deepcopy(v) for k, v in m.items() if k in mission_fields}
                        for m in view.get("missions", [])[-5:]]
    return game
