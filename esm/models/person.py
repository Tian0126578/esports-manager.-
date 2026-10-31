# SPDX-FileCopyrightText: 2025 Pedrenrique G. Guimarães <admin@esportsmanager.net>
# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
from datetime import date

from sqlmodel import SQLModel


class Person(SQLModel):
    first_name: str
    last_name: str
    date_of_birth: date | None = None
    nick_name: str | None = None
    nationality: str | None = None
    bio: str | None = None
    image_path: str | None = None

    def get_age(self, today: date | None = None) -> int | None:
        if not self.date_of_birth:
            return None
        if today is None:
            today = date.today()
        return (
            today.year
            - self.date_of_birth.year
            - (
                (today.month, today.day)
                < (self.date_of_birth.month, self.date_of_birth.day)
            )
        )
