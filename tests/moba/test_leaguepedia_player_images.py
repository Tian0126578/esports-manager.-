import json
import sqlite3
import urllib.error
from io import BytesIO

from PIL import Image

import scripts.fetch_leaguepedia_player_images as downloader
from scripts.fetch_leaguepedia_player_images import (
    choose_player_png,
    license_is_reusable,
    player_image_filename,
    player_image_matches,
    spdx_license_id,
)


def _file_page(
    title: str,
    *,
    mime: str = "image/png",
    license_name: str = "CC BY-SA 3.0",
) -> dict:
    return {
        "title": f"File:{title}",
        "imageinfo": [
            {
                "mime": mime,
                "url": "https://lol.fandom.com/images/player.png",
                "descriptionurl": "https://lol.fandom.com/wiki/File:player.png",
                "extmetadata": {
                    "LicenseShortName": {"value": license_name},
                    "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/3.0/"},
                    "Artist": {"value": "Photographer"},
                    "ImageDescription": {"value": "League of Legends player"},
                },
            }
        ],
    }


def test_leaguepedia_image_requires_exact_ign_png_and_reusable_license():
    player = {"ign": "Faker"}
    page = _file_page("Faker.png")

    assert player_image_matches(page, player)
    chosen = choose_player_png([page], player)
    assert chosen is not None
    assert chosen["title"] == "File:Faker.png"
    assert chosen["spdx_license_id"] == "CC-BY-SA-3.0"
    assert chosen["artist"] == "Photographer"

    assert not player_image_matches(_file_page("Chet Faker.png"), player)
    assert choose_player_png([_file_page("Faker.jpg", mime="image/jpeg")], player) is None
    assert choose_player_png(
        [_file_page("Faker.png", license_name="CC BY-NC 4.0")], player
    ) is None
    assert choose_player_png(
        [_file_page("Faker.png", license_name="CC BY-ND 4.0")], player
    ) is None


def test_only_explicitly_reusable_license_families_are_accepted():
    assert license_is_reusable({"LicenseShortName": {"value": "CC BY 4.0"}})
    assert license_is_reusable({"LicenseShortName": {"value": "CC BY-SA 4.0"}})
    assert license_is_reusable({"LicenseShortName": {"value": "CC0 1.0"}})
    assert not license_is_reusable({"LicenseShortName": {"value": "CC BY-NC 4.0"}})
    assert not license_is_reusable({"LicenseShortName": {"value": "CC BY-ND 4.0"}})
    assert spdx_license_id({"LicenseShortName": {"value": "CC BY 4.0"}}) == "CC-BY-4.0"
    assert spdx_license_id({"LicenseShortName": {"value": "CC0 1.0"}}) == "CC0-1.0"
    assert spdx_license_id({"LicenseShortName": {"value": "All rights reserved"}}) is None
    assert player_image_filename("Hans Sama") == "hanssama.png"
    assert player_image_filename("Jojopyun") == "jojopyun.png"


