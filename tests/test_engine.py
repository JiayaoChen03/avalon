import json
import unittest

from avalon.engine import CARDS, Game, Player, make_players


def fixed_game(count=5):
    roles = ["GOOD", "MERLIN", "ASSASSIN", "EVIL", "GOOD"]
    if count == 6:
        roles.append("GOOD")
    return Game([Player(f"P{i+1}", f"Player {i+1}", role)
                 for i, role in enumerate(roles)], seed=0, direction="clockwise")


def discuss(game):
    for pid in game.speaking_order:
        if game.resolve[pid]:
            game.social(pid, {"card": "HEDGE", "target": "P1", "reason": "observe"})
        else:
            game.act(pid, {"kind": "PASS"})
    game.act(game.leader, {"kind": "LOCK"})


def approve(game, team):
    game.propose(game.leader, team)
    discuss(game)
    game.vote({pid: True for pid in game.ids})


class RuleTests(unittest.TestCase):
    def test_opening_leader_does_not_reveal_last_seat_role(self):
        for count in (5, 6):
            last_roles_by_leader = {f"P{i+1}": set() for i in range(count)}
            for seed in range(200):
                players = make_players(count, seed)
                game = Game(players, seed=seed)
                last_roles_by_leader[game.leader].add(players[-1].role)
            for leader, roles in last_roles_by_leader.items():
                self.assertEqual(roles, {"MERLIN", "ASSASSIN", "EVIL", "GOOD"},
                                 f"Opening leader {leader} exposes the last seat in a {count}-player game")

    def test_opening_leader_is_seeded_and_can_be_any_seat(self):
        for count in (5, 6):
            players = make_players(count, 12)
            leaders = {Game(players, seed=seed).leader for seed in range(40)}
            self.assertEqual(leaders, {p.id for p in players})
            self.assertEqual(Game(players, seed=7).leader, "P1")
            self.assertEqual(Game(players, seed=7).events, Game(players, seed=7).events)

    def test_opening_draw_precedes_round_and_later_leaders_rotate(self):
        game = Game(make_players(5, 12), seed=7)
        self.assertEqual([e["kind"] for e in game.events], ["START", "LEADER", "DIRECTION", "ROUND", "RESOLVE_REFRESH"])
        self.assertEqual(game.events[1]["actor"], "P1")
        self.assertEqual(game.events[3]["leader"], "P1")
        game.propose("P1", ["P1", "P2"])
        discuss(game)
        game.vote({p: False for p in game.ids})
        self.assertEqual(game.leader, "P2")
        approve(game, ["P1", "P2"])
        game.resolve_mission({"P1": "SUCCESS", "P2": "SUCCESS"})
        self.assertEqual(game.leader, "P3")
        self.assertEqual(sum(e["kind"] == "LEADER" for e in game.events), 1)
        self.assertNotIn("seed", json.dumps(game.events))

    def test_role_counts_and_seed(self):
        for n in (5, 6):
            players = make_players(n, 12)
            self.assertEqual(players, make_players(n, 12))
            self.assertEqual(sum(p.role in ("EVIL", "ASSASSIN") for p in players), 2)
            self.assertEqual(sum(p.role == "MERLIN" for p in players), 1)
            self.assertEqual(sum(p.role == "ASSASSIN" for p in players), 1)
        with self.assertRaises(ValueError):
            make_players(7)

    def test_team_sizes(self):
        for count, sizes in ((5, [2, 3, 2, 3, 3]), (6, [2, 3, 4, 3, 4])):
            game = fixed_game(count)
            for size, success in zip(sizes, (True, False, True, False, True)):
                self.assertEqual(game.team_size, size)
                team = ["P3"] + [p for p in game.ids if p != "P3"][:size-1]
                approve(game, team)
                game.resolve_mission({p: "FAIL" if p == "P3" and not success else "SUCCESS"
                                      for p in team})
            self.assertEqual(game.phase, "assassination")

    def test_invalid_teams_are_rejected_without_events(self):
        game = fixed_game()
        before = len(game.events)
        for actor, team in (("P2", ["P1", "P2"]), ("P1", ["P1", "P1"]),
                            ("P1", ["P1"]), ("P1", ["P1", "P9"])):
            with self.assertRaises(ValueError):
                game.propose(actor, team)
        self.assertEqual(len(game.events), before)

    def test_votes_require_every_player_and_are_strict_booleans(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        discuss(game)
        for votes in ({"P1": True}, {p: "approve" for p in game.ids}):
            with self.assertRaises(ValueError):
                game.vote(votes)
        self.assertEqual(game.phase, "vote")

    def test_tie_rejects_and_leader_rotates(self):
        game = fixed_game(6)
        game.propose("P1", ["P1", "P2"])
        discuss(game)
        game.vote({p: p in ["P1", "P2", "P3"] for p in game.ids})
        self.assertEqual((game.phase, game.leader, game.attempt, game.round),
                         ("team", "P2", 2, 1))

    def test_five_rejections_end_game(self):
        game = fixed_game()
        for _ in range(5):
            game.propose(game.leader, ["P1", "P2"])
            discuss(game)
            game.vote({p: False for p in game.ids})
        self.assertEqual(game.winner, "EVIL")
        self.assertEqual(game.events[-2]["reason"], "five_rejections")
        self.assertFalse(any(e["kind"] == "MISSION" for e in game.events))
        with self.assertRaises(ValueError):
            game.propose(game.leader, ["P1", "P2"])

    def test_one_fail_suffices_and_good_cannot_sabotage(self):
        game = fixed_game()
        approve(game, ["P1", "P3"])
        before = len(game.events)
        with self.assertRaises(ValueError):
            game.resolve_mission({"P1": "FAIL", "P3": "SUCCESS"})
        self.assertEqual(len(game.events), before)
        with self.assertRaises(ValueError):
            game.resolve_mission({"P1": "SUCCESS"})
        game.resolve_mission({"P1": "SUCCESS", "P3": "FAIL"})
        self.assertEqual((game.failures, game.round, game.attempt, game.leader), (1, 2, 1, "P2"))
        mission = next(e for e in game.events if e["kind"] == "MISSION")
        self.assertEqual(mission["fail_count"], 1)
        self.assertNotIn("cards", mission)

    def test_three_failed_missions_win_without_assassination(self):
        game = fixed_game()
        for _ in range(3):
            team = ["P3"] + [p for p in game.ids if p != "P3"][:game.team_size-1]
            approve(game, team)
            game.resolve_mission({p: "FAIL" if p == "P3" else "SUCCESS" for p in team})
        self.assertEqual(game.winner, "EVIL")
        self.assertEqual(game.events[-2]["reason"], "three_failed_missions")

    def test_assassin_can_reverse_good_victory(self):
        for target, winner in (("P2", "EVIL"), ("P1", "GOOD")):
            game = fixed_game()
            for _ in range(3):
                team = ["P1", "P2", "P5"][:game.team_size]
                approve(game, team)
                game.resolve_mission({p: "SUCCESS" for p in team})
            self.assertIsNone(game.winner)
            self.assertFalse(any(e["kind"] == "REVEAL" for e in game.events))
            with self.assertRaises(ValueError):
                game.assassinate("P4", target)
            with self.assertRaises(ValueError):
                game.assassinate("P3", "P4")
            game.assassinate("P3", target)
            self.assertEqual(game.winner, winner)

    def test_social_cards_are_validated_and_once_per_proposal(self):
        self.assertEqual(set(CARDS), {"ACCUSE", "DEFEND", "HEDGE", "PRESSURE", "BAIT"})
        game = fixed_game()
        with self.assertRaises(ValueError):
            game.social("P1", {"card": "BAIT", "target": "P2", "reason": "observe"})
        game.propose("P1", ["P1", "P2"])
        for action in ({"card": "OTHER", "target": "P2", "reason": "observe"},
                       {"card": "BAIT", "target": "P99", "reason": "observe"},
                       {"card": "BAIT", "target": "P2", "reason": "secret reasoning"}):
            with self.assertRaises(ValueError):
                game.social("P1", action)
        game.social("P1", {"card": "BAIT", "target": "P2", "reason": "observe"})
        with self.assertRaises(ValueError):
            game.social("P1", {"card": "BAIT", "target": "P2", "reason": "observe"})

    def test_view_has_only_role_appropriate_secrets_and_copies(self):
        game = fixed_game()
        self.assertEqual(game.view("P1")["known_evil"], [])
        self.assertEqual(game.view("P2")["known_evil"], ["P3", "P4"])
        self.assertEqual(game.view("P3")["known_evil"], ["P3", "P4"])
        self.assertEqual(game.view("P1")["role"], "GOOD")
        for p in game.view("P1")["players"]:
            self.assertEqual(set(p), {"id", "name"})
        view = game.view("P1")
        view["recent_events"][0]["players"][0]["name"] = "MUTATED"
        self.assertNotIn("MUTATED", json.dumps(game.events))
        self.assertNotIn("role", json.dumps(game.events))
        self.assertNotIn("seed", json.dumps(game.view("P1")))

    def test_discussion_enforces_leader_first_and_clockwise_turns(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        action = {"card": "HEDGE", "target": "P1", "reason": "observe"}
        before = len(game.events)
        with self.assertRaises(ValueError):
            game.social("P2", action)
        self.assertEqual(len(game.events), before)
        discuss(game)
        game.vote({p: False for p in game.ids})
        game.propose("P2", ["P2", "P3"])
        with self.assertRaises(ValueError):
            game.social("P1", action)
        discuss(game)
        self.assertEqual([e["actor"] for e in game.events if e["kind"] == "SOCIAL"][-5:],
                         ["P2", "P3", "P4", "P5", "P1"])

    def test_public_speech_is_logged_and_visible_to_the_next_speaker(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        action = {"card": "HEDGE", "target": "P2", "reason": "observe",
                  "statement": "我希望先听听 P2 的选队依据。", "rationale": "首轮还没有任务记录。",
                  "evidence": []}
        game.social("P1", action)
        self.assertEqual(game.view("P2")["recent_events"][-1], game.events[-1])
        self.assertEqual(game.events[-1]["statement"], action["statement"])
        for field, value in (("reasoning_content", "PRIVATE"), ("statement", "\x1b[2J")):
            bad = {**action, field: value}
            with self.assertRaises(ValueError):
                game.social("P2", bad)


if __name__ == "__main__":
    unittest.main()
