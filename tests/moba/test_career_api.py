# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
from datetime import date

import pytest
from sqlalchemy import select

from esm.models.moba.career import MobaCareerFixture, MobaGameSave
from esm.models.moba.player import MobaPlayer, MobaPlayerRole
from esm.models.moba.player_contract import MobaPlayerContract
from esm.models.moba.team import MobaTeam
from esm.routes.career import reconcile_seed_rosters


@pytest.mark.asyncio
async def test_account_can_start_one_career_for_a_selected_team(client, session):
    team = MobaTeam(name="T1", region="LCK")
    session.add(team)
    await session.commit()
    await session.refresh(team)

    response = await client.post(
        "/api/auth/register",
        json={"username": "coach_1", "password": "secure-password-2026"},
    )
    assert response.status_code == 201

    teams_response = await client.get("/api/career/teams")
    assert teams_response.status_code == 200
    assert teams_response.json() == [
        {
            "id": team.id,
            "name": "T1",
            "region": "LCK",
            "logo_path": None,
            "average_overall": 0,
        }
    ]

    career_response = await client.post("/api/career", json={"team_id": team.id})
    assert career_response.status_code == 201
    assert career_response.json()["team_name"] == "T1"
    assert career_response.json()["team_tier"] == 3

    duplicate_response = await client.post("/api/career", json={"team_id": team.id})
    assert duplicate_response.status_code == 409

    save_result = await session.execute(select(MobaGameSave))
    save = save_result.scalars().one()
    assert save.managed_team_id == team.id


@pytest.mark.asyncio
async def test_career_endpoints_require_a_login(client):
    response = await client.get("/api/career")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_and_logout_revoke_the_session(client):
    register_response = await client.post(
        "/api/auth/register",
        json={"username": "coach_2", "password": "secure-password-2026"},
    )
    assert register_response.status_code == 201

    logout_response = await client.post("/api/auth/logout")
    assert logout_response.status_code == 204

    current_response = await client.get("/api/career")
    assert current_response.status_code == 401


@pytest.mark.asyncio
async def test_career_schedule_advances_days_and_starts_due_match(client, session):
    managed_team = MobaTeam(name="Gen.G", region="LCK")
    opponent = MobaTeam(name="T1", region="LCK")
    other_region_team = MobaTeam(name="Karmine Corp", region="LEC")
    session.add_all([managed_team, opponent, other_region_team])
    await session.commit()
    await session.refresh(managed_team)
    await session.refresh(opponent)

    await client.post(
        "/api/auth/register",
        json={"username": "schedule_coach", "password": "secure-password-2026"},
    )
    career_start = await client.post("/api/career", json={"team_id": managed_team.id})
    assert career_start.status_code == 201
    save_result = await session.execute(select(MobaGameSave))
    save = save_result.scalars().one()

    session.add(
        MobaCareerFixture(
            save_id=save.id,
            opponent_team_id=other_region_team.id,
            match_day=date.today().replace(day=1),
        )
    )
    await session.commit()

    starting_career = (await client.get("/api/career")).json()
    assert starting_career["next_action"] == "NEXT DAY"
    fixtures_result = await session.execute(select(MobaCareerFixture))
    fixtures = fixtures_result.scalars().all()
    assert len(fixtures) == 1
    assert fixtures[0].opponent_team_id == opponent.id

    for _ in range(7):
        response = await client.post("/api/career/advance-day")
        assert response.status_code == 200

    due_career = (await client.get("/api/career")).json()
    assert due_career["next_action"] == "NEXT MATCH"
    assert due_career["today_fixture"]["opponent"]["id"] == opponent.id

    match_response = await client.post("/api/career/next-match")
    assert match_response.status_code == 200
    assert match_response.json()["lineup_url"].endswith(
        f"/{match_response.json()['match_id']}"
    )

    duplicate_response = await client.post("/api/career/next-match")
    assert duplicate_response.json()["match_id"] == match_response.json()["match_id"]

    blocked_advance = await client.post("/api/career/advance-day")
    assert blocked_advance.status_code == 409


@pytest.mark.asyncio
async def test_seed_roster_reconciliation_repairs_misassigned_contracts(
    session, tmp_path, monkeypatch
):
    import json

    from esm.routes import career

    seed_teams = []
    teams = []
    for team_name in ("T1", "Gen.G"):
        team = MobaTeam(name=team_name, region="LCK")
        session.add(team)
        teams.append(team)
    await session.commit()
    for team in teams:
        await session.refresh(team)

    roles = list(MobaPlayerRole)
    players_by_team = {}
    for team in teams:
        seed_players = []
        for role in roles:
            ign = f"{team.name.replace('.', '')}_{role.value}"
            player = MobaPlayer(
                first_name=ign,
                last_name="Player",
                nick_name=ign,
                role=role,
            )
            session.add(player)
            await session.flush()
            players_by_team.setdefault(team.name, []).append(player)
            seed_players.append({"ign": ign, "role": role.value})
        seed_teams.append({"team": team.name, "region": "LCK", "players": seed_players})
    for player in players_by_team["T1"]:
        session.add(
            MobaPlayerContract(
                player_id=player.id,
                team_id=teams[1].id,
                start_date=date(2026, 1, 1),
                end_date=date(2027, 1, 1),
                salary=1000,
                is_active=True,
            )
        )
    for player in players_by_team["Gen.G"]:
        session.add(
            MobaPlayerContract(
                player_id=player.id,
                team_id=teams[0].id,
                start_date=date(2026, 1, 1),
                end_date=date(2027, 1, 1),
                salary=1000,
                is_active=True,
            )
        )
    await session.commit()

    roster_file = tmp_path / "roster.json"
    roster_file.write_text(json.dumps(seed_teams), encoding="utf-8")
    monkeypatch.setattr(career, "SEED_ROSTER_FILE", roster_file)

    changed = await reconcile_seed_rosters(session)
    await session.commit()

    assert changed
    for team in teams:
        result = await session.execute(
            select(MobaPlayer.nick_name)
            .join(
                MobaPlayerContract,
                MobaPlayerContract.player_id == MobaPlayer.id,
            )
            .where(
                MobaPlayerContract.team_id == team.id,
                MobaPlayerContract.is_active.is_(True),
            )
        )
        assert set(result.scalars().all()) == {
            player.nick_name for player in players_by_team[team.name]
        }
