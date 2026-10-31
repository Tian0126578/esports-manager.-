# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from esm.db import get_session
from esm.models.moba.career import (
    MobaCareerFixture,
    MobaGameAccount,
    MobaGameSave,
)
from esm.models.moba.moba_match import (
    MobaMatch,
    MobaMatchFormat,
    MobaMatchStatus,
)
from esm.models.moba.player import MobaPlayer, MobaPlayerRole
from esm.models.moba.player_contract import MobaPlayerContract
from esm.models.moba.team import MobaTeam
from esm.routes.auth import get_current_account

career_routes = APIRouter(prefix="/career", tags=["career"])
SEED_ROSTER_FILE = (
    Path(__file__).resolve().parents[2] / "scripts" / "worlds_2026_roster.json"
)


class StartCareerRequest(BaseModel):
    team_id: int = Field(gt=0)


async def get_current_save(
    account: MobaGameAccount,
    session: AsyncSession,
) -> MobaGameSave | None:
    result = await session.execute(
        select(MobaGameSave).where(MobaGameSave.account_id == account.id)
    )
    return result.scalars().first()


async def _team_roster_average(
    team_id: int,
    session: AsyncSession,
) -> int:
    result = await session.execute(
        select(MobaPlayer)
        .join(MobaPlayerContract, MobaPlayerContract.player_id == MobaPlayer.id)
        .where(
            MobaPlayerContract.team_id == team_id,
            MobaPlayerContract.is_active.is_(True),
        )
    )
    players = result.scalars().all()
    return sum(player.overall for player in players) // len(players) if players else 0


async def reconcile_seed_rosters(session: AsyncSession) -> bool:
    """Restore canonical team assignments only when seeded roster data is inconsistent."""
    with SEED_ROSTER_FILE.open(encoding="utf-8") as roster_file:
        seed_teams = json.load(roster_file)
    if not isinstance(seed_teams, list) or not seed_teams:
        raise ValueError("The canonical team roster must be a non-empty list.")

    teams_result = await session.execute(select(MobaTeam))
    teams_by_name = {team.name: team for team in teams_result.scalars().all()}
    if any(item.get("team") not in teams_by_name for item in seed_teams):
        return False

    players_result = await session.execute(select(MobaPlayer))
    players = players_result.scalars().all()
    players_by_ign: dict[str, list[MobaPlayer]] = {}
    for player in players:
        if player.nick_name:
            players_by_ign.setdefault(player.nick_name.casefold(), []).append(player)

    expected_team_by_player: dict[int, MobaTeam] = {}
    expected_roster_by_team: dict[int, set[int]] = {}
    expected_role_by_player: dict[int, MobaPlayerRole] = {}
    roles_by_seed_name = {role.value.casefold(): role for role in MobaPlayerRole}
    for seed_team in seed_teams:
        team = teams_by_name[seed_team["team"]]
        seed_players = seed_team.get("players", [])
        if len(seed_players) != 5:
            raise ValueError(
                f"The canonical roster for {team.name} must contain five players."
            )
        team_roster: set[int] = set()
        for seed_player in seed_players:
            matches = players_by_ign.get(seed_player["ign"].casefold(), [])
            if len(matches) != 1:
                return False
            player = matches[0]
            role = roles_by_seed_name.get(seed_player["role"].casefold())
            if role is None:
                raise ValueError(
                    f"Unknown role {seed_player['role']!r} in the canonical roster."
                )
            if player.id is None or player.id in expected_team_by_player:
                return False
            team_roster.add(player.id)
            expected_team_by_player[player.id] = team
            expected_role_by_player[player.id] = role
        expected_roster_by_team[team.id] = team_roster

    contracts_result = await session.execute(select(MobaPlayerContract))
    contracts = contracts_result.scalars().all()
    active_by_team: dict[int, set[int]] = {}
    contracts_by_player: dict[int, list[MobaPlayerContract]] = {}
    for contract in contracts:
        contracts_by_player.setdefault(contract.player_id, []).append(contract)
        if contract.is_active:
            active_by_team.setdefault(contract.team_id, set()).add(contract.player_id)

    has_roster_mismatch = any(
        active_by_team.get(team_id, set()) != expected_player_ids
        for team_id, expected_player_ids in expected_roster_by_team.items()
    )
    has_team_metadata_mismatch = any(
        teams_by_name[seed_team["team"]].region != seed_team["region"]
        for seed_team in seed_teams
    )
    has_role_mismatch = any(
        players_by_ign[seed_player["ign"].casefold()][0].role
        != roles_by_seed_name[seed_player["role"].casefold()]
        for seed_team in seed_teams
        for seed_player in seed_team["players"]
    )
    if not (has_roster_mismatch or has_team_metadata_mismatch or has_role_mismatch):
        return False

    canonical_team_ids = set(expected_roster_by_team)
    for contract in contracts:
        expected_team = expected_team_by_player.get(contract.player_id)
        if (
            contract.is_active
            and contract.team_id in canonical_team_ids
            and expected_team is not None
            and expected_team.id != contract.team_id
        ) or (
            contract.is_active
            and contract.team_id in canonical_team_ids
            and contract.player_id not in expected_roster_by_team[contract.team_id]
        ):
            contract.is_active = False

    today = date.today()
    for player_id, team in expected_team_by_player.items():
        player_contracts = contracts_by_player.get(player_id, [])
        active_contracts = [
            contract for contract in player_contracts if contract.is_active
        ]
        contract = next(
            (item for item in active_contracts if item.team_id == team.id),
            active_contracts[0] if active_contracts else None,
        )
        if contract is None:
            contract = next(
                (item for item in player_contracts if not item.is_active),
                None,
            )
        if contract is None:
            contract = MobaPlayerContract(
                player_id=player_id,
                team_id=team.id,
                start_date=today,
                end_date=today + timedelta(days=365),
                salary=0,
                is_active=True,
            )
            session.add(contract)
            contracts_by_player.setdefault(player_id, []).append(contract)
        else:
            contract.team_id = team.id
            contract.is_active = True
            for other_contract in active_contracts:
                if other_contract is not contract:
                    other_contract.is_active = False

        player = next(player for player in players if player.id == player_id)
        player.role = expected_role_by_player[player_id]

    for seed_team in seed_teams:
        team = teams_by_name[seed_team["team"]]
        team.region = seed_team["region"]

    await session.flush()
    return True


