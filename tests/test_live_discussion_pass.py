"""A public PASS must leave the next AI discussion turn actionable."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from avalon.engine import Player
from avalon.gui import GameSession
from test_agents import valid_plan


class ModernPassClient:
    def __init__(self):
        self.contexts = []

    def complete(self, context):
        self.contexts.append(deepcopy(context))
        if "tactical" in context:
            action = {"social": None, "discussion": {"kind": "PASS"},
                      "revision": {"kind": "LOCK"}, "strong_vote": False}
        else:
            action = valid_plan(context["game"])
            action.pop("beliefs")
            action.pop("profiles")
            ids = [p["id"] for p in context["game"]["players"]]
            action.update(team_rank=["P5", "P3"] + [p for p in ids if p not in {"P5", "P3"}],
                          mission="SUCCESS", social=None, discussion={"kind": "PASS"},
                          revision={"kind": "LOCK"}, strong_vote=False)
        return {"belief_updates": [], "interpretation": [],
                "public_stance_change": None, "recommended_action": action,
                "short_rationale": "当前公开证据有限，先保留判断。"}


class LiveDiscussionPassTests(unittest.TestCase):
    def test_p5_pass_then_p4_action_with_modern_envelope_for_all_roles(self):
        role_sets = {
            "GOOD": ["MERLIN", "ASSASSIN", "EVIL", "GOOD", "GOOD", "GOOD"],
            "MERLIN": ["GOOD", "ASSASSIN", "EVIL", "MERLIN", "GOOD", "GOOD"],
            "ASSASSIN": ["MERLIN", "GOOD", "EVIL", "ASSASSIN", "GOOD", "GOOD"],
            "EVIL": ["MERLIN", "ASSASSIN", "GOOD", "EVIL", "GOOD", "GOOD"],
        }
        for role, roles in role_sets.items():
            with self.subTest(p4_role=role):
                client = ModernPassClient()
                session = GameSession(lambda: client, merlin_vote_policy="v5")
                players = [Player(f"P{i+1}", f"Seat{i+1}", seat_role)
                           for i, seat_role in enumerate(roles)]
                with patch("avalon.gui.make_players", return_value=players):
                    session.start(6, 34)

                def command(name):
                    return session.dispatch({"request_id": f"{name}-{session.revision}",
                                             "revision": session.revision,
                                             "command": name, "payload": {}})

                self.assertEqual(session.game.leader, "P5")
                self.assertEqual(session.game.speaking_order[:2], ["P5", "P4"])
                self.assertTrue(command("continue")["ok"])
                self.assertTrue(command("advance")["ok"])
                self.assertEqual(session.game.team, ["P5", "P3"])
                self.assertEqual(session.game.phase, "discussion")
                self.assertTrue(command("advance")["ok"])
                self.assertEqual((session.game.events[-1]["kind"], session.game.events[-1]["actor"]),
                                 ("PASS", "P5"))
                self.assertEqual(session.game.next_actor, "P4")
                self.assertIn("PASS", session.game.view("P4")["legal_actions"])
                public_prefix = deepcopy(session.game.events)
                revision = session.revision

                result = command("advance")
                self.assertTrue(result["ok"], result["error"])
                self.assertEqual(session.revision, revision + 1)
                self.assertEqual(session.game.events[:len(public_prefix)], public_prefix)
                self.assertEqual((session.game.events[-1]["kind"], session.game.events[-1]["actor"]),
                                 ("PASS", "P4"))
                context = client.contexts[-1]
                self.assertEqual(context["game"]["phase"], "discussion")
                self.assertEqual(context["game"]["next_actor"], "P4")
                self.assertEqual(context["game"]["recent_events"][-1]["kind"], "PASS")
                self.assertEqual(context["game"]["recent_events"][-1]["actor"], "P5")
                self.assertIn("PASS", context["game"]["legal_actions"])


if __name__ == "__main__":
    unittest.main()
