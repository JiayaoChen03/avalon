"""Build render-test states through the real engine, with a test-only model client."""
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_gui import GUITests
from test_engine import approve, finish_council
from avalon.llm import LLMError


def build():
    harness = GUITests()
    harness.setUp()
    fixtures = []

    def save(name, expected, form="", disabled=()):
        state = deepcopy(harness.session.snapshot())
        state["can_advance"] = False  # Render tests never schedule real model calls.
        fixtures.append({"name": name, "state": state, "form": form,
                         "expected": expected, "disabled": list(disabled)})

    game = harness.start()
    harness.session.gate = "ROLE_REVEAL"
    save("role", ["继续"])
    harness.request("continue")
    save("draft", ["确认队伍"], disabled=["确认队伍"])
    harness.draft()
    save("discussion", ["沉默  [0]", "落笔  [1]", "保留反应  [1]"])
    save("social", ["加强承诺 +1", "确认指控 P1  ·  共消耗 1 点决心", "取消"], "SOCIAL")
    save("challenge_form", ["确认  ·  消耗 1 点决心", "取消"], "CHALLENGE")
    save("cite", ["确认  ·  消耗 1 点决心", "取消"], "CITE")
    game.resolve["P1"] = 0
    save("zero_resolve", ["沉默  [0]"], disabled=["落笔  [1]", "质询  [1]", "引证  [1]", "保留反应  [1]"])
    game.resolve["P1"] = 3
    harness.action("HOLD")
    harness.request("advance")
    save("reaction", ["作出反应  [0 · 已预付]", "继续等待  [0]"])
    save("reaction_form", ["确认指控 P1  ·  共消耗 0 点决心", "取消"], "REACT")
    harness.to_revision()
    save("revision", ["确认队伍  [0]", "调整队伍  [1]"])
    save("revision_form", ["确认调整", "取消"], "REVISE")
    harness.action("LOCK")
    save("vote", ["赞成  [0]", "反对  [0]", "强烈赞成  [1]", "强烈反对  [1]"])
    balance = game.resolve["P1"]
    game.resolve["P1"] = 0
    save("vote_zero", ["赞成  [0]", "反对  [0]"], disabled=["强烈赞成  [1]", "强烈反对  [1]"])
    game.resolve["P1"] = balance
    harness.request("vote", {"approve": True})
    harness.finish_ballots()
    save("vote_result", ["继续"])
    harness.request("continue")
    save("good_mission", ["成功"])
    harness.request("mission", {"card": "SUCCESS"})
    harness.request("advance")
    save("round_result", ["进入任务后讨论"])
    harness.request("continue")
    save("council_discussion", ["沉默  [0]", "落笔  [1]"])
    while game.phase != "exile_nomination":
        if harness.session.snapshot()["can_advance"]:
            harness.request("advance")
        else:
            harness.action("PASS")
    save("exile_nomination", ["确认提名"], disabled=["确认提名"])
    harness.request("nominate_exile", {"target": "P2"})
    save("exile_vote", ["赞成", "反对", "弃票"])
    harness.request("exile_vote", {"choice": "APPROVE"})
    save("exile_waiting", [])
    harness.session.exile_ballots.update(P2="REJECT", P3="APPROVE", P4="APPROVE", P5="ABSTAIN")
    harness.session._finish_exile_vote()
    harness.session._flush()
    save("exile_result", ["下一轮 · 安全任务"])
    harness.request("continue")
    save("safe_round", [])
    approve(game, ["P1", "P2", "P3"])
    harness.session._flush()
    save("safe_mission", ["成功"])
    game.resolve_mission({"P1": "SUCCESS", "P2": "SUCCESS", "P3": "FAIL"})
    harness.session.result = next(e for e in reversed(game.events) if e["kind"] == "MISSION")
    harness.session.gate = "ROUND_RESULT"
    harness.session._flush()
    save("safe_failure", ["进入任务后讨论"])
    game = harness.start()
    harness.draft()
    seq = game.events[-1]["seq"]
    harness.action("PASS")
    game.act("P2", {"kind": "CHALLENGE", "target": "P1", "evidence": seq})
    harness.session._flush()
    save("challenged", ["回应  [1]", "拒绝回应  [0]"])
    save("response_form", ["确认指控 P1  ·  共消耗 1 点决心", "取消"], "RESPOND")
    game.resolve["P1"] = 0
    save("challenge_zero", ["拒绝回应  [0]"], disabled=["回应  [1]"])
    game.resolve["P1"] = 3
    harness.action("RESPOND", social={"card": "HEDGE", "target": "P2", "reason": "observe",
                                      "public_writing": "P2 阁下，名单已在卷上。我尚未许下别的誓约。", "citations": []})
    save("reply_link", [])
    game = harness.start("ASSASSIN")
    game.phase = "assassination"
    save("assassination", [])
    harness.request("assassinate", {"target": "P2"})
    save("game_over", ["再玩一局", "退出"])
    game = harness.start("EVIL")
    harness.draft(["P1", "P3"])
    harness.to_revision()
    harness.action("LOCK")
    harness.request("vote", {"approve": True})
    harness.finish_ballots()
    harness.request("continue")
    save("evil_mission", ["成功", "失败"])
    game = harness.start(count=6)
    save("six_player_draft", ["确认队伍"], disabled=["确认队伍"])
    harness.draft()
    harness.action("PASS")
    harness.client.error = LLMError("invalid_plan")
    harness.request("advance", ok=False)
    save("ai_error", ["重试 AI 行动"])
    harness.client.error = None
    game = harness.start()
    harness.draft()
    harness.action("PASS")
    game.act("P2", {"kind": "SOCIAL", "social": {
        "card": "HEDGE", "target": "P1", "reason": "observe", "evidence": [],
        "statement": "[b]这段标记应按原文显示[/b]。" + "我会结合公开落笔和投票记录再作判断。" * 10,
        "rationale": "这是未在手稿栏展示的理由摘要。",
    }})
    harness.session._flush()
    save("long_dialogue", [])
    original = game.events[-1]
    game.social("P3", {"card": "ACCUSE", "target": "P2", "reason": "observe",
                       "public_writing": "这份手稿需要重新核查。", "citations": [original["record_id"]]})
    harness.session._flush()
    save("chronicle_citation", [])
    game = harness.start(count=6)
    for proposal in range(3):
        game.propose(game.leader, ["P1", "P2"])
        for pid in game.speaking_order:
            game.social(pid, {"card": "HEDGE", "target": "P1", "reason": "observe",
                              "public_writing": f"第 {proposal + 1} 札，{pid} 留书：远征未定，旧卷中的凭据须先查明。",
                              "citations": []})
        game.act(game.leader, {"kind": "LOCK"})
        game.vote(dict.fromkeys(game.ids, False))
    harness.session._flush()
    save("history_review", ["回到最新"])
    history_fixture = fixtures[-1]
    approve(game, ["P1", "P2"])
    game.resolve_mission(dict.fromkeys(game.team, "SUCCESS"))
    finish_council(game)
    game.propose(game.leader, game.ids[:game.team_size])
    game.social(game.next_actor, {"card": "HEDGE", "target": "P1", "reason": "observe",
                                  "public_writing": "新札：上一程已毕，我仍将守望这份远征名单。", "citations": []})
    harness.session._flush()
    history_fixture["updated_state"] = deepcopy(harness.session.snapshot())
    history_fixture["updated_state"]["can_advance"] = False
    return fixtures


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps(build()), encoding="utf-8")
