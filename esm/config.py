# SPDX-FileCopyrightText: 2025 Pedrenrique G. Guimarães <admin@esportsmanager.net>
# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
ESM_DIR = ROOT_DIR / "esm"
FRONTEND_DIR = ROOT_DIR / "frontend"


@dataclass
class Config:
    database_url: str = ""
    port: int = 0
    api_url: str = ""

    def get_default_config(self) -> dict[str, str | int]:
        port = 8000
        return {
            "database_url": "sqlite+aiosqlite:///" + os.path.join(ESM_DIR, "app.db"),
            "port": port,
            "api_url": "http://localhost:{port}",
        }

    def get_config(self) -> dict[str, str | int]:
        return {
            "database_url": self.database_url,
            "port": self.port,
            "api_url": self.api_url,
        }

    def load_config(self):
        config_path = ESM_DIR / "config.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
        else:
            config = self.get_default_config()

        self.database_url = os.getenv(
            "ESM_DATABASE_URL", config.get("database_url", self.database_url)
        )
        self.port = int(os.getenv("ESM_PORT", config.get("port", self.port)))
        self.api_url = os.getenv(
            "ESM_API_URL", config.get("api_url", self.api_url)
        )

    def save_config(self):
        config_path = ESM_DIR / "config.json"
        with open(config_path, "w") as f:
            json.dump(self.get_config(), f)

    def __str__(self):
        return f"Database URL: {self.database_url}\nPort: {self.port}\nAPI URL: {self.api_url}"
