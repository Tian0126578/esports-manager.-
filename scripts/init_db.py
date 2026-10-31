# SPDX-FileCopyrightText: 2025 Pedrenrique G. Guimarães <admin@esportsmanager.net>
# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import random
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from esm.db import DatabaseManager
from esm.config import Config
from esm.models.tournament import (
    TournamentType,
    TournamentFormat,
    TournamentTier,
)
from esm.models.moba.team import MobaTeam
from esm.models.moba.player import MobaPlayer, MobaPlayerRole
from esm.models.moba.champion import (
    MobaChampion,
    MobaChampionRole,
    MobaChampionType,
    MobaChampionDifficulty,
)
from esm.models.moba.champion_mastery import (
    MobaChampionMastery,
    MobaChampionMasteryTier,
)
from esm.models.moba.player_contract import MobaPlayerContract
from esm.models.moba.tournament import MobaTournament


def load_json_file(file_path: str) -> list[dict[str, Any]]:
    """Load data from a JSON file."""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading {file_path}: {e}")
        return []


def player_identity(item: dict[str, Any]) -> tuple[str, str, str]:
    """Return a stable unique identifier for a player.

    We use full name plus nickname because several rosters contain repeated
    nicknames across different players, and nicknames alone overwrite the mapping.
    """
    return (
        str(item.get("first_name") or ""),
        str(item.get("last_name") or ""),
        str(item.get("nick_name") or ""),
    )


