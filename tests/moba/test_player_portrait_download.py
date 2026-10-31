import json
import struct
import zlib
from io import BytesIO

from PIL import Image

from scripts.fetch_player_portraits import (
    candidate_matches_player,
    convert_to_png,
    create_labeled_placeholder,
    filename_slug,
    image_signature_is_valid,
    license_is_reusable,
)


def test_commons_license_filter_only_accepts_reusable_license_families():
    assert license_is_reusable({"LicenseShortName": {"value": "CC BY 4.0"}})
    assert license_is_reusable({"LicenseShortName": {"value": "CC BY-SA 4.0"}})
    assert license_is_reusable({"LicenseShortName": {"value": "CC0 1.0"}})
    assert not license_is_reusable({"LicenseShortName": {"value": "CC BY-NC 4.0"}})
    assert not license_is_reusable({"LicenseShortName": {"value": "CC BY-ND 4.0"}})


def test_commons_candidate_must_match_player_and_esports_context():
    faker = {"ign": "Faker"}
    metadata = {
        "ImageDescription": {"value": "Faker at the League of Legends Worlds 2024"},
    }

    assert candidate_matches_player("File:Faker at Worlds 2024.jpg", metadata, faker)
    assert candidate_matches_player(
        "File:T1 Faker Lee Sang-Hyeok in a 2026 Interview.png",
        {
            "ImageDescription": {
                "value": "Faker in a League of Legends interview"
            }
        },
        {"ign": "Faker", "team": "T1"},
    )
    assert not candidate_matches_player(
        "File:Chet Faker at The Rolling Stone Awards.jpg",
        {
            "ImageDescription": {
                "value": "Australian electronic musician Chet Faker"
            },
        },
        {"ign": "Faker", "team": "T1"},
    )
    assert not candidate_matches_player(
        "File:Caps G2 2020.jpg",
        {
            "ImageDescription": {"value": "Caps with G2 in 2020"},
            "Categories": {"value": "League of Legends esports"},
        },
        faker,
    )
    assert not candidate_matches_player(
        "File:Faker portrait.jpg",
        {"ImageDescription": {"value": "Faker portrait"}, "Categories": {"value": ""}},
        faker,
    )
    assert not candidate_matches_player(
        "File:Faker Hall of Legends press conference.jpg",
        {
            "ImageDescription": {"value": "Faker at the press conference"},
            "Categories": {"value": "Oner (gamer), Keria (gamer)"},
        },
        {"ign": "Oner"},
    )
    assert not candidate_matches_player(
        "File:La Karmine Corp lors du LEC Roadtrip.jpg",
        {
            "ImageDescription": {"value": "Canna with La Karmine Corp during the LEC Roadtrip"},
            "Categories": {"value": "Canna (gamer), Yike (gamer), Caliste (gamer)"},
        },
        {"ign": "Canna"},
    )


def test_generated_fallback_is_valid_png_and_uses_player_name(tmp_path):
    output = tmp_path / "faker-placeholder.png"

    create_labeled_placeholder("Faker", output)

    image_data = output.read_bytes()
    assert image_signature_is_valid(image_data, "image/png")
    assert struct.unpack(">2I", image_data[16:24]) == (320, 320)
    compressed_data = image_data[41:-16]
    decoded = zlib.decompress(compressed_data)
    assert len(decoded) == 320 * (1 + 320 * 3)
    white_pixels = sum(
        decoded[offset : offset + 3] == b"\xff\xff\xff"
        for offset in range(1, len(decoded), 3)
    )
    assert white_pixels > 100


def test_portrait_name_and_conversion_use_canonical_png():
    assert filename_slug("Hans Sama") == "hanssama"

    jpeg = BytesIO()
    Image.new("RGB", (4, 4), "red").save(jpeg, format="JPEG")

    converted = convert_to_png(jpeg.getvalue())

    assert image_signature_is_valid(converted, "image/png")
    with Image.open(BytesIO(converted)) as image:
        assert image.format == "PNG"
        assert image.size == (4, 4)


def test_portrait_process_writes_canonical_png_for_every_player(tmp_path, monkeypatch):
    import scripts.fetch_player_portraits as downloader

    players = downloader.load_json(downloader.PLAYERS_FILE)
    faker = next(player for player in players if player["nick_name"] == "Faker")
    faker["image_path"] = "faker-source.jpg"
    players_file = tmp_path / "players.json"
    players_file.write_text(json.dumps(players), encoding="utf-8")
    assets = tmp_path / "assets"
    legacy = tmp_path / "legacy"
    assets.mkdir()
    legacy.mkdir()
    Image.new("RGB", (4, 4), "red").save(
        legacy / "faker-source.jpg", format="JPEG"
    )
    credits_file = tmp_path / "credits.json"
    credits_file.write_text("{}", encoding="utf-8")
    captured_paths = {}
    jpeg = BytesIO()
    Image.new("RGB", (4, 4), "blue").save(jpeg, format="JPEG")

    monkeypatch.setattr(downloader, "PLAYER_IMAGE_DIR", assets)
    monkeypatch.setattr(downloader, "LEGACY_PLAYER_IMAGE_DIR", legacy)
    monkeypatch.setattr(downloader, "PLAYERS_FILE", players_file)
    monkeypatch.setattr(downloader, "CREDITS_FILE", credits_file)
    monkeypatch.setattr(
        downloader,
        "choose_commons_image",
        lambda player, excluded: (
            {
                "url": "https://commons.example/chovy.jpg",
                "mime_type": "image/jpeg",
                "title": "File:Chovy portrait.jpg",
                "description_url": "https://commons.example/wiki/Chovy",
                "license": "CC BY 4.0",
                "artist": "Photographer",
                "credit": "",
                "description": "Chovy, League of Legends player",
            }
            if player["ign"] == "Chovy"
            else None
        ),
    )
    monkeypatch.setattr(
        downloader, "download_image", lambda url, mime_type: jpeg.getvalue()
    )
    monkeypatch.setattr(
        downloader, "update_seed_and_database", captured_paths.update
    )

    downloader.process_portraits(delay=0)

    assert len(captured_paths) == 95
    assert captured_paths["hanssama"] == "hanssama.png"
    assert len(list(assets.glob("*.png"))) == 95
    for path in assets.glob("*.png"):
        with Image.open(path) as image:
            assert image.format == "PNG"
            image.verify()
