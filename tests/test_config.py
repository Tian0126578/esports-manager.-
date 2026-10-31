# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
import json

from esm import config as config_module
from esm.config import Config


def test_environment_values_override_config_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "database_url": "sqlite:///local.db",
                "port": 8000,
                "api_url": "http://localhost:8000",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "ESM_DIR", tmp_path)
    monkeypatch.setenv("ESM_DATABASE_URL", "sqlite+aiosqlite:////data/game.db")
    monkeypatch.setenv("ESM_PORT", "9000")
    monkeypatch.setenv("ESM_API_URL", "https://game.example.test")

    config = Config()
    config.load_config()

    assert config.database_url == "sqlite+aiosqlite:////data/game.db"
    assert config.port == 9000
    assert config.api_url == "https://game.example.test"
