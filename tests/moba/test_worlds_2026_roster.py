import json

from scripts.sync_worlds_2026_roster import (
    PLAYER_ASSET_IMAGE_DIR,
    PLAYER_IMAGE_DIR,
    ROSTER_FILE,
    build_player_data,
    build_team_data,
    load_json,
    validate_roster,
)


def test_worlds_2026_roster_has_19_teams_and_95_unique_players():
    teams = load_json(ROSTER_FILE)
    players = validate_roster(teams)

    assert len(teams) == 19
    assert len(players) == 95
    assert len({player["ign"].casefold() for player in players}) == 95
    assert {team["region"] for team in teams} == {
        "LCK",
        "LPL",
        "LEC",
        "LCS",
        "LCP",
        "CBLOL",
    }


def test_seed_data_has_exact_roster_team_region_and_resolvable_images():
    teams = load_json(ROSTER_FILE)
    players = validate_roster(teams)
    generated_players = build_player_data(players, [])
    generated_teams = build_team_data(teams, [])

    assert len(generated_teams) == 19
    assert all(len(team["players"]) == 5 for team in teams)
    for source, generated in zip(players, generated_players, strict=True):
        assert generated["nick_name"] == source["ign"]
        assert generated["real_name"] == source["real_name"]
        assert generated["role"] == source["role"].lower()
        assert generated["team"] == source["team"]
        assert generated["region"] == source["region"]
        assert any(
            (directory / generated["image_path"]).is_file()
            for directory in (PLAYER_IMAGE_DIR, PLAYER_ASSET_IMAGE_DIR)
        )
        assert all(
            1 <= generated[field] <= 99
            for field in (
                "mechanics",
                "knowledge",
                "agility",
                "reflexes",
                "accuracy",
                "aggression",
                "vision",
                "farming",
                "communication",
                "concentration",
                "leadership",
                "teamwork",
                "decisions",
                "morale",
                "form",
            )
        )
    assert all(
        team["region"] == source["region"]
        for team, source in zip(generated_teams, teams, strict=True)
    )


def test_roster_json_is_valid_utf8_and_keeps_accented_names():
    roster = json.loads(ROSTER_FILE.read_text(encoding="utf-8"))
    players = [player for team in roster for player in team["players"]]

    assert any(player["real_name"] == "Nguyễn Phú Kiệt" for player in players)
    assert any(player["real_name"] == "Sergen Çelik" for player in players)
    assert any(player["real_name"] == "Álvaro Fernández del Amo" for player in players)


def test_seed_sync_finds_player_images_in_assets_directory(tmp_path, monkeypatch):
    import scripts.sync_worlds_2026_roster as roster_sync

    image_path = tmp_path / "faker.png"
    image_path.write_bytes(b"test image")
    monkeypatch.setattr(roster_sync, "PLAYER_ASSET_IMAGE_DIR", tmp_path)

    players = validate_roster(load_json(ROSTER_FILE))
    generated = build_player_data(players, [])
    faker = next(player for player in generated if player["nick_name"] == "Faker")

    assert faker["image_path"] == "faker.png"