def deduplicate_players(players_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove repeated roster entries for the same player identity."""
    seen: set[tuple[str, str, str]] = set()
    unique_players: list[dict[str, Any]] = []

    for item in players_data:
        identity = player_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        unique_players.append(item)

    return unique_players


def build_player_team_map(
    players_data: list[dict[str, Any]],
    teams_data: list[dict[str, Any]],
) -> dict[tuple[str, str, str], str]:
    """Map players to teams only when the roster data explicitly names a team."""
    players_data = deduplicate_players(players_data)
    valid_team_names = {
        team["name"] for team in teams_data if team.get("name")
    }
    assignments = {}
    for item in players_data:
        team_name = item.get("team")
        if not team_name:
            continue
        if team_name not in valid_team_names:
            raise ValueError(
                f"Unknown team {team_name!r} for player {player_identity(item)!r}"
            )
        assignments[player_identity(item)] = team_name
    return assignments


async def add_tournaments(
    session: AsyncSession, data: list[dict[str, Any]]
) -> dict[int, MobaTournament]:
    """Import tournament data into the database."""
    print("Importing tournaments...")
    tournament_map = {}  # Map tournament names to IDs

    for item in data:
        start_date = (
            datetime.strptime(item["start_date"], "%Y-%m-%d")
            if item.get("start_date")
            else None
        )
        end_date = (
            datetime.strptime(item["end_date"], "%Y-%m-%d")
            if item.get("end_date")
            else None
        )

        tournament = MobaTournament(
            name=item["name"],
            abbreviation=item.get("abbreviation"),
            type=TournamentType(item["type"]),
            format=TournamentFormat(item["format"]),
            tier=TournamentTier(item["tier"]),
            start_date=start_date,
            end_date=end_date,
            location=item.get("location"),
            description=item.get("description"),
            default_color=item.get("default_color"),
            logo_path=item.get("logo_path"),
        )

        session.add(tournament)
        await session.flush()  # Flush to get the ID
        tournament_map[item["name"]] = tournament.id
        print(f"  Added tournament: {item['name']}")

    await session.commit()
    print(f"Imported {len(tournament_map)} tournaments")
    return tournament_map


async def add_teams(session: AsyncSession, data: list[dict[str, Any]]) -> dict[int, MobaTeam]:
    """Import team data into the database."""
    print("Importing teams...")
    team_map = {}  # Map team names to IDs

    for item in data:
        team = MobaTeam(
            name=item["name"],
            nationality=item.get("nationality"),
            region=item.get("region"),
            description=item.get("description"),
            logo_path=item.get("logo_path"),
            banner_path=item.get("banner_path"),
        )

        session.add(team)
        await session.flush()
        team_map[team.id] = team
        print(f"  Added team: {team.name}")

    await session.commit()
    print(f"Imported {len(team_map)} teams")
    return team_map


async def add_champions(
    session: AsyncSession, data: list[dict[str, Any]]
) -> dict[int, MobaChampion]:
    """Import champion data into the database."""
    print("Importing champions...")
    champion_map = {}  # Map champion names to IDs

    for item in data:
        release_date = datetime.strptime(item["release_date"], "%Y-%m-%d").date()

        secondary_role = (
            MobaChampionRole(item["secondary_role"])
            if item.get("secondary_role")
            else None
        )
        champion_type2 = (
            MobaChampionType(item["champion_type2"])
            if item.get("champion_type2")
            else None
        )

        champion = MobaChampion(
            name=item["name"],
            release_date=release_date,
            primary_role=MobaChampionRole(item["primary_role"]),
            secondary_role=secondary_role,
            champion_type1=MobaChampionType(item["champion_type1"]),
            champion_type2=champion_type2,
            difficulty=MobaChampionDifficulty(item["difficulty"]),
            strength=item["strength"],
            image_path=item.get("image_path"),
            description=item.get("description"),
            win_rate=item.get("win_rate"),
            pick_rate=item.get("pick_rate"),
            ban_rate=item.get("ban_rate"),
        )

        session.add(champion)
        await session.flush()
        champion_map[champion.id] = champion
        print(f"  Added champion: {champion.name}")

    await session.commit()
    print(f"Imported {len(champion_map)} champions")
    return champion_map


async def add_players(
    session: AsyncSession,
    data: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Import player data into the database."""
    print("Importing players...")
    player_map = {}  # Map player nicknames to IDs

    for item in data:
        date_of_birth = (
            datetime.strptime(item["date_of_birth"], "%Y-%m-%d").date()
            if item.get("date_of_birth")
            else None
        )

        player = MobaPlayer(
            first_name=item["first_name"],
            last_name=item["last_name"],
            nick_name=item["nick_name"],
            date_of_birth=date_of_birth,
            nationality=item.get("nationality"),
            bio=item.get("bio"),
            image_path=item.get("image_path"),
            role=MobaPlayerRole(item["role"]),
            is_active=item.get("is_active", True),
            mechanics=item.get("mechanics", 50),
            knowledge=item.get("knowledge", 50),
            agility=item.get("agility", 50),
            reflexes=item.get("reflexes", 50),
            accuracy=item.get("accuracy", 50),
            aggression=item.get("aggression", 50),
            vision=item.get("vision", 50),
            farming=item.get("farming", 50),
            communication=item.get("communication", 50),
            concentration=item.get("concentration", 50),
            leadership=item.get("leadership", 50),
            teamwork=item.get("teamwork", 50),
            decisions=item.get("decisions", 50),
            morale=item.get("morale", 50),
            form=item.get("form", 50),
            value=item.get("value", 1000000),
        )

        session.add(player)
        await session.flush()
        player_map[player.id] = player
        print(f"  Added player: {player.nick_name}")

    await session.commit()
    print(f"Imported {len(player_map)} players")
    return player_map


async def create_player_contracts(
    session: AsyncSession,
    player_map: Dict[int, MobaPlayer],
    team_map: Dict[int, MobaTeam],
    players_data: List[Dict[str, Any]],
) -> None:
    """Create player contracts based on roster team assignments."""
    print("Creating player contracts...")
    contracts_created = 0
    team_name_by_id = {team.id: team.name for team in team_map.values()}
    player_team_map = build_player_team_map(players_data, [{"name": team.name} for team in team_map.values()])

    for player in player_map.values():
        team_name = player_team_map.get(
            (player.first_name, player.last_name, player.nick_name)
        )
        if not team_name:
            continue

        team_id = next(
            (team.id for team in team_map.values() if team.name == team_name),
            None,
        )
        if team_id is None:
            continue

        contract = MobaPlayerContract(
            player_id=player.id,
            team_id=team_id,
            start_date=datetime.now().date(),
            end_date=datetime(2026, 12, 31).date(),
            salary=500000,
            is_active=True,
        )

        session.add(contract)
        await session.commit()
        contracts_created += 1
        print(f"  Created contract: {player.nick_name} -> {team_name_by_id[team_id]}")

    print(f"Created {contracts_created} player contracts")


async def add_champions_to_champion_pool(
    session: AsyncSession,
    champion_map: dict[int, MobaChampion],
    player_map: dict[int, MobaPlayer],
):
    for player in player_map.values():
        number_champions = random.randint(5, 20)
        champions_list = list(champion_map.values())
        champions_list = list(
            filter(lambda x: x.primary_role.value == player.role.value, champions_list)
        )
        champions_list = sorted(champions_list, key=lambda x: x.strength)

        champions = random.sample(champions_list, number_champions)
        mastery_tiers = list(MobaChampionMasteryTier)
        if player.overall >= 80:
            mastery_tiers.remove(MobaChampionMasteryTier.BRONZE)
            mastery_tiers.remove(MobaChampionMasteryTier.SILVER)
            mastery_tiers.remove(MobaChampionMasteryTier.GOLD)
            mastery_tiers.remove(MobaChampionMasteryTier.PLATINUM)
        for champion in champions:
            tier = random.choice(mastery_tiers)
            mastery = MobaChampionMastery(
                player_id=player.id,
                champion_id=champion.id,
                tier=tier,
                points=0,
            )
            session.add(mastery)
            await session.commit()
            print(
                f"Added champion {champion.name} to player {player.nick_name} with tier {tier}"
            )
    print("Added champions to champion pool")


async def main():
    """Main function to import all data."""
    print("Starting data import...")

    config = Config()
    config.load_config()

    database_path = config.database_url.replace('sqlite+aiosqlite:///', '')
    if os.path.exists(database_path):
        print("Database already exists. Please remove it before running this script.")
        return

    db_manager = DatabaseManager(config.database_url)
    await db_manager.create_db_and_tables()

    script_dir = Path(__file__).parent

    tournaments_file = script_dir / "tournaments.json"
    teams_file = script_dir / "teams.json"
    players_file = script_dir / "players.json"
    champions_file = script_dir / "champions.json"

    for file_path in [tournaments_file, teams_file, players_file, champions_file]:
        if not file_path.exists():
            print(f"Error: {file_path} does not exist")
            return

    tournaments_data = load_json_file(tournaments_file)
    teams_data = load_json_file(teams_file)
    players_data = load_json_file(players_file)
    players_data = deduplicate_players(players_data)
    champions_data = load_json_file(champions_file)

    # Import data into the database
    async for session in db_manager.get_session():
        # Import data in order of dependencies
        await add_tournaments(session, tournaments_data)
        team_map = await add_teams(session, teams_data)
        champions_map = await add_champions(session, champions_data)
        player_map = await add_players(session, players_data)

        # Create player contracts using roster-based team assignments.
        await create_player_contracts(session, player_map, team_map, players_data)
        await add_champions_to_champion_pool(session, champions_map, player_map)
        break  # Only iterate once

    print("Data import completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
