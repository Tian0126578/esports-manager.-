# SPDX-FileCopyrightText: 2025 Pedrenrique G. Guimarães <admin@esportsmanager.net>
# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
import argparse
import email.utils
import html
import json
import re
import sqlite3
import struct
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import UTC, datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esm.config import Config
from scripts.sync_worlds_2026_roster import (
    PLAYER_ASSET_IMAGE_DIR,
    PLAYERS_FILE,
    ROSTER_FILE,
    load_json,
    normalized_ign,
    validate_roster,
)
from scripts.sync_worlds_2026_roster import (
    PLAYER_IMAGE_DIR as LEGACY_PLAYER_IMAGE_DIR,
)

PLAYER_IMAGE_DIR = PLAYER_ASSET_IMAGE_DIR
CREDITS_FILE = Path(__file__).resolve().parent / "player_image_credits.json"
API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = (
    "EsportsManagerRosterImages/1.0 "
    "(https://github.com/esports-manager/esports-manager; "
    "admin@esportsmanager.net)"
)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
LICENSE_PREFIXES = (
    "cc by ",
    "cc by-sa ",
    "cc by-sa ",
    "cc0",
    "public domain",
    "pd-",
    "us public domain",
)
COMMONS_SEARCH_LIMIT = 30

FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "11001", "10101", "10011", "10011", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}


class PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: str) -> str:
    parser = PlainTextParser()
    parser.feed(html.unescape(value))
    return " ".join(parser.parts)


def filename_slug(ign: str) -> str:
    return normalized_ign(ign) or "player"


def license_is_reusable(metadata: dict[str, Any]) -> bool:
    license_name = plain_text(metadata.get("LicenseShortName", {}).get("value", ""))
    normalized = license_name.casefold().strip()
    return normalized.startswith(LICENSE_PREFIXES)


def candidate_matches_player(
    title: str, metadata: dict[str, Any], player: dict[str, str]
) -> bool:
    description = plain_text(
        metadata.get("ImageDescription", {}).get("value", "")
    )
    ign = re.escape(player["ign"])
    matcher = re.compile(rf"(?<!\w){ign}(?!\w)", flags=re.IGNORECASE)
    title_match = matcher.search(title)
    if not title_match:
        return False
    context = f"{title} {description}".casefold().replace("_", " ")
    has_esports_context = bool(
        re.search(
            r"\bleague of legends\b|\besports?\b|\bmoba\b|"
            r"\b(?:lck|lpl|lec|lcs|lcp|cblol)\b",
            context,
        )
    )
    if not has_esports_context or (
        player["ign"].casefold() == "faker" and "chet faker" in context
    ):
        return False
    if len(player["ign"]) <= 3:
        real_name = player.get("real_name", "")
        real_name_match = bool(
            real_name
            and re.search(
                re.escape(real_name), context, flags=re.IGNORECASE
            )
        )
        return real_name_match
    return bool(title_match)


def candidate_score(
    title: str, metadata: dict[str, Any], player: dict[str, str]
) -> int:
    ign = re.compile(rf"(?<!\w){re.escape(player['ign'])}(?!\w)", re.IGNORECASE)
    if ign.search(title):
        return 3
    if ign.search(plain_text(metadata.get("ImageDescription", {}).get("value", ""))):
        return 2
    return 1


def commons_search(player: dict[str, str]) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": f'"{player["ign"]}"',
            "gsrnamespace": 6,
            "gsrlimit": COMMONS_SEARCH_LIMIT,
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 640,
            "format": "json",
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 3:
                raise
            retry_after = error.headers.get("Retry-After")
            try:
                wait_seconds = float(retry_after)
            except (TypeError, ValueError):
                retry_time = email.utils.parsedate_to_datetime(retry_after or "")
                wait_seconds = max(
                    1,
                    (retry_time - datetime.now(UTC)).total_seconds(),
                )
            print(
                f"Wikimedia rate limit reached for {player['ign']}; "
                f"retrying in {wait_seconds:.0f} seconds."
            )
            time.sleep(wait_seconds)
    pages = data.get("query", {}).get("pages", {}).values()
    return sorted(pages, key=lambda page: page.get("index", 0))


