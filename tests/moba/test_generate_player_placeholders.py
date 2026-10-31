import json
import sqlite3
from pathlib import Path

from PIL import Image

import scripts.generate_player_placeholders as generator
from scripts.sync_worlds_2026_roster import load_json, normalized_ign


def test_generates_role_labeled_pngs_and_syncs_seed_and_database(
    tmp_path, monkeypatch
):
    roster = load_json(generator.ROSTER_FILE)
    seed_players = load_json(generator.PLAYERS_FILE)
    roster_file = tmp_path / "roster.json"
    players_file = tmp_path / "players.json"
    assets_dir = tmp_path / "assets"
    manifest_file = tmp_path / "manifest.json"
    database_file = tmp_path / "players.db"
    roster_file.write_text(json.dumps(roster, ensure_ascii=False), encoding="utf-8")
    players_file.write_text(
        json.dumps(seed_players, ensure_ascii=False), encoding="utf-8"
    )
    with sqlite3.connect(database_file) as connection:
        connection.execute(
            "CREATE TABLE moba_players (nick_name TEXT PRIMARY KEY, image_path TEXT)"
        )
        connection.executemany(
            "INSERT INTO moba_players (nick_name, image_path) VALUES (?, ?)",
            [(player["nick_name"], "old.webp") for player in seed_players],
        )

    monkeypatch.setattr(generator, "ROSTER_FILE", roster_file)
    monkeypatch.setattr(generator, "PLAYERS_FILE", players_file)
    monkeypatch.setattr(generator, "PLAYER_IMAGE_DIR", assets_dir)
    monkeypatch.setattr(generator, "PLACEHOLDER_MANIFEST", manifest_file)
    monkeypatch.setattr(
        generator,
        "configured_database_path",
        lambda: Path(database_file),
    )

    manifest = generator.generate_roster_placeholders()

    assert len(manifest) == 95
    assert len(list(assets_dir.glob("*.png"))) == 95
    assert manifest["Doran"]["role"] == "Top"
    assert manifest["Delight"]["role"] == "Sup"
    updated_players = json.loads(players_file.read_text(encoding="utf-8"))
    assert all(
        player["image_path"]
        == f"{normalized_ign(player['nick_name'])}.png"
        for player in updated_players
    )
    for player in updated_players:
        path = assets_dir / player["image_path"]
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.size == (300, 400)
            image.verify()
    with sqlite3.connect(database_file) as connection:
        image_paths = dict(
            connection.execute("SELECT nick_name, image_path FROM moba_players")
        )
    assert all(
        image_paths[player["nick_name"]] == player["image_path"]
        for player in updated_players
    )
    assert json.loads(manifest_file.read_text(encoding="utf-8")) == manifest
