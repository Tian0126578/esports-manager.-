# SPDX-FileCopyrightText: 2025 Pedrenrique G. Guimarães <admin@esportsmanager.net>
# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
import json
import re
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esm.config import ESM_DIR, Config

SCRIPT_DIR = Path(__file__).resolve().parent
ROSTER_FILE = SCRIPT_DIR / "worlds_2026_roster.json"
PLAYERS_FILE = SCRIPT_DIR / "players.json"
TEAMS_FILE = SCRIPT_DIR / "teams.json"
PLAYER_IMAGE_DIR = ESM_DIR / "res" / "img" / "players"
PLAYER_ASSET_IMAGE_DIR = (
    Path(__file__).resolve().parents[1] / "assets" / "images" / "players"
)
DEFAULT_PLAYER_IMAGE = "default_player.webp"
ROLE_MAP = {
    "Top": "top",
    "Jungle": "jungle",
    "Mid": "mid",
    "ADC": "adc",
    "Support": "support",
}
PLAYER_DEFAULTS = {
    "mechanics": 50,
    "knowledge": 50,
    "agility": 50,
    "reflexes": 50,
    "accuracy": 50,
    "aggression": 50,
    "vision": 50,
    "farming": 50,
    "communication": 50,
    "concentration": 50,
    "leadership": 50,
    "teamwork": 50,
    "decisions": 50,
    "morale": 50,
    "form": 50,
    "value": 1_000_000,
}
IMAGE_FILENAME_PATTERN = re.compile(r"[^a-z0-9]+")


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def validate_roster(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(teams) != 19:
        raise ValueError(f"Expected 19 teams, received {len(teams)}")
    if len({team["team"] for team in teams}) != len(teams):
        raise ValueError("Roster contains duplicate team names")

    players = []
    seen_igns = set()
    expected_roles = set(ROLE_MAP)
    for team in teams:
        team_players = team.get("players", [])
        if len(team_players) != 5:
            raise ValueError(f"{team['team']} must have exactly five players")
        if {player["role"] for player in team_players} != expected_roles:
            raise ValueError(f"{team['team']} must have one player per role")
        for player in team_players:
            ign = player.get("ign", "").strip()
            real_name = player.get("real_name", "").strip()
            if not ign or not real_name or player.get("role") not in ROLE_MAP:
                raise ValueError(f"Invalid player record in {team['team']}: {player}")
            if ign.casefold() in seen_igns:
                raise ValueError(f"Duplicate player IGN: {ign}")
            seen_igns.add(ign.casefold())
            player["ign"] = ign
            player["real_name"] = real_name
            player["team"] = team["team"]
            player["region"] = team["region"]
            players.append(player)
    if len(players) != 95:
        raise ValueError(f"Expected 95 players, received {len(players)}")
    return players


def normalized_name(value: str) -> str:
    return " ".join(value.casefold().split())


def normalized_ign(value: str) -> str:
    return IMAGE_FILENAME_PATTERN.sub("", value.casefold())


def build_player_data(
    roster_players: list[dict[str, Any]],
    old_players: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    image_directories = (PLAYER_IMAGE_DIR, PLAYER_ASSET_IMAGE_DIR)
    assets = {
        normalized_ign(path.stem): path.name
        for directory in image_directories
        if directory.is_dir()
        for path in directory.iterdir()
        if path.is_file()
        and path.name != DEFAULT_PLAYER_IMAGE
        and not path.stem.endswith("-placeholder")
    }
    unused = set(range(len(old_players)))
    output = []

    for player in roster_players:
        full_name = normalized_name(player["real_name"])
        ign = normalized_name(player["ign"])
        candidates = [
            index
            for index in unused
            if normalized_name(
                f"{old_players[index].get('first_name', '')} "
                f"{old_players[index].get('last_name', '')}"
            )
            == full_name
        ]
        exact_identity = [
            index
            for index in candidates
            if normalized_name(old_players[index].get("nick_name") or "") == ign
        ]
        ign_matches = [
            index
            for index in unused
            if normalized_name(old_players[index].get("nick_name") or "") == ign
        ]
        match = next(
            iter(exact_identity or candidates or ign_matches),
            None,
        )
        previous = old_players[match] if match is not None else {}
        if match is not None:
            unused.remove(match)

        name_parts = player["real_name"].split(maxsplit=1)
        previous_image = previous.get("image_path")
        canonical_asset = assets.get(normalized_ign(player["ign"]))
        if canonical_asset:
            image_path = canonical_asset
        elif (
            previous_image
            and previous_image != DEFAULT_PLAYER_IMAGE
            and any(
                (directory / previous_image).is_file()
                for directory in image_directories
            )
        ):
            image_path = previous_image
        else:
            image_path = assets.get(
                normalized_ign(player["ign"]), DEFAULT_PLAYER_IMAGE
            )
        record = {
            "first_name": name_parts[0],
            "last_name": name_parts[1] if len(name_parts) > 1 else "",
            "real_name": player["real_name"],
            "nick_name": player["ign"],
            "date_of_birth": previous.get("date_of_birth"),
            "nationality": previous.get("nationality"),
            "bio": None,
            "image_path": image_path,
            "role": ROLE_MAP[player["role"]],
            "team": player["team"],
            "region": player["region"],
            "is_active": True,
        }
        for field, default in PLAYER_DEFAULTS.items():
            value = previous.get(field, default)
            if field != "value":
                value = min(99, max(1, value))
            record[field] = value
        output.append(record)
    return output


def build_team_data(
    teams: list[dict[str, Any]], old_teams: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    old_by_name = {team["name"]: team for team in old_teams}
    output = []
    for team in teams:
        previous = old_by_name.get(team["team"], {})
        output.append(
            {
                "name": team["team"],
                "nationality": previous.get("nationality"),
                "region": team["region"],
                "description": previous.get("description"),
                "logo_path": previous.get("logo_path"),
                "banner_path": previous.get("banner_path"),
            }
        )
    return output


def database_path() -> Path:
    config = Config()
    config.load_config()
    prefix = "sqlite+aiosqlite:///"
    if not config.database_url.startswith(prefix):
        raise ValueError("Roster synchronization supports the configured SQLite database only")
    return Path(config.database_url[len(prefix) :])


def ensure_nullable_birth_date(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info(moba_players)")
    }
    if not columns or not columns["date_of_birth"][3]:
        return

    connection.execute(
        """
        CREATE TABLE moba_players_new (
            first_name VARCHAR NOT NULL,
            last_name VARCHAR NOT NULL,
            date_of_birth DATE,
            nick_name VARCHAR,
            nationality VARCHAR,
            bio VARCHAR,
            image_path VARCHAR,
            role VARCHAR(7),
            is_active BOOLEAN NOT NULL,
            mechanics INTEGER NOT NULL,
            knowledge INTEGER NOT NULL,
            agility INTEGER NOT NULL,
            reflexes INTEGER NOT NULL,
            accuracy INTEGER NOT NULL,
            vision INTEGER NOT NULL,
            farming INTEGER NOT NULL,
            communication INTEGER NOT NULL,
            aggression INTEGER NOT NULL,
            concentration INTEGER NOT NULL,
            leadership INTEGER NOT NULL,
            teamwork INTEGER NOT NULL,
            decisions INTEGER NOT NULL,
            morale INTEGER NOT NULL,
            form INTEGER NOT NULL,
            value INTEGER NOT NULL,
            id INTEGER NOT NULL PRIMARY KEY,
            created_at DATETIME NOT NULL,
            updated_at DATETIME
        )
        """
    )
    names = ", ".join(f'"{name}"' for name in columns)
    connection.execute(
        f"INSERT INTO moba_players_new ({names}) SELECT {names} FROM moba_players"
    )
    connection.execute("DROP TABLE moba_players")
    connection.execute("ALTER TABLE moba_players_new RENAME TO moba_players")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_moba_players_role ON moba_players (role)"
    )


def referencing_rows(
    connection: sqlite3.Connection,
    target_table: str,
    target_ids: set[int],
    allowed_tables: set[str],
) -> list[str]:
    if not target_ids:
        return []
    issues = []
    placeholders = ",".join("?" for _ in target_ids)
    for (table,) in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ):
        if table in allowed_tables:
            continue
        for foreign_key in connection.execute(f'PRAGMA foreign_key_list("{table}")'):
            if foreign_key[2] != target_table:
                continue
            column = foreign_key[3]
            count = connection.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IN ({placeholders})',
                tuple(target_ids),
            ).fetchone()[0]
            if count:
                issues.append(f"{table}.{column}: {count}")
    return issues