async def ensure_regional_fixtures(
    save: MobaGameSave,
    team: MobaTeam,
    session: AsyncSession,
) -> bool:
    """Keep a career schedule within the managed team's region."""
    fixtures_result = await session.execute(
        select(MobaCareerFixture)
        .where(MobaCareerFixture.save_id == save.id)
        .order_by(MobaCareerFixture.match_day, MobaCareerFixture.id)
    )
    fixtures = fixtures_result.scalars().all()
    opponents_result = await session.execute(
        select(MobaTeam)
        .where(
            MobaTeam.id != team.id,
            MobaTeam.region == team.region,
        )
        .order_by(MobaTeam.id)
    )
    opponents = opponents_result.scalars().all()
    regional_opponent_ids = {opponent.id for opponent in opponents}
    represented_opponents: set[int] = set()
    changed = False
    for fixture in fixtures:
        if (
            fixture.status == "scheduled"
            and fixture.match_id is None
            and fixture.opponent_team_id not in regional_opponent_ids
        ):
            await session.delete(fixture)
            changed = True
        else:
            represented_opponents.add(fixture.opponent_team_id)

    opponents = [
        opponent for opponent in opponents if opponent.id not in represented_opponents
    ]
    for week, opponent in enumerate(opponents, start=1):
        session.add(
            MobaCareerFixture(
                save_id=save.id,
                opponent_team_id=opponent.id,
                match_day=save.current_day + timedelta(days=week * 7),
            )
        )
        changed = True

    return changed


