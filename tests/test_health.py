# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
from httpx import AsyncClient
from sqlalchemy import text

from esm import db
from esm.db import DatabaseManager


async def test_health_reports_database_readiness(client: AsyncClient, monkeypatch):
    manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(db, "db_manager", manager)

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    await manager.engine.dispose()


async def test_health_fails_when_database_is_not_initialized(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(db, "db_manager", None)

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not initialized"


async def test_existing_career_database_adds_standings_columns():
    manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    async with manager.engine.begin() as connection:
        await connection.execute(
            text(
                """
                CREATE TABLE moba_game_saves (
                    id INTEGER PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    managed_team_id INTEGER NOT NULL,
                    current_day DATE NOT NULL,
                    budget INTEGER NOT NULL,
                    salary_cap INTEGER NOT NULL,
                    team_tier INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )

    await manager.create_db_and_tables()
    async with manager.engine.connect() as connection:
        result = await connection.execute(text("PRAGMA table_info(moba_game_saves)"))
        column_names = {row[1] for row in result.fetchall()}

    assert {"wins", "losses", "standings_points"} <= column_names
    await manager.engine.dispose()
