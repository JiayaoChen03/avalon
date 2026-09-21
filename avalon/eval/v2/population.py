"""Frozen, reproducible policy families. complete() receives only policy_context.

Styles are sampled independently of role/seat; role capabilities come from the
legal view. The observer's q is intentionally unrelated to these policy values.
"""
from itertools import combinations
from copy import deepcopy
from avalon.engine import EVIL_ROLES
from avalon.eval.simulation import ControlledClient, keyed_uniform, canonical

PROFILES = {
    "transparent": {"transparent": True},
    "mixed": {"hedge": .30, "defend": .30, "early_pass": .35, "dissent": .18, "clean_support": .45, "revision": .10},
    "camouflage": {"hedge": .50, "defend": .28, "early_pass": .90, "dissent": .15, "clean_support": .80, "revision": .10},
    "negotiation": {"hedge": .25, "defend": .35, "early_pass": .50, "dissent": .43, "clean_support": .65, "revision": .35},
    # Held out as combinations, not claims of a wholly new action alphabet.
    "heldout_blend": {"hedge": .43, "defend": .30, "early_pass": .80, "dissent": .38, "clean_support": .82, "revision": .30},
    "heldout_patient": {"hedge": .60, "defend": .22, "early_pass": 1.0, "dissent": .48, "clean_support": .90, "revision": .40},
}


class PopulationClient(ControlledClient):
    def __init__(self, seed, profile, focal=None, all_controlled=False):
        super().__init__(seed)
        self.profile, self.parameters = profile, deepcopy(PROFILES[profile])
        self.focal, self.all_controlled = focal, all_controlled
        self.focal_client = ControlledClient(seed + 700000003)

    def style(self,pid):
        # A seed-specific style, never a fixed mapping from ID or alignment.
        return keyed_uniform(self.seed,"style",pid)

    def complete(self,context):
        v, b = context["view"], context["marginals"]
        pid,phase = v["self"],v["phase"]
        if self.all_controlled or pid == self.focal:
            self.calls += 1
            self.context_bytes += len(canonical(context).encode())
            return self.focal_client.complete(context)
        if self.parameters.get("transparent"):
            return super().complete(context)
        self.calls += 1
        self.context_bytes += len(canonical(context).encode())
        par = self.parameters
        coordinate = (pid,v["round"],v["attempt"],phase)
        u = lambda label: keyed_uniform(self.seed,"opponent",*coordinate,label)
        ids = [p["id"] for p in v["players"]]
        evil, known = v["role"] in EVIL_ROLES,set(v["known_evil"])
        style = self.style(pid)
        if phase=="team":
            teams = list(combinations(ids,v["team_size"]))
            camouflage = evil and v["round"]<=2 and u("clean_offer")<par["clean_support"]
            def utility(t):
                risk = context["team_risks"][",".join(t)]
                if evil and not camouflage:
                    risk = abs(len(set(t)&known)-1)
                # Public rejection history discourages repeating rejected teams.
                repeated = any(e["kind"]=="TEAM_VOTE" and not e["approved"] and set(e["team"])==set(t)
                               for e in v["recent_events"])
                return -risk-.35*repeated + .12*keyed_uniform(self.seed,*coordinate,"team",t)
            return {"team":list(max(teams,key=utility))}
        if phase=="vote":
            threshold = .62+.20*style+.035*(v["attempt"]-1)
            approve = context["team_risk"]<=threshold
            if evil:
                approve = bool(set(v["team"])&known) or u("clean_approve")<par["clean_support"]
            if u("dissent")<par["dissent"]/(v["attempt"]): approve=False
            return {"approve":approve or v["attempt"]==v["rules"]["max_proposals"],"strong":False}
        if phase=="mission":
            cards = next(o["cards"] for o in v["legal_options"] if o["kind"]=="MISSION")
            dirty = sorted(set(v["team"])&known)
            pass_chance = par["early_pass"] if v["round"]<=2 else .08+.12*style
            fail = ("FAIL" in cards and pid==dirty[0] and
                    (v["successes"]==2 or u("sabotage")>=pass_chance))
            return {"card":"FAIL" if fail else "SUCCESS"}
        if phase in {"discussion","council_discussion"}:
            if "SOCIAL" not in v["legal_actions"]: return {"kind":"PASS"}
            draw = u("card")
            # Every capable role overlaps on all three cards. Merlin's hidden
            # knowledge remains exact internally, regardless of public phrasing.
            card = "HEDGE" if draw<par["hedge"] else "DEFEND" if draw<par["hedge"]+par["defend"] else "ACCUSE"
            candidates = [p for p in ids if p!=pid]
            def target_score(p):
                risk = b[p]["evil"]
                if card=="DEFEND": risk=1-risk
                if card=="HEDGE": risk=1-abs(risk-.5)
                # A cautious speaker sometimes discusses an ambiguous target.
                return (.25 if style<.35 else 1)*risk+u("target:"+p)
            target=max(candidates,key=target_score)
            writing={"HEDGE":f"I reserve judgment about {target}.","DEFEND":f"I can support {target} on the visible evidence.",
                     "ACCUSE":f"I question {target}'s public choices."}[card]
            return {"kind":"SOCIAL","social":{"card":card,"target":target,"reason":"observe","public_writing":writing,"citations":[]}}
        if phase=="revision" and "REVISE" in v["legal_actions"] and u("revise")<par["revision"]:
            removed=max(v["team"],key=lambda p:b[p]["evil"]+u("remove:"+p)*.1)
            added=min([p for p in ids if p not in v["team"]],key=lambda p:b[p]["evil"]+u("add:"+p)*.1)
            return {"kind":"REVISE","removed":removed,"added":added}
        # Reuse the existing validated passive responses and argmax assassin.
        self.calls -= 1
        self.context_bytes -= len(canonical(context).encode())
        return super().complete(context)
