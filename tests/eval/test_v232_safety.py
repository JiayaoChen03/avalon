"""Regression tests for the offline MerlinVoteCamouflageV1 safety audit."""

import json
from pathlib import Path

from avalon.eval.v2 import v232_p1, v232_safety


def _cases():
    run = Path("results/joint_belief_v2_3_2/20260919-v232-r2-p1-offline-v12")
    return json.loads((run / "p1_preregistered_cases.json").read_text())["cases"]


def test_safety_baseline_uses_recorded_merlin_vote_not_fixed_approve():
    cases = _cases()
    records, _ = v232_p1._source_records()
    # The first case is an approve; the fifth is a recorded reject with strong vote.
    first = cases[0]
    fifth = cases[4]
    for case, expected_vote, expected_strong in ((first, True, False), (fifth, False, True)):
        record = records[(case["source_run_id"], case["game_id"])]
        effect, _, _ = v232_safety._case_rows(record, case, primary_other=case["other_ballots"])
        assert effect["baseline_vote"] is expected_vote
        assert effect["baseline_strong"] is expected_strong


def test_safety_case_does_not_inject_future_events(tmp_path):
    result = v232_safety.run(tmp_path)
    assert result["network_calls"] == 0
    assert result["future_events_injected"] == 0
    assert result["valid_pairs"] == 6
    assert result["invalid_pairs"] == 0
    assert result["gate"] == "CANDIDATE_EFFECT_BUT_UNSAFE"