def sync_database(
    path: Path,
    teams: list[dict[str, Any]],
    players: list[dict[str, Any]],
) -> None:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        ensure_nullable_birth_date(connection)

        existing_teams = {
            row["name"]: dict(row)
            for row in connection.execute("SELECT * FROM moba_teams")
        }
        desired_team_names = {team["name"] for team in teams}
        obsolete_team_ids = {
            row["id"]
            for name, row in existing_teams.items()
            if name not in desired_team_names
        }
        team_references = referencing_rows(
            connection,
            "moba_teams",
            obsolete_team_ids,
            {"moba_player_contracts"},
        )
        if team_references:
            raise ValueError(
                "Cannot remove obsolete teams because gameplay history references "
                + ", ".join(team_references)
            )

        existing_players = [
            dict(row)
            for row in connection.execute("SELECT * FROM moba_players")
        ]
        old_by_identity = {
            (
                normalized_name(row["first_name"] + " " + row["last_name"]),
                normalized_name(row["nick_name"] or ""),
            ): row
            for row in existing_players
        }
        old_by_ign: dict[str, list[dict[str, Any]]] = {}
        for row in existing_players:
            old_by_ign.setdefault(normalized_name(row["nick_name"] or ""), []).append(row)

        used_ids = set()
        player_rows = []
        for player in players:
            name_key = normalized_name(player["real_name"])
            ign_key = normalized_name(player["nick_name"])
            row = old_by_identity.get((name_key, ign_key))
            if row is None:
                row = next(
                    (
                        candidate
                        for candidate in old_by_ign.get(ign_key, [])
                        if candidate["id"] not in used_ids
                    ),
                    None,
                )
            if row is not None and row["id"] in used_ids:
                row = None
            if row is not None:
                player["id"] = row["id"]
                player["_created_at"] = row["created_at"]
                player["_updated_at"] = row["updated_at"]
                for field in ("date_of_birth", "nationality", *PLAYER_DEFAULTS):
                    if field == "date_of_birth" or player.get(field) is None:
                        player[field] = row[field]
                used_ids.add(row["id"])
            player_rows.append(player)

        removed_player_ids = {
            row["id"] for row in existing_players if row["id"] not in used_ids
        }
        player_references = referencing_rows(
            connection,
            "moba_players",
            removed_player_ids,
            {"moba_player_contracts", "moba_champion_masteries"},
        )
        if player_references:
            raise ValueError(
                "Cannot remove players because gameplay history references "
                + ", ".join(player_references)
            )

        active_contracts = [
            (row["nick_name"], row["name"])
            for row in connection.execute(
                """
                SELECT p.nick_name, t.name
                FROM moba_player_contracts c
                JOIN moba_players p ON p.id = c.player_id
                JOIN moba_teams t ON t.id = c.team_id
                WHERE c.is_active = 1
                """
            )
        ]
        desired_contracts = sorted(
            (player["nick_name"], player["team"]) for player in players
        )
        current_contracts = sorted(active_contracts)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS moba_roster_contract_archive (
                archive_id INTEGER PRIMARY KEY,
                contract_id INTEGER NOT NULL,
                player_ign TEXT,
                team_name TEXT,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                leave_date DATE,
                salary INTEGER NOT NULL,
                is_active BOOLEAN NOT NULL,
                created_at DATETIME,
                updated_at DATETIME,
                archived_at DATETIME NOT NULL
            )
            """
        )
        if current_contracts != desired_contracts:
            connection.execute(
                """
                INSERT INTO moba_roster_contract_archive (
                    contract_id, player_ign, team_name, start_date, end_date,
                    leave_date, salary, is_active, created_at, updated_at, archived_at
                )
                SELECT c.id, p.nick_name, t.name, c.start_date, c.end_date,
                       c.leave_date, c.salary, c.is_active, c.created_at,
                       c.updated_at, ?
                FROM moba_player_contracts c
                LEFT JOIN moba_players p ON p.id = c.player_id
                LEFT JOIN moba_teams t ON t.id = c.team_id
                """,
                (datetime.now(UTC).isoformat(),),
            )
            connection.execute("DELETE FROM moba_player_contracts")

        for team in teams:
            previous = existing_teams.get(team["name"])
            if previous:
                connection.execute(
                    """
                    UPDATE moba_teams
                    SET nationality = ?, region = ?, description = ?,
                        logo_path = ?, banner_path = ?
                    WHERE id = ?
                    """,
                    (
                        team.get("nationality"),
                        team["region"],
                        team.get("description"),
                        team.get("logo_path"),
                        team.get("banner_path"),
                        previous["id"],
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO moba_teams
                    (name, nationality, region, description, logo_path, banner_path,
                     created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        team["name"],
                        team.get("nationality"),
                        team["region"],
                        team.get("description"),
                        team.get("logo_path"),
                        team.get("banner_path"),
                        datetime.now(UTC).isoformat(),
                    ),
                )
        if obsolete_team_ids:
            connection.executemany(
                "DELETE FROM moba_teams WHERE id = ?",
                [(team_id,) for team_id in obsolete_team_ids],
            )

        if removed_player_ids:
            connection.executemany(
                "DELETE FROM moba_champion_masteries WHERE player_id = ?",
                [(player_id,) for player_id in removed_player_ids],
            )
            connection.executemany(
                "DELETE FROM moba_players WHERE id = ?",
                [(player_id,) for player_id in removed_player_ids],
            )

        now = datetime.now(UTC).isoformat()
        for player in player_rows:
            name_parts = player["real_name"].split(maxsplit=1)
            player_values = (
                name_parts[0],
                name_parts[1] if len(name_parts) > 1 else "",
                player.get("date_of_birth"),
                player["nick_name"],
                player.get("nationality"),
                None,
                player["image_path"],
                player["role"].upper(),
                1,
                *(player[field] for field in PLAYER_DEFAULTS),
            )
            if "id" in player:
                connection.execute(
                    """
                    UPDATE moba_players SET
                        first_name=?, last_name=?, date_of_birth=?, nick_name=?,
                        nationality=?, bio=?, image_path=?, role=?, is_active=?,
                        mechanics=?, knowledge=?, agility=?, reflexes=?, accuracy=?,
                        aggression=?, vision=?, farming=?, communication=?,
                        concentration=?, leadership=?, teamwork=?, decisions=?,
                        morale=?, form=?, value=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        *player_values,
                        now,
                        player["id"],
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO moba_players (
                        first_name, last_name, date_of_birth, nick_name, nationality,
                        bio, image_path, role, is_active, mechanics, knowledge,
                        agility, reflexes, accuracy, aggression, vision, farming,
                        communication, concentration, leadership, teamwork, decisions,
                        morale, form, value, created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (*player_values, now),
                )
                player["id"] = connection.execute(
                    "SELECT last_insert_rowid()"
                ).fetchone()[0]

        team_ids = {
            row["name"]: row["id"]
            for row in connection.execute("SELECT id, name FROM moba_teams")
        }
        player_ids = {
            normalized_name(row["nick_name"]): row["id"]
            for row in connection.execute(
                "SELECT id, nick_name FROM moba_players"
            )
        }
        start_date = date.today().isoformat()
        end_date = date(2026, 12, 31).isoformat()
        if current_contracts != desired_contracts:
            for player in players:
                connection.execute(
                    """
                    INSERT INTO moba_player_contracts
                    (start_date, end_date, salary, is_active, team_id, player_id, created_at)
                    VALUES (?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        start_date,
                        end_date,
                        500_000,
                        team_ids[player["team"]],
                        player_ids[normalized_name(player["nick_name"])],
                        now,
                    ),
                )

        team_count = connection.execute(
            "SELECT COUNT(*) FROM moba_teams"
        ).fetchone()[0]
        roster_count = connection.execute(
            """
            SELECT COUNT(DISTINCT p.id)
            FROM moba_players p
            JOIN moba_player_contracts c ON c.player_id = p.id
            WHERE c.is_active = 1
            """
        ).fetchone()[0]
        contract_count = connection.execute(
            "SELECT COUNT(*) FROM moba_player_contracts WHERE is_active = 1"
        ).fetchone()[0]
        if (team_count, roster_count, contract_count) != (19, 95, 95):
            raise ValueError(
                f"Post-sync validation failed: teams={team_count}, "
                f"rostered_players={roster_count}, active_contracts={contract_count}"
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    teams = load_json(ROSTER_FILE)
    roster_players = validate_roster(teams)
    old_players = load_json(PLAYERS_FILE)
    old_teams = load_json(TEAMS_FILE)
    players_data = build_player_data(roster_players, old_players)
    teams_data = build_team_data(teams, old_teams)

    sync_database(database_path(), teams_data, players_data)

    PLAYERS_FILE.write_text(
        json.dumps(players_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    TEAMS_FILE.write_text(
        json.dumps(teams_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Synchronized {len(teams_data)} teams and {len(players_data)} players. "
        "Missing player portraits use the bundled default avatar."
    )


if __name__ == "__main__":
    main()
