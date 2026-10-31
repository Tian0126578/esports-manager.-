from collections.abc import AsyncGenerator

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


class DatabaseManager:
    def __init__(self, database_url: str):
        # Convert sqlite:/// to sqlite+aiosqlite:///
        if database_url.startswith("sqlite:///"):
            database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")
        
        self.engine = create_async_engine(database_url, echo=True)
        self.async_session_maker = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def create_db_and_tables(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            if conn.dialect.name == "sqlite":
                await conn.run_sync(_migrate_sqlite_game_saves)

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.async_session_maker() as session:
            yield session


db_manager: DatabaseManager = None


def _migrate_sqlite_game_saves(connection):
    columns = {
        column["name"]
        for column in inspect(connection).get_columns("moba_game_saves")
    }
    new_columns = {
        "wins": "INTEGER NOT NULL DEFAULT 0",
        "losses": "INTEGER NOT NULL DEFAULT 0",
        "standings_points": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, column_type in new_columns.items():
        if name not in columns:
            connection.exec_driver_sql(
                f'ALTER TABLE moba_game_saves ADD COLUMN "{name}" {column_type}'
            )


async def get_session():
    if not db_manager:
        raise RuntimeError("Database manager not initialized")
    async for session in db_manager.get_session():
        yield session