def choose_commons_image(
    player: dict[str, str], excluded_sources: set[str] | None = None
) -> dict[str, str] | None:
    candidates = []
    for page in commons_search(player):
        image_info = page.get("imageinfo", [{}])[0]
        metadata = image_info.get("extmetadata", {})
        mime_type = image_info.get("mime") or metadata.get("MimeType", {}).get(
            "value", ""
        )
        url = image_info.get("thumburl") or image_info.get("url")
        description_url = image_info.get("descriptionurl", "")
        if (
            not url
            or description_url in (excluded_sources or set())
            or mime_type not in ALLOWED_MIME_TYPES
            or not license_is_reusable(metadata)
            or not candidate_matches_player(page.get("title", ""), metadata, player)
        ):
            continue
        candidates.append(
            (
                candidate_score(page["title"], metadata, player),
                page,
                image_info,
                metadata,
            )
        )
    candidates.sort(key=lambda result: (-result[0], result[1].get("index", 0)))
    for _, page, image_info, metadata in candidates:
        mime_type = image_info.get("mime") or metadata.get("MimeType", {}).get(
            "value", ""
        )
        url = image_info.get("thumburl") or image_info.get("url")
        return {
            "title": page["title"],
            "url": url,
            "description_url": image_info["descriptionurl"],
            "mime_type": mime_type,
            "license": plain_text(metadata["LicenseShortName"]["value"]),
            "license_url": metadata.get("LicenseUrl", {}).get("value", ""),
            "artist": plain_text(metadata.get("Artist", {}).get("value", "")),
            "credit": plain_text(metadata.get("Credit", {}).get("value", "")),
            "description": plain_text(
                metadata.get("ImageDescription", {}).get("value", "")
            ),
        }
    return None


def download_image(url: str, mime_type: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": mime_type}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        content_type = response.headers.get_content_type()
        if content_type != mime_type:
            raise ValueError(f"Image content type mismatch: {content_type}")
        data = response.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES} bytes")
    if not image_signature_is_valid(data, mime_type):
        raise ValueError(f"Downloaded data is not a valid {mime_type} image")
    return data


def image_signature_is_valid(data: bytes, mime_type: str) -> bool:
    if mime_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    content = chunk_type + payload
    return (
        struct.pack(">I", len(payload))
        + content
        + struct.pack(">I", zlib.crc32(content) & 0xFFFFFFFF)
    )


