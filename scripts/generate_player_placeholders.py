# SPDX-FileCopyrightText: 2026 eSports Manager contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAYER_IMAGE_DIR = PLAYER_ASSET_IMAGE_DIR
PLACEHOLDER_MANIFEST = (
    Path(__file__).resolve().parent / "generated_player_placeholders.json"
)
CREDIT_MANIFESTS = (
    Path(__file__).resolve().parent / "player_image_credits.json",
    Path(__file__).resolve().parent / "leaguepedia_player_image_credits.json",
)
IMAGE_SIZE = (300, 400)
ROLE_LABELS = {
    "Top": "Top",
    "Jungle": "Jg",
    "Mid": "Mid",
    "ADC": "Adc",
    "Support": "Sup",
}
ROLE_COLORS = {
    "Top": (87, 118, 255),
    "Jungle": (59, 201, 168),
    "Mid": (173, 107, 255),
    "ADC": (245, 163, 81),
    "Support": (94, 191, 255),
}
FONT_REGULAR = Path("C:/Windows/Fonts/segoeui.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/segoeuib.ttf")
FONT_FALLBACKS = (
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)
FONT_BOLD_FALLBACKS = (
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        (FONT_BOLD, *FONT_BOLD_FALLBACKS)
        if bold
        else (FONT_REGULAR, *FONT_FALLBACKS)
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    start_size: int,
    minimum_size: int = 18,
) -> ImageFont.ImageFont:
    for size in range(start_size, minimum_size - 1, -1):
        font = load_font(size, bold=True)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return font
    return load_font(minimum_size, bold=True)


def normalized_filename(ign: str) -> str:
    filename = normalized_ign(
        unicodedata.normalize("NFKD", ign)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    if not filename:
        raise ValueError(f"IGN cannot be converted to a filename: {ign!r}")
    return f"{filename}.png"


def create_player_placeholder(
    ign: str,
    role: str,
    output_path: Path,
) -> None:
    if role not in ROLE_LABELS:
        raise ValueError(f"Unsupported player role: {role}")

    width, height = IMAGE_SIZE
    accent = ROLE_COLORS[role]
    image = Image.new("RGB", IMAGE_SIZE)
    pixels = image.load()
    for y in range(height):
        blend = y / (height - 1)
        color = tuple(
            round(start + (end - start) * blend)
            for start, end in zip((14, 17, 36), (34, 24, 66), strict=True)
        )
        for x in range(width):
            pixels[x, y] = color

    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        (13, 13, width - 14, height - 14),
        radius=18,
        outline=(*accent, 180),
        width=2,
    )
    draw.ellipse((35, 75, 265, 305), fill=(*accent, 22))
    draw.ellipse((51, 91, 249, 289), outline=(*accent, 65), width=2)
    draw.ellipse((69, 109, 231, 271), outline=(*accent, 90), width=1)

    initials = "".join(part[0] for part in ign.split() if part)[:2].upper()
    initials_font = load_font(76, bold=True)
    initial_bounds = draw.textbbox((0, 0), initials, font=initials_font)
    initials_x = (width - (initial_bounds[2] - initial_bounds[0])) // 2
    initials_y = 154 - (initial_bounds[3] - initial_bounds[1]) // 2
    draw.text(
        (initials_x, initials_y),
        initials,
        font=initials_font,
        fill=(255, 255, 255, 238),
        stroke_width=1,
        stroke_fill=(*accent, 220),
    )

    ign_font = fit_font(
        draw,
        ign,
        max_width=width - 38,
        start_size=35,
    )
    ign_bounds = draw.textbbox((0, 0), ign, font=ign_font)
    ign_x = (width - (ign_bounds[2] - ign_bounds[0])) // 2
    draw.text(
        (ign_x, 310),
        ign,
        font=ign_font,
        fill=(255, 255, 255, 255),
        stroke_width=1,
        stroke_fill=(16, 18, 38, 255),
    )

    label = ROLE_LABELS[role]
    label_font = load_font(18, bold=True)
    label_bounds = draw.textbbox((0, 0), label, font=label_font)
    label_width = label_bounds[2] - label_bounds[0]
    chip_width = label_width + 34
    chip_left = (width - chip_width) // 2
    draw.rounded_rectangle(
        (chip_left, 355, chip_left + chip_width, 385),
        radius=13,
        fill=(*accent, 42),
        outline=(*accent, 220),
        width=1,
    )
    draw.text(
        ((width - label_width) // 2, 359),
        label,
        font=label_font,
        fill=(255, 255, 255, 255),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)


def configured_database_path() -> Path:
    config = Config()
    config.load_config()
    prefix = "sqlite+aiosqlite:///"
    if not config.database_url.startswith(prefix):
        raise ValueError(
            "Placeholder generation requires the configured SQLite database"
        )
    return Path(config.database_url[len(prefix) :])


def update_seed_and_database(image_paths: dict[str, str]) -> None:
    players = load_json(PLAYERS_FILE)
    for player in players:
        image_path = image_paths.get(normalized_ign(player["nick_name"]))
        if image_path is not None:
            player["image_path"] = image_path

    original_seed = PLAYERS_FILE.read_bytes()
    updated_seed = (
        json.dumps(players, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    connection = sqlite3.connect(configured_database_path())
    try:
        connection.execute("BEGIN IMMEDIATE")
        for player in players:
            image_path = image_paths.get(normalized_ign(player["nick_name"]))
            if image_path is None:
                continue
            cursor = connection.execute(
                "UPDATE moba_players SET image_path = ? WHERE nick_name = ?",
                (image_path, player["nick_name"]),
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


def generate_roster_placeholders() -> dict[str, Any]:
    roster = validate_roster(load_json(ROSTER_FILE))
    PLAYER_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    image_paths = {}
    manifest = {}

    for player in roster:
        ign = player["ign"]
        filename = normalized_filename(ign)
        image_path = PLAYER_IMAGE_DIR / filename
        create_player_placeholder(ign, player["role"], image_path)
        sidecar = image_path.with_name(image_path.name + ".license")
        if sidecar.exists():
            sidecar.unlink()
        image_paths[normalized_ign(ign)] = filename
        manifest[ign] = {
            "image": filename,
            "role": ROLE_LABELS[player["role"]],
            "size": list(IMAGE_SIZE),
            "source": "Generated locally with Pillow; no network access",
            "license": "GPL-3.0-or-later",
        }

    update_seed_and_database(image_paths)
    PLACEHOLDER_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for manifest_path in CREDIT_MANIFESTS:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return manifest


def main() -> None:
    manifest = generate_roster_placeholders()
    print(
        f"Generated {len(manifest)} local PNG placeholders "
        f"({IMAGE_SIZE[0]}x{IMAGE_SIZE[1]}) in {PLAYER_IMAGE_DIR}"
    )


if __name__ == "__main__":
    main()
