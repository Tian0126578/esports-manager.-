<!--
SPDX-FileCopyrightText: 2025 Pedrenrique G. Guimarães <admin@esportsmanager.net>
SPDX-License-Identifier: GPL-3.0-or-later
License-Filename: LICENSES/GPL-3.0-or-later
-->

<div align="center">

![eSports Manager Logo](docs/img/logo.svg)

# eSports Manager

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python version](https://img.shields.io/python/required-version-toml?tomlFilePath=https://raw.githubusercontent.com/esports-manager/esports-manager/develop/pyproject.toml)](https://www.python.org/downloads/)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://GitHub.com/esports-manager/esports-manager/graphs/commit-activity)
[![Last commit](https://img.shields.io/github/last-commit/esports-manager/esports-manager)](https://github.com/esports-manager/esports-manager/commits/develop)
[![GitHub contributors](https://img.shields.io/github/contributors/esports-manager/esports-manager.svg)](https://GitHub.com/esports-manager/esports-manager/graphs/contributors/)

**A free and open source eSports management simulation game**

[Features](#features) • [Screenshots](#screenshots) • [Installation](#installation) • [Getting Started](#getting-started) • [Contributing](#contributing) • [License](#license)

⚠️ **DEVELOPMENT STATUS:** This project is actively being developed and is not yet ready for gameplay. The codebase is currently undergoing significant restructuring. ⚠️

</div>

---

**eSports Manager** is an ambitious free and open source management simulation game, inspired by classic titles like Football Manager and Championship Manager, but focused on the exciting world of competitive gaming.

In eSports Manager, you'll:

- **Manage your own professional eSports team** across various game titles
- **Discover and develop talent** from solo queue and amateur leagues
- **Create strategies** for your team
- **Compete in major leagues and championships** against the world's best teams
- **Handle team finances, sponsorships, and player contracts** to build a sustainable organization
- **Train your squad** with specialized coaching staff and practice regimens
- **Experience matches** through detailed text-based commentary and statistics

The game aims to provide an authentic and deep management experience for eSports enthusiasts and simulation game fans alike.

## Features

### Current Features

- Comprehensive player management system with detailed attributes and statistics
- Team management with finances, facilities, and staff
- Staff management with specialized roles and skill systems
- Match simulation engine with detailed statistics
- Scouting system for discovering talent
- Champions database with role-specific attributes

### Planned Features

- Multiple game titles (MOBA, FPS, etc.) with unique mechanics
- Complete career mode with goals and achievements
- In-depth match tactics and strategy system
- Media interaction and player psychology system
- Custom tournament creation
- Realistic transfer market with negotiations

For a more detailed breakdown of current and planned features, check the [FEATURES.md](FEATURES.md) document.

## Screenshots

The UI is currently being reworked with a modern web-based interface. Here are some previews of the current development state:

<table>
<tr>
<td>
  <img src="docs/img/homepage_screenshot.png" width="300" alt="Home page">
</td>
<td>
  <img src="docs/img/news_page_screenshot.png" width="300" alt="News page">
</td>
</tr>
<tr>
<td>
  <img src="docs/img/player_page_screenshot.png" width="300" alt="Player page">
</td>
<td>
  <img src="docs/img/champions_page_screenshot.png" width="300" alt="Champions page">
</td>
</tr>
</table>


## Installation

### Prerequisites

- Python 3.10 or higher
- Git

### Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/esports-manager/esports-manager.git
   cd esports-manager
   ```

1. **Set up the environment and install dependencies**
   ```bash
   uv venv .venv
   uv sync
   ```

1. **Activate the virtual environment**
   - On Linux/macOS:
     ```bash
     source .venv/bin/activate
     ```
   - On Windows:
     ```bash
     .venv\Scripts\activate
     ```

1. **Initialize the database**
   ```bash
   uv run python scripts/init_db.py
   ```

1. **Run the development server**
   ```bash
   uv run uvicorn dev:app --reload
   ```




For more detailed setup instructions, including troubleshooting tips, refer to the [CONTRIBUTING.md](CONTRIBUTING.md#development-environment-setup) document.

## Getting Started

### Running the Game

To run the main application:
```bash
uv run uvicorn dev:app --host 0.0.0.0 --port 8000
```

Access the web interface at:
- Frontend: http://localhost:8000
- API documentation: http://localhost:8000/docs

### Share a temporary public link

To share the local game over a temporary HTTPS Cloudflare Quick Tunnel:

1. Install `cloudflared` (Windows: `winget install --id Cloudflare.cloudflared`;
   macOS: `brew install cloudflared`; Linux: use the
   [official installation guide](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)).
2. Stop any game server already using port `8000`.
3. Run `uv run python run_public.py` from the project directory.
4. Share the `trycloudflare.com` HTTPS URL printed by the script. Keep the
   terminal open while people are playing; press Ctrl+C to stop both the tunnel
   and web server.

This temporary link is public: anyone who receives it can open the game, and
the tunnel only stays available while your computer and this process are
running. Do not share it for a database containing private or sensitive data.
Cloudflare Quick Tunnels are intended for development/testing, not as a
production hosting service. The server binds to `0.0.0.0:8000` for this launch;
the tunnel connects to its local `127.0.0.1:8000` address.
The project declares Python dependencies in `pyproject.toml` and `uv.lock`;
the launcher uses Python's standard library, so no additional Python tunnel
package or duplicate `requirements.txt` is needed.

### VPS deployment

The web app runs independently of the desktop wrapper. To build and start it with
Docker Compose:

```bash
docker compose up --build -d
```

The first startup seeds the named SQLite volume from the bundled JSON data. The
volume persists the game database across container restarts. The default web
port is `8000`; set `ESM_HTTP_PORT` in the environment to expose another host
port. Set `ESM_COOKIE_SECURE=true` when serving behind HTTPS. Check readiness at
`http://localhost:8000/health`.

For a Linux VPS managed by systemd, install the project at
`/opt/esports-manager`, create the `esports-game` system user, and install its
dependencies with `uv sync --frozen --no-dev`. Initialize the database as that
user with the service's database URL:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin esports-game
cd /opt/esports-manager
uv sync --frozen --no-dev
sudo -u esports-game env ESM_DATABASE_URL=sqlite+aiosqlite:////var/lib/esports-game/app.db \
  /opt/esports-manager/.venv/bin/python /opt/esports-manager/scripts/init_db.py
sudo cp deploy/esports-game.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now esports-game
```

The service listens on `127.0.0.1:8000`; put a TLS-enabled reverse proxy such as
Nginx or Caddy in front of it. Inspect service status with
`sudo systemctl status esports-game` and logs with
`sudo journalctl -u esports-game`.

Web accounts are created from the landing page. Career records are stored per
account, and the session cookie is HTTP-only with a 30-day expiry.

### Syncing the Worlds 2026 roster

The supplied roster is maintained in `scripts/worlds_2026_roster.json`. After setting up the project, apply it to the seed files and configured SQLite database with:

```bash
uv run python scripts/sync_worlds_2026_roster.py
```

The sync validates the 19 teams and 95 players, keeps prior contracts in the database archive, and uses the bundled default avatar when a player portrait is unavailable. Unknown birth dates remain blank.

To generate matching, role-labeled player avatar PNGs locally without any network access, run:

```bash
uv run python scripts/generate_player_placeholders.py
```

The script generates a 300x400 PNG for each of the 95 roster players in
`assets/images/players/`, with the player's IGN and role. It updates
`scripts/players.json` and the configured SQLite database to use the normalized
`ign.png` paths, and records the generated files in
`scripts/generated_player_placeholders.json`. The game serves these files via
the existing `/api/moba/players/images/{filename}` endpoint.

### Development Mode

For frontend development with hot reloading of styles:

```bash
uv run tailwindcss -i frontend/static/css/input.css -o frontend/static/css/tailwind.css --watch
```

```bash
uv run uvicorn dev:app --reload
```

## Contributing

Contributions are welcome and greatly appreciated! eSports Manager is a community-driven project and we value all forms of contributions, from code to documentation, design to testing.

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed information on:
- Code conventions and style
- Development workflow
- Issue reporting
- Pull request process
- Testing guidelines

### Ways to Contribute

- Report bugs or request features using our issue templates
- Improve or expand documentation
- Submit code improvements or new features
- Help test the application
- Share ideas and feedback

## Contact

- **Email**: admin@esportsmanager.net
- **Discussions**: [Discussions](https://github.com/esports-manager/esports-manager/discussions) 
- **[GitHub Issues](https://github.com/esports-manager/esports-manager/issues)**: For bug reports and feature requests

## License

eSports Manager is licensed under the GNU General Public License v3.0 (GPL-3.0).

```
eSports Manager - A free and open source eSports management game
Copyright (C) 2020-2025  Pedrenrique G. Guimarães

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
```

For the full license text, see the [LICENSE.md](LICENSE.md) file.
