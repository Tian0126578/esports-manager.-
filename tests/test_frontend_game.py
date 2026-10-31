# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
from collections.abc import AsyncGenerator
from datetime import date

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from esm.app import create_api
from esm.db import get_session
from esm.models.moba.career import MobaGameAccount, MobaGameSave
from esm.models.moba.player import MobaPlayer, MobaPlayerRole
from esm.models.moba.player_contract import MobaPlayerContract
from esm.models.moba.team import MobaTeam
from frontend import create_frontend


async def test_account_can_choose_a_team_and_open_its_home_page():
    app = create_frontend(create_api(lifespan=None))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    async with session_factory() as session:
        team = MobaTeam(name="GAM Esports", region="VCS")
        other_team = MobaTeam(name="T1", region="LCK")
        session.add_all([team, other_team])
        await session.commit()
        await session.refresh(team)
        await session.refresh(other_team)

        for index, role in enumerate(MobaPlayerRole):
            player = MobaPlayer(
                first_name=f"GAM{index}",
                last_name="Player",
                nick_name=f"GAM_{role.value}",
                role=role,
            )
            session.add(player)
            await session.flush()
            session.add(
                MobaPlayerContract(
                    player_id=player.id,
                    team_id=team.id,
                    start_date=date(2026, 1, 1),
                    end_date=date(2027, 1, 1),
                    salary=1000,
                    is_active=True,
                )
            )

        unrelated_player = MobaPlayer(
            first_name="T1",
            last_name="Player",
            nick_name="T1_Faker",
            role=MobaPlayerRole.MID,
        )
        session.add(unrelated_player)
        await session.flush()
        session.add(
            MobaPlayerContract(
                player_id=unrelated_player.id,
                team_id=other_team.id,
                start_date=date(2026, 1, 1),
                end_date=date(2027, 1, 1),
                salary=1000,
                is_active=True,
            )
        )
        await session.commit()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=True,
        ) as client:
            register_response = await client.post(
                "/api/auth/register",
                json={
                    "username": "new_manager",
                    "password": "secure-password-2026",
                },
            )
            assert register_response.status_code == 201

            picker_response = await client.get("/new-game")
            assert picker_response.status_code == 200

            teams = await client.get("/api/career/teams")
            team_id = teams.json()[0]["id"]
            career_response = await client.post(
                "/api/career", json={"team_id": team_id}
            )
            assert career_response.status_code == 201

            home_response = await client.get("/home")
            assert home_response.status_code == 200
            assert "GAM Esports" in home_response.text
            assert "G2 Esports" not in home_response.text
            assert "GAM_top" in home_response.text
            assert "GAM_jungle" in home_response.text
            assert "VCS League standings" in home_response.text
            assert "Karmine Corp" not in home_response.text

            roster_response = await client.get("/page/roster")
            assert roster_response.status_code == 200
            assert "GAM Esports" in roster_response.text
            assert "GAM_top" in roster_response.text
            assert "GAM_jungle" in roster_response.text
            assert "GAM_mid" in roster_response.text
            assert "GAM_adc" in roster_response.text
            assert "GAM_support" in roster_response.text
            assert "T1_Faker" not in roster_response.text
            assert "Fnatic" not in roster_response.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_roster_page_returns_a_clear_json_error_when_roster_table_is_missing():
    app = create_frontend(create_api(lifespan=None))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with session_factory() as session:
            team = MobaTeam(name="T1", region="LCK")
            session.add(team)
            await session.commit()
            await session.refresh(team)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=True,
        ) as client:
            registration = await client.post(
                "/api/auth/register",
                json={
                    "username": "roster_error_coach",
                    "password": "secure-password-2026",
                },
            )
            assert registration.status_code == 201

            async with session_factory() as session:
                account_result = await session.execute(
                    select(MobaGameAccount).where(
                        MobaGameAccount.username == "roster_error_coach"
                    )
                )
                account = account_result.scalars().one()
                session.add(
                    MobaGameSave(
                        account_id=account.id,
                        managed_team_id=team.id,
                        current_day=date(2026, 1, 1),
                    )
                )
                await session.commit()
                await session.execute(text("DROP TABLE moba_player_contracts"))
                await session.commit()

            response = await client.get("/page/roster")

            assert response.status_code == 500
            assert response.json() == {
                "detail": (
                    "Roster data could not be loaded because of a database error."
                )
            }
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
