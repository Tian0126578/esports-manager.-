import pytest

from scripts.init_db import build_player_team_map, deduplicate_players


def test_deduplicate_players_removes_repeated_player_records():
    players = [
        {"first_name": "Kim", "last_name": "Tae-min", "nick_name": "Delight", "team": "T1"},
        {"first_name": "Kim", "last_name": "Tae-min", "nick_name": "Delight", "team": "T1"},
        {"first_name": "Lee", "last_name": "Min-hyeong", "nick_name": "Gumayusi", "team": "T1"},
    ]

    deduped = deduplicate_players(players)

    assert len(deduped) == 2
    assert deduped[0]["nick_name"] == "Delight"
    assert deduped[1]["nick_name"] == "Gumayusi"


def test_build_player_team_map_uses_only_explicit_team_names():
    players = [
        {"first_name": "Choi", "last_name": "Hyeon-jun", "nick_name": "Zeus", "team": "T1"},
        {"first_name": "Mun", "last_name": "Hyeon-jun", "nick_name": "Oner", "team": "T1"},
        {"first_name": "Kim", "last_name": "Su-hwan", "nick_name": "Kiin", "team": "Gen.G"},
        {"first_name": "Han", "last_name": "Wang-ho", "nick_name": "Peanut", "team": "Gen.G"},
        {"first_name": "Kim", "last_name": "Ki-in", "nick_name": "Rascal", "team": "KT Rolster"},
    ]
    teams = [
        {"name": "T1"},
        {"name": "Gen.G"},
        {"name": "KT Rolster"},
    ]

    mapping = build_player_team_map(players, teams)

    assert mapping[("Choi", "Hyeon-jun", "Zeus")] == "T1"
    assert mapping[("Mun", "Hyeon-jun", "Oner")] == "T1"
    assert mapping[("Kim", "Su-hwan", "Kiin")] == "Gen.G"
    assert mapping[("Han", "Wang-ho", "Peanut")] == "Gen.G"
    assert mapping[("Kim", "Ki-in", "Rascal")] == "KT Rolster"
    assert len(mapping) == 5


def test_build_player_team_map_does_not_guess_teams_when_team_is_missing():
    players = [
        {"first_name": "A", "last_name": "1", "nick_name": "a"},
        {"first_name": "B", "last_name": "2", "nick_name": "b"},
        {"first_name": "C", "last_name": "3", "nick_name": "c"},
        {"first_name": "D", "last_name": "4", "nick_name": "d"},
        {"first_name": "E", "last_name": "5", "nick_name": "e"},
        {"first_name": "F", "last_name": "6", "nick_name": "f"},
    ]
    teams = [
        {"name": "T1"},
        {"name": "Gen.G"},
        {"name": "KT Rolster"},
    ]

    mapping = build_player_team_map(players, teams)

    assert mapping == {}


def test_build_player_team_map_keeps_unassigned_players_unassigned():
    players = [
        {"first_name": "A", "last_name": "1", "nick_name": "a", "team": "T1"},
        {"first_name": "B", "last_name": "2", "nick_name": "b"},
    ]

    mapping = build_player_team_map(players, [{"name": "T1"}])

    assert mapping == {("A", "1", "a"): "T1"}


def test_build_player_team_map_rejects_unknown_team_names():
    players = [
        {"first_name": "A", "last_name": "1", "nick_name": "a", "team": "Unknown"}
    ]

    with pytest.raises(ValueError, match="Unknown team"):
        build_player_team_map(players, [{"name": "T1"}])