def test_processing_updates_assets_seed_database_and_fallbacks(tmp_path, monkeypatch):
    source_players = json.loads(downloader.PLAYERS_FILE.read_text(encoding="utf-8"))
    players_file = tmp_path / "players.json"
    players_file.write_text(
        json.dumps(source_players, ensure_ascii=False), encoding="utf-8"
    )
    database_path = tmp_path / "players.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE moba_players (nick_name TEXT PRIMARY KEY, image_path TEXT)"
        )
        connection.executemany(
            "INSERT INTO moba_players (nick_name, image_path) VALUES (?, ?)",
            [(player["nick_name"], "old.png") for player in source_players],
        )

    class TestConfig:
        database_url = f"sqlite+aiosqlite:///{database_path}"

        def load_config(self):
            return None

    png = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(png, format="PNG")
    valid_png = png.getvalue()
    monkeypatch.setattr(downloader, "Config", TestConfig)
    monkeypatch.setattr(downloader, "PLAYERS_FILE", players_file)
    monkeypatch.setattr(downloader, "PLAYER_IMAGE_DIR", tmp_path / "assets")
    monkeypatch.setattr(
        downloader, "LEGACY_PLAYER_IMAGE_DIR", tmp_path / "no-legacy-images"
    )
    monkeypatch.setattr(downloader, "CREDITS_FILE", tmp_path / "credits.json")
    monkeypatch.setattr(
        downloader, "LEGACY_CREDITS_FILE", tmp_path / "no-legacy-credits.json"
    )
    monkeypatch.setattr(
        downloader, "fetch_player_image_files", lambda delay: [_file_page("Faker.png")]
    )
    monkeypatch.setattr(downloader, "download_png", lambda url: valid_png)
    monkeypatch.setattr(
        downloader,
        "create_labeled_placeholder",
        lambda ign, path: path.write_bytes(valid_png),
    )

    downloader.process_portraits(delay=0)

    updated_players = json.loads(players_file.read_text(encoding="utf-8"))
    credits = json.loads((tmp_path / "credits.json").read_text(encoding="utf-8"))
    assert len(updated_players) == 95
    assert len(list((tmp_path / "assets").glob("*.png"))) == 95
    assert all(
        path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        for path in (tmp_path / "assets").glob("*.png")
    )
    assert credits["Faker"]["source"] == "Leaguepedia/Fandom"
    assert credits["Faker"]["image"] == "faker.png"
    assert credits["Duro"]["source"] == "Generated local placeholder"
    assert len({player["image_path"] for player in updated_players}) == 95
    assert all(
        (tmp_path / "assets" / player["image_path"]).is_file()
        for player in updated_players
    )
    assert (
        tmp_path / "assets" / "faker.png.license"
    ).read_text(encoding="utf-8").splitlines() == [
        "SPDX-FileCopyrightText: Photographer",
        "SPDX-License-Identifier: CC-BY-SA-3.0",
    ]
    with sqlite3.connect(database_path) as connection:
        database_images = dict(
            connection.execute("SELECT nick_name, image_path FROM moba_players")
        )
    assert len(database_images) == 95
    assert all(
        database_images[player["nick_name"]] == player["image_path"]
        for player in updated_players
    )


def test_unavailable_leaguepedia_reuses_real_photo_and_generates_valid_pngs(
    tmp_path, monkeypatch
):
    source_players = json.loads(downloader.PLAYERS_FILE.read_text(encoding="utf-8"))
    faker = next(player for player in source_players if player["nick_name"] == "Faker")
    faker["image_path"] = "faker-source.jpg"
    players_file = tmp_path / "players.json"
    players_file.write_text(
        json.dumps(source_players, ensure_ascii=False), encoding="utf-8"
    )
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    Image.new("RGB", (4, 4), "red").save(
        legacy_dir / "faker-source.jpg", format="JPEG"
    )

    captured_paths = {}
    monkeypatch.setattr(downloader, "PLAYERS_FILE", players_file)
    monkeypatch.setattr(downloader, "PLAYER_IMAGE_DIR", tmp_path / "assets")
    monkeypatch.setattr(downloader, "LEGACY_PLAYER_IMAGE_DIR", legacy_dir)
    monkeypatch.setattr(downloader, "CREDITS_FILE", tmp_path / "credits.json")
    monkeypatch.setattr(
        downloader, "LEGACY_CREDITS_FILE", tmp_path / "no-legacy-credits.json"
    )

    def unavailable(delay):
        raise urllib.error.HTTPError(
            "https://lol.fandom.com/api.php", 403, "Forbidden", {}, None
        )

    monkeypatch.setattr(downloader, "fetch_player_image_files", unavailable)
    monkeypatch.setattr(downloader, "update_player_images", captured_paths.update)

    downloader.process_portraits(delay=0)

    credits = json.loads((tmp_path / "credits.json").read_text(encoding="utf-8"))
    files = list((tmp_path / "assets").glob("*.png"))
    assert len(files) == len(captured_paths) == 95
    assert credits["Faker"]["source"] == "Existing bundled project image"
    assert credits["Duro"]["source"] == "Generated local placeholder"
    for path in files:
        with Image.open(path) as image:
            assert image.format == "PNG"
            image.verify()
    assert captured_paths["faker"] == "faker.png"
