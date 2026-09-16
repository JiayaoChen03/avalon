from copy import deepcopy
import unittest

from avalon.agents import validate_performance
from avalon.llm import LLMError


class PerformanceValidationTests(unittest.TestCase):
    def setUp(self):
        self.ids = ["P1", "P2", "P3", "P4", "P5"]
        self.tactic = {"primary_target": "P4", "allowed_cards": ["HEDGE"],
                       "strategy_mode": "FAKE_CONFLICT"}
        self.response = {"social": {"card": "HEDGE", "target": "P4", "reason": "observe",
                                    "statement": "我对 P4 的选队理由还保留判断。",
                                    "rationale": "现在公开证据不足，需要继续验证。", "evidence": []}}

    def test_private_keys_and_explicit_self_disclosures_are_rejected(self):
        for disclosure in ("evil_partner=P4", "likely_merlin=P2", "active_narratives=[]",
                           "aggressor_agent_id=P3", "我和 P4 都是坏人。", "我负责进攻，P4 负责潜伏。",
                           "mission_fail_owner=P4", "FAKE_CONFLICT", "我是刺客。"):
            for field in ("statement", "rationale"):
                with self.subTest(disclosure=disclosure, field=field):
                    response = deepcopy(self.response)
                    response["social"][field] = disclosure
                    with self.assertRaisesRegex(LLMError, "private_disclosure"):
                        validate_performance(response, self.ids, [], self.tactic)

    def test_public_distrust_of_partner_remains_model_written(self):
        result = validate_performance(self.response, self.ids, [], self.tactic)
        self.assertEqual(result["social"], self.response["social"])
        self.response["social"]["statement"] = "changed"
        self.assertEqual(result["social"]["statement"], "我对 P4 的选队理由还保留判断。")

    def test_new_objective_names_are_private_without_a_static_blocklist_update(self):
        tactic = {**self.tactic, "primary_objective": "OBSERVE_MERLIN_REACTION", "role": "Sleeper"}
        response = deepcopy(self.response)
        response["social"]["statement"] = "My assigned objective is OBSERVE_MERLIN_REACTION."
        with self.assertRaisesRegex(LLMError, "private_disclosure"):
            validate_performance(response, self.ids, [], tactic)

    def test_all_private_tactical_labels_and_readable_variants_are_rejected(self):
        tactic = {**self.tactic, "role": "Sleeper", "primary_objective": "PROBE_MERLIN",
                  "secondary_objective": "BUILD_TRUST", "agenda_topic": "MISSION_ACCOUNTABILITY",
                  "constraints": ["PUBLIC_EVIDENCE_ONLY", "NO_ADJACENT_PARTNER_REINFORCEMENT"],
                  "active_narratives": [{"category": "INFORMED_PRESSURE", "targets": ["P4"], "evidence": []},
                                       {"category": "MISDIRECTION", "targets": ["P3"], "evidence": []},
                                       {"category": "FUTURE_NARRATIVE_LABEL", "targets": ["P4"], "evidence": []}]}
        labels = [tactic[key] for key in ("role", "strategy_mode", "primary_objective", "secondary_objective", "agenda_topic")]
        labels += tactic["constraints"] + [n["category"] for n in tactic["active_narratives"]]
        for label in labels:
            for variant in (label, label.lower().replace("_", " "), label.lower().replace("_", "-")):
                for field in ("statement", "rationale"):
                    with self.subTest(label=variant, field=field):
                        response = deepcopy(self.response)
                        response["social"][field] = "这一轮采用 " + variant + "。"
                        with self.assertRaisesRegex(LLMError, "private_disclosure"):
                            validate_performance(response, self.ids, [], tactic)

    def test_other_valid_targets_or_cards_cannot_override_tactic(self):
        for key, value in (("target", "P5"), ("card", "DEFEND")):
            response = deepcopy(self.response)
            response["social"][key] = value
            with self.assertRaises(ValueError):
                validate_performance(response, self.ids, [], self.tactic)

    def test_evidence_must_be_public_and_reason_matched(self):
        response = deepcopy(self.response)
        response["social"].update(reason="mission_record", evidence=[2])
        with self.assertRaises(ValueError):
            validate_performance(response, self.ids, [{"seq": 2, "kind": "TEAM"}], self.tactic)
        response["social"]["evidence"] = [99]
        with self.assertRaises(ValueError):
            validate_performance(response, self.ids, [{"seq": 2, "kind": "MISSION"}], self.tactic)


if __name__ == "__main__":
    unittest.main()
