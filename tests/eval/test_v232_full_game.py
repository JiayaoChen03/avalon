"""Targeted checks for the V3 full-game validation adapter."""

from avalon.eval.v2.v232_full_game import PROFILE_BY_SEED, SEEDS, scenario_players


def test_full_game_plan_has_frozen_six_seed_pairs():
    assert len(SEEDS) == 6
    assert len(set(SEEDS)) == 6
    assert set(SEEDS) == set(PROFILE_BY_SEED)


def test_focal_seat_is_merlin_for_every_seed():
    for seed in SEEDS:
        players = scenario_players(seed)
        roles = {player.id: player.role for player in players}
        assert roles["P1"] == "MERLIN"
        assert list(roles.values()).count("MERLIN") == 1


def test_full_game_adapter_is_evaluation_only():
    from avalon.eval.v2 import v232_full_game as full_game

    assert full_game.CANDIDATE == "MerlinVoteCamouflageV3PublicConsensus"
    assert full_game.ROOT.name == "avalon"