@career_routes.get("/teams")
async def list_career_teams(
    _: Annotated[MobaGameAccount, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if await reconcile_seed_rosters(session):
        await session.commit()
    result = await session.execute(select(MobaTeam).order_by(MobaTeam.name))
    teams = result.scalars().all()
    team_data = []
    for team in teams:
        team_data.append(
            {
                "id": team.id,
                "name": team.name,
                "region": team.region,
                "logo_path": team.logo_path,
                "average_overall": await _team_roster_average(team.id, session),
            }
        )
    return team_data


@career_routes.post("", status_code=status.HTTP_201_CREATED)
async def start_career(
    payload: StartCareerRequest,
    account: Annotated[MobaGameAccount, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    existing_save = await get_current_save(account, session)
    if existing_save:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account already has an active career.",
        )

    team = await session.get(MobaTeam, payload.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")

    if await reconcile_seed_rosters(session):
        await session.flush()

    average_overall = await _team_roster_average(team.id, session)
    if average_overall >= 80:
        tier, budget, salary_cap = 1, 5_000_000, 1_000_000
    elif average_overall >= 70:
        tier, budget, salary_cap = 2, 2_000_000, 400_000
    else:
        tier, budget, salary_cap = 3, 750_000, 150_000

    save = MobaGameSave(
        account_id=account.id,
        managed_team_id=team.id,
        current_day=date.today(),
        budget=budget,
        salary_cap=salary_cap,
        team_tier=tier,
        updated_at=datetime.now(UTC),
    )
    session.add(save)
    await session.flush()

    await ensure_regional_fixtures(save, team, session)

    await session.commit()
    await session.refresh(save)
    return {
        "id": save.id,
        "team_id": save.managed_team_id,
        "team_name": team.name,
        "current_day": save.current_day.isoformat(),
        "budget": save.budget,
        "salary_cap": save.salary_cap,
        "team_tier": save.team_tier,
    }


@career_routes.get("")
async def current_career(
    account: Annotated[MobaGameAccount, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    save = await get_current_save(account, session)
    if not save:
        return None
    team = await session.get(MobaTeam, save.managed_team_id)
    if team and await ensure_regional_fixtures(save, team, session):
        await session.commit()
    fixture_result = await session.execute(
        select(MobaCareerFixture).where(
            MobaCareerFixture.save_id == save.id,
            MobaCareerFixture.match_day == save.current_day,
            MobaCareerFixture.status != "completed",
        )
    )
    today_fixture = fixture_result.scalars().first()
    fixture = None
    if today_fixture:
        opponent = await session.get(MobaTeam, today_fixture.opponent_team_id)
        fixture = {
            "id": today_fixture.id,
            "match_day": today_fixture.match_day.isoformat(),
            "status": today_fixture.status,
            "match_id": today_fixture.match_id,
            "opponent": {
                "id": opponent.id,
                "name": opponent.name,
            }
            if opponent
            else None,
        }
    return {
        "id": save.id,
        "team_id": save.managed_team_id,
        "team_name": team.name if team else None,
        "current_day": save.current_day.isoformat(),
        "budget": save.budget,
        "salary_cap": save.salary_cap,
        "team_tier": save.team_tier,
        "wins": save.wins,
        "losses": save.losses,
        "standings_points": save.standings_points,
        "today_fixture": fixture,
        "next_action": "NEXT MATCH" if today_fixture else "NEXT DAY",
    }


@career_routes.post("/advance-day")
async def advance_career_day(
    account: Annotated[MobaGameAccount, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    save = await get_current_save(account, session)
    if not save:
        raise HTTPException(status_code=404, detail="No active career.")

    fixture_result = await session.execute(
        select(MobaCareerFixture).where(
            MobaCareerFixture.save_id == save.id,
            MobaCareerFixture.match_day == save.current_day,
            MobaCareerFixture.status != "completed",
        )
    )
    fixture = fixture_result.scalars().first()
    if fixture:
        raise HTTPException(
            status_code=409,
            detail="Play or complete today's scheduled match before advancing.",
        )

    payroll_result = await session.execute(
        select(func.coalesce(func.sum(MobaPlayerContract.salary), 0)).where(
            MobaPlayerContract.team_id == save.managed_team_id,
            MobaPlayerContract.is_active.is_(True),
        )
    )
    monthly_payroll = int(payroll_result.scalar() or 0)
    daily_payroll = (monthly_payroll + 29) // 30
    save.budget -= daily_payroll
    save.current_day += timedelta(days=1)
    save.updated_at = datetime.now(UTC)
    await session.commit()
    return {
        "current_day": save.current_day.isoformat(),
        "daily_payroll": daily_payroll,
        "budget": save.budget,
    }


@career_routes.post("/next-match")
async def start_next_match(
    account: Annotated[MobaGameAccount, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    save = await get_current_save(account, session)
    if not save:
        raise HTTPException(status_code=404, detail="No active career.")

    fixture_result = await session.execute(
        select(MobaCareerFixture).where(
            MobaCareerFixture.save_id == save.id,
            MobaCareerFixture.match_day == save.current_day,
            MobaCareerFixture.status != "completed",
        )
    )
    fixture = fixture_result.scalars().first()
    if not fixture:
        raise HTTPException(
            status_code=409, detail="There is no match scheduled today."
        )
    if fixture.match_id:
        return {
            "match_id": fixture.match_id,
            "lineup_url": f"/api/moba/lineup/match/{fixture.match_id}",
        }

    match = MobaMatch(
        blue_team_id=save.managed_team_id,
        red_team_id=fixture.opponent_team_id,
        status=MobaMatchStatus.NOT_STARTED,
        format=MobaMatchFormat.BO3,
        start_time=datetime.combine(fixture.match_day, time(17), tzinfo=UTC),
    )
    session.add(match)
    await session.flush()
    fixture.match_id = match.id
    fixture.status = "in_progress"
    await session.commit()
    return {
        "match_id": match.id,
        "lineup_url": f"/api/moba/lineup/match/{match.id}",
    }
