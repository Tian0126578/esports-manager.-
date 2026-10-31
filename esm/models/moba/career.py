# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
from datetime import UTC, date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class MobaGameAccount(SQLModel, table=True):
    __tablename__ = "moba_game_accounts"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=32)
    password_hash: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class MobaLoginSession(SQLModel, table=True):
    __tablename__ = "moba_login_sessions"

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="moba_game_accounts.id", index=True)
    token_hash: str = Field(index=True, unique=True, max_length=64)
    expires_at: int = Field(index=True)


class MobaGameSave(SQLModel, table=True):
    __tablename__ = "moba_game_saves"

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(
        foreign_key="moba_game_accounts.id", index=True, unique=True
    )
    managed_team_id: int = Field(foreign_key="moba_teams.id")
    current_day: date = Field(default_factory=date.today)
    budget: int = Field(default=750_000)
    salary_cap: int = Field(default=150_000)
    team_tier: int = Field(default=3, ge=1, le=3)
    wins: int = Field(default=0, ge=0)
    losses: int = Field(default=0, ge=0)
    standings_points: int = Field(default=0, ge=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class MobaCareerFixture(SQLModel, table=True):
    __tablename__ = "moba_career_fixtures"
    __table_args__ = (
        UniqueConstraint("save_id", "match_day", name="unique_career_match_day"),
    )

    id: int | None = Field(default=None, primary_key=True)
    save_id: int = Field(foreign_key="moba_game_saves.id", index=True)
    opponent_team_id: int = Field(foreign_key="moba_teams.id")
    match_day: date = Field(index=True)
    match_id: int | None = Field(default=None, foreign_key="moba_games.id")
    status: str = Field(default="scheduled", max_length=16)
