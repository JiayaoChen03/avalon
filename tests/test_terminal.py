import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from avalon.agents import Agent
from avalon.engine import Game, make_players
from avalon.terminal import Human, QuitGame, run_game
from test_engine import fixed_game


class TerminalTests(unittest.TestCase):
    def test_human_reprompts_for_invalid_inputs_and_handles_quit(self):
        output = []
        answers = iter(["P1 P1", "P1 P9", "1,2", "blah", "BAIT P2", "maybe", "n"])
        human = Human(fixed_game().view("P1"), input_fn=lambda _: next(answers), write=output.append)
        self.assertEqual(human.choose_team(2), ["P1", "P2"])
        self.assertEqual(human.social_action(), {"card": "BAIT", "target": "P2", "reason": "human_choice"})
        self.assertFalse(human.vote(["P1", "P2"], 1))
        self.assertGreaterEqual(len(output), 4)
        human.input_fn = lambda _: "q"
        with self.assertRaises(QuitGame):
            human.vote(["P1", "P2"], 1)

    def test_scripted_human_plays_a_complete_game(self):
        game = fixed_game()
        human = Human(game.view("P1"), input_fn=lambda _: "", write=lambda _: None)
        agents = {pid: Agent(game.view(pid)) for pid in game.ids if pid != "P1"}
        output, log = [], io.StringIO()
        run_game(game, agents, human=human, write=output.append, log=log, dossier=True)
        self.assertIn(game.winner, {"GOOD", "EVIL"})
        text = "\n".join(output)
        for name in ("TEAM", "SOCIAL", "VOTE", "MISSION", "RESULT", "DOSSIER"):
            self.assertIn(f"[{name}]", text)
        events = [json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual(events, game.events)
        self.assertTrue(any(e["kind"] == "SOCIAL" and e["actor"] == "P1" for e in events))
        self.assertTrue(all(agent.calls == {} for agent in agents.values()))
        self.assertNotIn("beliefs", log.getvalue())
        self.assertNotIn("PRIVATE", log.getvalue())
        for event in events:
            if event["kind"] == "TEAM_VOTE":
                same_proposal = [e for e in events if e["round"] == event["round"]
                                 and e["attempt"] == event["attempt"]]
                self.assertEqual(sum(e["kind"] == "SOCIAL" for e in same_proposal), 5)
                self.assertEqual(sum(e["kind"] == "VOTE" for e in same_proposal), 5)

    def test_demo_many_seeds_always_terminates_and_is_reproducible(self):
        for count in (5, 6):
            for seed in range(20):
                game = Game(make_players(count, seed), seed=seed)
                agents = {p: Agent(game.view(p)) for p in game.ids}
                run_game(game, agents, write=lambda _: None)
                self.assertIn(game.winner, {"GOOD", "EVIL"})
                self.assertLessEqual(len(game.missions), 5)
                self.assertEqual(game.events[-1]["kind"], "REVEAL")
        logs = []
        for _ in range(2):
            game = Game(make_players(6, 7), seed=7)
            log = io.StringIO()
            run_game(game, {p: Agent(game.view(p)) for p in game.ids}, write=lambda _: None, log=log)
            logs.append(log.getvalue())
        self.assertEqual(*logs)

    def test_cli_demo_and_eof_are_real_entrypoint_runs(self):
        cwd = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "demo.jsonl"
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--mock",
                                     "--demo", "--players", "6", "--seed", "7", "--log", str(log)],
                                    cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("[RESULT]", result.stdout)
            self.assertIn("[LYRA/P6]", result.stdout)
            self.assertLess(result.stdout.index("[LEADER]"), result.stdout.index("[ROUND 1/5]"))
            self.assertIn("[LEADER] [YOU/P1]", result.stdout)
            self.assertIn("演示", result.stdout)
            self.assertTrue(log.is_file())
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--mock"],
                                cwd=cwd, input="", capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[EXIT]", result.stdout)
        self.assertNotIn("[RESULT]", result.stdout)


if __name__ == "__main__":
    unittest.main()
