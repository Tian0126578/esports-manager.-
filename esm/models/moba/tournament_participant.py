# SPDX-FileCopyrightText: 2025 Pedrenrique G. Guimarães <admin@esportsmanager.net>
# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Column, DateTime


class MobaTournamentParticipant(SQLModel, table=True):
    __tablename__ = "moba_tournament_participants"

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="moba_tournaments.id", index=True)
    team_id: int = Field(foreign_key="moba_teams.id", index=True)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
