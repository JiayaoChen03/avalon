"""Versioned inference boundary: only a legal view and public events enter."""
from copy import deepcopy
from dataclasses import asdict
import math

from avalon.cognition import BeliefEngine
from avalon.evidence import LikelihoodConfig
from avalon.mission_likelihood import MissionLikelihoodConfig, MissionOutcomeLikelihood, public_outcome
from avalon.eval.frozen_v1.cognition import BeliefEngine as FrozenEngine
from avalon.eval.frozen_v1.legacy_beliefs import BaselineBeliefs, authorized_worlds
from avalon.eval.simulation import digest

VARIANTS = ("legacy_baseline", "joint_v1", "joint_hard_only", "joint_v2",
            "joint_v2_no_success_soft", "joint_v2_no_social_soft")


def configuration(variant):
    return LikelihoodConfig(mission=MissionLikelihoodConfig(enabled=variant in {
        "joint_v2", "joint_v2_no_success_soft", "joint_v2_no_social_soft"},
        success_enabled=variant != "joint_v2_no_success_soft", q=.5, gamma=.5),
        behavioral_enabled=variant != "joint_hard_only",
        social_enabled=variant != "joint_v2_no_social_soft", language_enabled=variant != "joint_hard_only")


def posterior_hash(distribution):
    return digest([[list(w), round(p, 15)] for w, p in sorted(distribution.items())])


class VersionedBeliefs:
    representation = "native_joint"

    def __init__(self, variant, view):
        if variant not in VARIANTS:
            raise ValueError(variant)
        self.variant = variant
        self.pid, self.role = view["self"], view["role"]
        self.ids = tuple(p["id"] for p in view["players"])
        self.knowledge, self.rules = deepcopy(view["private_knowledge"]), deepcopy(view["rules"])
        self.universe = authorized_worlds(view)
        self.config = configuration(variant)
        self.legacy = BaselineBeliefs(deepcopy(view)) if variant == "legacy_baseline" else None
        self.engine = None if self.legacy else (FrozenEngine(deepcopy(view)) if variant == "joint_v1"
                    else BeliefEngine(deepcopy(view), likelihood_config=self.config))
        if self.legacy:
            self.representation = self.legacy.representation
        self.last_audit = None
        self.last_factors = []
        self.delivered = set()

    def marginals(self):
        return self.legacy.marginals() if self.legacy else self.engine.marginals()

    def distribution(self):
        return self.legacy.distribution() if self.legacy else {h.key: h.probability for h in self.engine.beliefs.hypotheses}

    def role_marginals(self):
        distribution = self.distribution()
        return {pid: {r: math.fsum(p for w, p in distribution.items() if dict(w)[pid] == r)
                      for r in self.rules["role_counts"]} for pid in self.ids}

    def team_risk(self, team):
        if self.legacy:
            return self.legacy.team_risk(team)
        return 1 - self.engine.P_joint({p: {"alignment": "GOOD"} for p in team})

    def team_query(self, team, rules=None):
        if self.legacy:
            raise ValueError("Scoring projection must never drive the legacy policy")
        counts = {k: math.fsum(p for w, p in self.distribution().items()
                    if sum(self.rules["role_alignments"][dict(w)[a]] == "EVIL" for a in team) == k)
                  for k in range(len(team) + 1)}
        model = MissionOutcomeLikelihood(MissionLikelihoodConfig(enabled=True))
        return {"clean_probability": counts[0], "evil_count_probabilities": counts,
                "expected_evil_count": math.fsum(k*p for k,p in counts.items()),
                "mission_failure_probability": math.fsum(p*model.team_failure_probability(k,rules or self.rules,team)
                                                         for k,p in counts.items())}

    def observe(self, event):
        mission = event["kind"] == "MISSION"
        before = self.distribution() if mission else None
        marg = self.marginals() if mission else None
        roles = self.role_marginals() if mission else None
        seen = event["seq"] in self.delivered
        signals = set(self.engine._applied_signals) if self.engine else set()
        if self.legacy:
            changed = self.legacy.observe(deepcopy(event))
            self.last_factors = []
        else:
            old_record = self.engine.beliefs.update_records[-1]
            self.engine.observe(deepcopy(event))
            new_record = self.engine.beliefs.update_records[-1]
            changed = new_record is not old_record
            self.last_factors = [asdict(e) for e in new_record.evidence] if changed else []
        self.delivered.add(event["seq"])
        self.last_audit = None
        if mission:
            outcome = public_outcome(event, self.rules)
            after = self.distribution()
            tv = .5 * math.fsum(abs(after.get(w,0)-before.get(w,0)) for w in set(before)|set(after))
            new_marg, new_roles = self.marginals(), self.role_marginals()
            align_delta = max(abs(new_marg[p]["evil"]-marg[p]["evil"]) for p in self.ids)
            role_delta = max(abs(new_roles[p][r]-roles[p][r]) for p in self.ids for r in self.rules["role_counts"])
            factor_id = f"mission_outcome:{event['round']}:{event.get('attempt',1)}"
            applied = bool(self.engine and factor_id in self.engine._applied_signals - signals)
            skip = ("duplicate_event_or_factor" if seen or factor_id in signals else
                    "legacy_independent_update" if self.legacy else
                    "no_mission_soft_factor_v1" if self.variant == "joint_v1" else
                    MissionOutcomeLikelihood(self.config.mission).skip_reason(outcome))
            if applied and tv < 1e-12:
                skip = "belief_already_certain" if len(after) == 1 else "equal_likelihood_on_surviving_support"
            self.last_audit = {"observer_id": self.pid,"event_id":event.get("record_id",str(event["seq"])),
                "origin_event_id":event.get("record_id",str(event["seq"])),"factor_id":factor_id,
                "variant":self.variant,"likelihood_version":MissionOutcomeLikelihood.version if applied else self.variant,
                "evidence_kind":"mission_result", "outcome_observation_type":outcome["outcome_observation_type"],
                "fail_threshold":outcome["fail_threshold"],"q":self.config.mission.q,"gamma":self.config.mission.gamma,
                "success":outcome["success"],"fail_count":outcome["fail_count"],
                "support_before":sum(p>0 for p in before.values()),"support_after":sum(p>0 for p in after.values()),"posterior_tv":tv,
                "posterior_hash_before":posterior_hash(before),"posterior_hash_after":posterior_hash(after),
                "posterior_changed":int(tv>1e-12),"alignment_marginal_delta":align_delta,
                "role_marginal_delta":role_delta,"max_marginal_delta":max(align_delta,role_delta),
                "applied":int(applied),"skip_reason":skip or "applied_informative",
                "duplicate_delivery":int(seen)}
        return changed

    def snapshot(self):
        if self.legacy:
            dist = self.distribution()
            worlds = [{"world_id":digest(w),"roles":dict(w),"probability":p,
                       "log_probability":math.log(p) if p else None} for w,p in sorted(dist.items())]
            eliminated = []
        else:
            worlds = [{"world_id":digest(h.key),"roles":dict(h.roles),"probability":h.probability,
                       "log_probability":h.log_probability} for h in self.engine.beliefs.hypotheses]
            eliminated = [dict(w) for w in sorted(self.engine.beliefs.eliminated_keys)]
        return {"probability_source":self.representation,"worlds":worlds,
                "hard_eliminated_worlds":eliminated,"factors":deepcopy(self.last_factors),
                "raw_marginals":self.marginals(),"posterior_hash":posterior_hash(self.distribution())}


def make_version(variant, view, likelihood=None):
    return VersionedBeliefs("joint_v1" if variant in {"baseline","reference"} else variant, view)
