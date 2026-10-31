# SPDX-FileCopyrightText: 2026 eSports Manager contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esm.config import Config
from scripts.fetch_player_portraits import (
    create_labeled_placeholder,
    image_signature_is_valid,
    plain_text,
)
from scripts.sync_worlds_2026_roster import (
    PLAYER_IMAGE_DIR as LEGACY_PLAYER_IMAGE_DIR,
)
from scripts.sync_worlds_2026_roster import (
    PLAYERS_FILE,
    ROSTER_FILE,
    load_json,
    normalized_ign,
    validate_roster,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAYER_IMAGE_DIR = PROJECT_ROOT / "assets" / "images" / "players"
CREDITS_FILE = Path(__file__).resolve().parent / "leaguepedia_player_image_credits.json"
LEGACY_CREDITS_FILE = Path(__file__).resolve().parent / "player_image_credits.json"
API_URL = "https://lol.fandom.com/api.php"
USER_AGENT = (
    "EsportsManagerRosterImages/1.0 "
    "(https://github.com/esports-manager/esports-manager; "
    "admin@esportsmanager.net)"
)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
SUPPORTED_SPDX_LICENSES = {
    "CC-BY-2.0",
    "CC-BY-3.0",
    "CC-BY-4.0",
    "CC-BY-SA-3.0",
    "CC-BY-SA-4.0",
    "CC0-1.0",
}
REUSABLE_LICENSES = (
    "cc by ",
    "cc by-sa ",
    "cc0",
    "public domain",
    "pd-",
    "us public domain",
)


def license_is_reusable(metadata: dict[str, Any]) -> bool:
    license_name = plain_text(
        metadata.get("LicenseShortName", {}).get("value", "")
    ).casefold().strip()
    if any(
        term in license_name
        for term in ("-nc", "-nd", "noncommercial", "no derivatives")
    ):
        return False
    return license_name.startswith(REUSABLE_LICENSES)


def spdx_license_id(metadata: dict[str, Any]) -> str | None:
    license_name = plain_text(
        metadata.get("LicenseShortName", {}).get("value", "")
    ).casefold().strip()
    if license_name.startswith("cc0"):
        license_id = "CC0-1.0"
        return license_id if license_id in SUPPORTED_SPDX_LICENSES else None
    match = re.match(r"^cc by(-sa)?\s+(\d+(?:\.\d+)?)\b", license_name)
    if not match:
        return None
    family = "CC-BY-SA" if match.group(1) else "CC-BY"
    license_id = f"{family}-{match.group(2)}"
    return license_id if license_id in SUPPORTED_SPDX_LICENSES else None


def player_image_filename(ign: str) -> str:
    ascii_name = (
        unicodedata.normalize("NFKD", ign)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    normalized = re.sub(r"[^a-z0-9]+", "", ascii_name)
    if not normalized:
        raise ValueError(f"IGN cannot be converted to an image filename: {ign!r}")
    return f"{normalized}.png"


def player_image_matches(page: dict[str, Any], player: dict[str, str]) -> bool:
    title = page.get("title", "")
    if not title.casefold().startswith("file:"):
        return False
    image_stem = Path(title[5:]).stem
    return normalized_ign(image_stem) == normalized_ign(player["ign"])


def fetch_player_image_files(delay: float = 0.25) -> list[dict[str, Any]]:
    files = []
    continuation: dict[str, str] = {}
    while True:
        params = {
            "action": "query",
            "generator": "categorymembers",
            "gcmtitle": "Category:Player_Images",
            "gcmtype": "file",
            "gcmlimit": "max",
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "format": "json",
            **continuation,
        }
        request = urllib.request.Request(
            f"{API_URL}?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        pages = data.get("query", {}).get("pages", {})
        files.extend(pages.values())
        continuation = data.get("continue", {})
        if not continuation:
            return files
        if delay:
            time.sleep(delay)


def choose_player_png(
    files: list[dict[str, Any]], player: dict[str, str]
) -> dict[str, Any] | None:
    candidates = []
    for page in files:
        if not player_image_matches(page, player):
            continue
        image_info = page.get("imageinfo", [{}])[0]
        metadata = image_info.get("extmetadata", {})
        license_id = spdx_license_id(metadata)
        artist = plain_text(metadata.get("Artist", {}).get("value", ""))
        if (
            image_info.get("mime") != "image/png"
            or not image_info.get("url")
            or license_id is None
            or not license_is_reusable(metadata)
            or not artist
        ):
            continue
        candidates.append((page, image_info, metadata, license_id, artist))
    if not candidates:
        return None
    page, image_info, metadata, license_id, artist = candidates[0]
    return {
        "title": page["title"],
        "url": image_info["url"],
        "description_url": image_info.get("descriptionurl", ""),
        "license": plain_text(metadata["LicenseShortName"]["value"]),
        "spdx_license_id": license_id,
        "license_url": metadata.get("LicenseUrl", {}).get("value", ""),
        "artist": artist,
        "description": plain_text(
            metadata.get("ImageDescription", {}).get("value", "")
        ),
    }


def download_png(url: str) -> bytes:
    parsed_url = urllib.parse.urlparse(url)
    hostname = parsed_url.hostname or ""
    if parsed_url.scheme != "https" or not (
        hostname in ("fandom.com", "wikia.nocookie.net")
        or hostname.endswith((".fandom.com", ".wikia.nocookie.net"))
    ):
        raise ValueError("Leaguepedia returned an image URL outside Fandom domains")
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "image/png"}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.headers.get_content_type() != "image/png":
            raise ValueError("Leaguepedia image endpoint did not return PNG data")
        data = response.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES} bytes")
    if not image_signature_is_valid(data, "image/png"):
        raise ValueError("Leaguepedia image response is not a valid PNG")
    validate_png(data)
    return data


def validate_png(data: bytes) -> None:
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError("Image content is not a PNG")
            image.verify()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Downloaded PNG is corrupt or unreadable") from error


def existing_player_portrait(
    ign: str,
    previous_path: str | None,
    credits: dict[str, Any],
) -> tuple[Path, dict[str, Any]] | None:
    old_credit = credits.get(ign, {})
    if old_credit.get("source") == "Generated local placeholder":
        return None

    image_dirs = (PLAYER_IMAGE_DIR, LEGACY_PLAYER_IMAGE_DIR)
    preferred = [Path(previous_path)] if previous_path else []
    candidates = []
    for path in preferred:
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.extend(directory / path for directory in image_dirs)
    for directory in image_dirs:
        if directory.is_dir():
            candidates.extend(
                path
                for path in directory.iterdir()
                if path.is_file()
                and normalized_ign(path.stem) == normalized_ign(ign)
                and not path.stem.casefold().endswith("-placeholder")
            )

    credited_image = old_credit.get("image")
    if credited_image:
        candidates = [
            path
            for path in candidates
            if path.name == credited_image
        ]

    seen = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        sidecar = path.with_name(path.name + ".license")
        previous_credit = old_credit
        if path.parent == PLAYER_IMAGE_DIR and not (
            sidecar.is_file()
            or (
                previous_credit.get("image") == path.name
                and previous_credit.get("source")
                != "Generated local placeholder"
            )
        ):
            continue
        try:
            with Image.open(path) as image:
                image.verify()
        except (UnidentifiedImageError, OSError):
            continue
        if previous_credit.get("image") == path.name and previous_credit.get("source"):
            return path, previous_credit
        if sidecar.is_file():
            return path, {
                "image": path.name,
                "source": "Existing licensed project image",
            }
        return path, {
            "image": path.name,
            "source": "Existing bundled project image",
            "license": "See existing project image license records",
        }
    return None


def load_previous_credits() -> dict[str, Any]:
    credits = {}
    if CREDITS_FILE.is_file():
        credits = json.loads(CREDITS_FILE.read_text(encoding="utf-8"))
    if not LEGACY_CREDITS_FILE.is_file():
        return credits

    legacy_credits = json.loads(LEGACY_CREDITS_FILE.read_text(encoding="utf-8"))
    for ign, legacy_credit in legacy_credits.items():
        current_credit = credits.get(ign, {})
        current_image = PLAYER_IMAGE_DIR / current_credit.get("image", "")
        has_leaguepedia_attribution = (
            current_credit.get("source") == "Leaguepedia/Fandom"
            and current_image.with_name(current_image.name + ".license").is_file()
        )
        if not has_leaguepedia_attribution:
            credits[ign] = legacy_credit
    return credits


def convert_to_png(source_path: Path) -> bytes:
    try:
        with Image.open(source_path) as image:
            image.load()
            output = BytesIO()
            image.convert("RGBA" if "A" in image.getbands() else "RGB").save(
                output, format="PNG", optimize=True
            )
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError(f"Existing player portrait is corrupt: {source_path}") from error
    data = output.getvalue()
    validate_png(data)
    return data


def update_player_images(image_paths: dict[str, str]) -> None:
    players = load_json(PLAYERS_FILE)
    for player in players:
        image_path = image_paths.get(normalized_ign(player["nick_name"]))
        if image_path is not None:
            player["image_path"] = image_path

    database = Config()
    database.load_config()
    prefix = "sqlite+aiosqlite:///"
    if not database.database_url.startswith(prefix):
        raise ValueError("Leaguepedia image syncing requires the configured SQLite database")
    database_path = Path(database.database_url[len(prefix) :])
    original_seed = PLAYERS_FILE.read_bytes()
    updated_seed = json.dumps(players, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        known_image_paths = set(image_paths.values())
        for player in players:
            if player.get("image_path") in known_image_paths:
                cursor = connection.execute(
                    "UPDATE moba_players SET image_path = ? WHERE nick_name = ?",
                    (player["image_path"], player["nick_name"]),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        f"Expected one database row for {player['nick_name']}, "
                        f"updated {cursor.rowcount}"
                    )
        PLAYERS_FILE.write_bytes(updated_seed)
        connection.commit()
    except Exception:
        connection.rollback()
        PLAYERS_FILE.write_bytes(original_seed)
        raise
    finally:
        connection.close()


def process_portraits(delay: float = 0.25) -> None:
    players = validate_roster(load_json(ROSTER_FILE))
    try:
        files = fetch_player_image_files(delay)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        print(
            "Leaguepedia is unavailable; preserving existing portraits and "
            f"generating placeholders for remaining players: {error}"
        )
        files = []
    PLAYER_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    filenames = [player_image_filename(player["ign"]) for player in players]
    slugs = [Path(filename).stem for filename in filenames]
    if len(set(slugs)) != len(slugs):
        raise ValueError("Roster contains IGN names that collide as image filenames")

    image_paths = {}
    credits = {}
    previous_players = {
        normalized_ign(player["nick_name"]): player
        for player in load_json(PLAYERS_FILE)
    }
    previous_credits = load_previous_credits()

    for player in players:
        ign = player["ign"]
        filename = player_image_filename(ign)
        image_path = PLAYER_IMAGE_DIR / filename
        source = choose_player_png(files, player)
        download_error = None
        image_data = None
        if source is not None:
            try:
                image_data = download_png(source["url"])
            except (urllib.error.URLError, TimeoutError, ValueError) as error:
                download_error = str(error)
                print(f"Leaguepedia image download failed for {ign}: {download_error}")

        license_path = image_path.with_name(image_path.name + ".license")
        if image_data is not None and source is not None:
            image_path.write_bytes(image_data)
            artist = re.sub(r"[\r\n\x00]+", " ", source["artist"]).strip()
            license_path.write_text(
                "\n".join(
                    (
                        f"SPDX-FileCopyrightText: {artist}",
                        f"SPDX-License-Identifier: {source['spdx_license_id']}",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            credits[ign] = {
                **source,
                "image": filename,
                "source": "Leaguepedia/Fandom",
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
            print(f"Downloaded licensed Leaguepedia PNG for {ign}.")
        else:
            previous = previous_players.get(normalized_ign(ign), {})
            existing = existing_player_portrait(
                ign, previous.get("image_path"), previous_credits
            )
            if existing is not None:
                source_path, existing_credit = existing
                image_path.write_bytes(convert_to_png(source_path))
                source_sidecar = source_path.with_name(source_path.name + ".license")
                if license_path.exists():
                    license_path.unlink()
                if source_sidecar.is_file():
                    license_path.write_bytes(source_sidecar.read_bytes())
                elif existing_credit.get("source") == "Wikimedia Commons":
                    license_id = spdx_license_id(
                        {
                            "LicenseShortName": {
                                "value": existing_credit.get("license", "")
                            }
                        }
                    )
                    if license_id and existing_credit.get("artist"):
                        license_path.write_text(
                            "\n".join(
                                (
                                    (
                                        "SPDX-FileCopyrightText: "
                                        f"{existing_credit['artist']}"
                                    ),
                                    f"SPDX-License-Identifier: {license_id}",
                                    "",
                                )
                            ),
                            encoding="utf-8",
                        )
                credits[ign] = {
                    **existing_credit,
                    "image": filename,
                }
                print(f"Reused existing portrait for {ign}.")
            else:
                create_labeled_placeholder(ign, image_path)
                if license_path.exists():
                    license_path.unlink()
                credits[ign] = {
                    "image": filename,
                    "source": "Generated local placeholder",
                    "license": "GPL-3.0-or-later",
                }
                if download_error:
                    credits[ign]["download_error"] = download_error
                print(
                    f"No reusable portrait found for {ign}; "
                    "created PNG placeholder."
                )
        image_paths[normalized_ign(ign)] = filename

    update_player_images(image_paths)
    CREDITS_FILE.write_text(
        json.dumps(credits, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    downloaded_count = sum(
        item["source"] == "Leaguepedia/Fandom" for item in credits.values()
    )
    placeholder_count = sum(
        item["source"] == "Generated local placeholder"
        for item in credits.values()
    )
    reused_count = len(credits) - downloaded_count - placeholder_count
    print(
        f"Processed {len(players)} players: "
        f"{downloaded_count} Leaguepedia PNGs, "
        f"{reused_count} reused project portraits, "
        f"{placeholder_count} placeholders."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch explicitly reusable PNG player portraits from the "
            "Leaguepedia/Fandom Player Images category."
        )
    )
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay must be zero or greater")
    process_portraits(delay=args.delay)


if __name__ == "__main__":
    main()