def create_labeled_placeholder(ign: str, output_path: Path) -> None:
    width = height = 320
    seed = sum((index + 1) * ord(char) for index, char in enumerate(ign))
    accent = (60 + seed % 100, 75 + seed % 90, 130 + seed % 100)
    pixels = bytearray(width * height * 3)

    def paint(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = bytes(color)

    for y in range(height):
        blend = y / (height - 1)
        color = tuple(int(20 + (channel - 20) * blend) for channel in accent)
        start = y * width * 3
        pixels[start : start + width * 3] = bytes(color) * width

    silhouette = (38, 44, 61)
    for y in range(72, 254):
        for x in range(40, 280):
            if (x - 160) ** 2 + (y - 112) ** 2 <= 47**2 or (
                ((x - 160) / 110) ** 2 + ((y - 259) / 93) ** 2 <= 1
            ):
                paint(x, y, silhouette)

    label = (
        unicodedata.normalize("NFKD", ign)
        .encode("ascii", "ignore")
        .decode("ascii")
        .upper()
    )
    max_chars = 12
    lines = [
        label[index : index + max_chars]
        for index in range(0, len(label), max_chars)
    ] or ["PLAYER"]
    lines = lines[:3]
    scale = 3 if any(len(line) > 10 for line in lines) else 4
    line_height = 8 * scale
    text_top = height - len(lines) * line_height - 13
    for line_index, line in enumerate(lines):
        line_width = max(0, len(line) * 6 * scale - scale)
        left = (width - line_width) // 2
        top = text_top + line_index * line_height
        for char_index, char in enumerate(line):
            glyph = FONT.get(char, FONT[" "])
            for row, pattern in enumerate(glyph):
                for column, pixel in enumerate(pattern):
                    if pixel == "1":
                        for dy in range(scale):
                            for dx in range(scale):
                                paint(
                                    left + char_index * 6 * scale + column * scale + dx,
                                    top + row * scale + dy,
                                    (255, 255, 255),
                                )

    scanlines = b"".join(
        b"\x00" + pixels[y * width * 3 : (y + 1) * width * 3]
        for y in range(height)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + png_chunk(b"IEND", b"")
    )
    output_path.write_bytes(png)


def existing_player_image(
    ign: str,
    preferred_path: str | None = None,
    *,
    include_placeholders: bool = False,
    excluded_names: set[str] | None = None,
) -> Path | None:
    image_directories = (PLAYER_IMAGE_DIR, LEGACY_PLAYER_IMAGE_DIR)
    if preferred_path and preferred_path != "default_player.webp":
        for directory in image_directories:
            preferred = directory / preferred_path
            if preferred.is_file() and preferred.name not in (excluded_names or set()):
                return preferred
    target = normalized_ign(ign)
    candidates = []
    for directory in image_directories:
        if not directory.is_dir():
            continue
        candidates.extend(
            path
            for path in directory.iterdir()
            if (
                path.is_file()
                and path.name not in (excluded_names or set())
                and path.suffix.casefold() in ALLOWED_MIME_TYPES.values()
                and (
                    include_placeholders
                    or not path.stem.casefold().endswith("-placeholder")
                )
                and normalized_ign(path.stem) == target
            )
        )
    candidates.sort(
        key=lambda path: (
            path.stem.casefold().endswith("-placeholder"),
            path.suffix.casefold() != ".png",
        )
    )
    return candidates[0] if candidates else None


def convert_to_png(data: bytes) -> bytes:
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            output = BytesIO()
            image.convert("RGBA" if "A" in image.getbands() else "RGB").save(
                output, format="PNG", optimize=True
            )
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Portrait image is corrupt or unreadable") from error
    png = output.getvalue()
    if not image_signature_is_valid(png, "image/png"):
        raise ValueError("Portrait image conversion did not produce PNG data")
    return png


def save_existing_image(source: Path, destination: Path) -> None:
    destination.write_bytes(convert_to_png(source.read_bytes()))
    source_license = source.with_name(source.name + ".license")
    destination_license = destination.with_name(destination.name + ".license")
    if source_license.is_file():
        destination_license.write_bytes(source_license.read_bytes())
    elif destination_license.exists():
        destination_license.unlink()


def update_seed_and_database(image_paths: dict[str, str]) -> None:
    players = load_json(PLAYERS_FILE)
    for player in players:
        image_path = image_paths.get(normalized_ign(player["nick_name"]))
        if image_path:
            player["image_path"] = image_path

    database = Config()
    database.load_config()
    database_url_prefix = "sqlite+aiosqlite:///"
    if not database.database_url.startswith(database_url_prefix):
        raise ValueError("Portrait syncing requires the configured SQLite database")
    db_path = Path(database.database_url[len(database_url_prefix) :])
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for player in players:
            if player.get("image_path") not in set(image_paths.values()):
                continue
            connection.execute(
                "UPDATE moba_players SET image_path = ? WHERE nick_name = ?",
                (player["image_path"], player["nick_name"]),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    PLAYERS_FILE.write_text(
        json.dumps(players, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def process_portraits(force: bool = False, delay: float = 0.35) -> None:
    roster = validate_roster(load_json(ROSTER_FILE))
    PLAYER_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    image_paths = {}
    failures = []

    old_credits = {}
    if CREDITS_FILE.exists():
        old_credits = json.loads(CREDITS_FILE.read_text(encoding="utf-8"))
    old_players = load_json(PLAYERS_FILE)
    old_images = {
        normalized_ign(player["nick_name"]): player.get("image_path")
        for player in old_players
    }
    used_commons_sources: set[str] = set()
    for entry in roster:
        ign = entry["ign"]
        slug = filename_slug(ign)
        old_credit = old_credits.get(ign, {})
        current_image = (
            None
            if old_credit.get("source") == "Generated local placeholder"
            else existing_player_image(ign, old_images.get(normalized_ign(ign)))
        )
        filename = f"{slug}.png"
        image_path = PLAYER_IMAGE_DIR / filename
        if current_image and old_credit.get("source") == "Wikimedia Commons":
            prior_image_matches = candidate_matches_player(
                old_credit.get("title", ""),
                {"ImageDescription": {"value": old_credit.get("description", "")}},
                entry,
            )
            if not prior_image_matches:
                current_image = existing_player_image(
                    ign,
                    include_placeholders=True,
                    excluded_names={current_image.name},
                )
                old_credit = (
                    {
                        "image": current_image.name,
                        "source": (
                            "Generated local placeholder"
                            if current_image.stem.endswith("-placeholder")
                            else "Existing bundled project image"
                        ),
                        "license": (
                            "GPL-3.0-or-later"
                            if current_image.stem.endswith("-placeholder")
                            else "See the project's existing image license records"
                        ),
                    }
                    if current_image
                    else {}
                )
        if current_image and not force:
            save_existing_image(current_image, image_path)
            image_paths[normalized_ign(ign)] = filename
            manifest[ign] = old_credit or {
                "image": filename,
                "source": (
                    "Generated local placeholder"
                    if current_image.stem.endswith("-placeholder")
                    else "Existing bundled project image"
                ),
                "license": (
                    "GPL-3.0-or-later"
                    if current_image.stem.endswith("-placeholder")
                    else "See the project's existing image license records"
                ),
            }
            manifest[ign]["image"] = filename
            continue

        try:
            source = choose_commons_image(entry, used_commons_sources)
            if source:
                data = convert_to_png(
                    download_image(source["url"], source["mime_type"])
                )
                image_path.write_bytes(data)
                manifest[ign] = {
                    **source,
                    "image": filename,
                    "source": "Wikimedia Commons",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
                image_paths[normalized_ign(ign)] = filename
                used_commons_sources.add(source["description_url"])
                print(f"Downloaded {ign}: {source['title']} ({source['license']})")
            elif current_image:
                save_existing_image(current_image, image_path)
                image_paths[normalized_ign(ign)] = filename
                manifest[ign] = old_credit or {
                    "image": filename,
                    "source": "Existing bundled project image",
                    "license": "See the project's existing image license records",
                }
                manifest[ign]["image"] = filename
                print(f"No replacement portrait found for {ign}; kept existing image.")
            else:
                create_labeled_placeholder(ign, image_path)
                manifest[ign] = {
                    "image": filename,
                    "source": "Generated local placeholder",
                    "license": "GPL-3.0-or-later",
                }
                image_paths[normalized_ign(ign)] = filename
                print(f"No suitable freely reusable portrait found for {ign}; made placeholder.")
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
            if current_image:
                save_existing_image(current_image, image_path)
                image_paths[normalized_ign(ign)] = filename
                manifest[ign] = {
                    **old_credits.get(
                        ign,
                        {
                            "image": filename,
                            "source": "Existing bundled project image",
                            "license": "See the project's existing image license records",
                        },
                    ),
                    "image": filename,
                    "lookup_error": str(error),
                }
                failures.append((ign, str(error)))
                print(f"Portrait lookup failed for {ign}: {error}; kept existing image.")
                continue
            create_labeled_placeholder(ign, image_path)
            manifest[ign] = {
                "image": filename,
                "source": "Generated local placeholder",
                "license": "GPL-3.0-or-later",
                "lookup_error": str(error),
            }
            image_paths[normalized_ign(ign)] = filename
            failures.append((ign, str(error)))
            print(f"Portrait lookup failed for {ign}: {error}; made placeholder.")
        if delay:
            time.sleep(delay)

    update_seed_and_database(image_paths)
    CREDITS_FILE.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Processed {len(roster)} players: "
        f"{sum(item.get('source') == 'Wikimedia Commons' for item in manifest.values())} "
        f"licensed Commons photos and "
        f"{sum(item.get('source') == 'Generated local placeholder' for item in manifest.values())} "
        "named placeholders."
    )
    if failures:
        print(f"Image lookups/downloads failed for {len(failures)} players.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch reusable player portraits from Wikimedia Commons."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing portraits and placeholders with Commons results when found.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between Commons queries (default: 2).",
    )
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay must not be negative")
    process_portraits(force=args.force, delay=args.delay)


if __name__ == "__main__":
    main()
