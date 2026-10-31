# SPDX-FileCopyrightText: 2025 Pedrenrique G. Guimarães <admin@esportsmanager.net>
# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
import logging
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from esm.config import FRONTEND_DIR
from esm.db import get_session
from esm.models.moba.career import MobaCareerFixture, MobaGameAccount
from esm.models.moba.moba_match import MobaMatch, MobaMatchResult
from esm.models.moba.player import MobaPlayer, MobaPlayerRole
from esm.models.moba.player_contract import MobaPlayerContract
from esm.models.moba.team import MobaTeam
from esm.routes.auth import get_current_account
from esm.routes.career import (
    ensure_regional_fixtures,
    get_current_save,
    reconcile_seed_rosters,
)
from frontend.sidebar import sidebar

static_dir = FRONTEND_DIR / "static"
templates_dir = FRONTEND_DIR / "templates"
logger = logging.getLogger(__name__)


def create_frontend(app: FastAPI) -> FastAPI:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    templates = Jinja2Templates(directory=templates_dir)

    @app.get("/")
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {"request": request})

    @app.get("/home")
    async def home(
        request: Request,
        account: Annotated[MobaGameAccount, Depends(get_current_account)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ):
        global current_page
        save = await get_current_save(account, session)
        if not save:
            return RedirectResponse("/new-game", status_code=303)
        managed_team = await session.get(MobaTeam, save.managed_team_id)
        if not managed_team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Your career team no longer exists.",
            )
        roster_repaired = await reconcile_seed_rosters(session)
        schedule_repaired = await ensure_regional_fixtures(save, managed_team, session)
        if roster_repaired or schedule_repaired:
            await session.commit()

        region_teams_result = await session.execute(
            select(MobaTeam)
            .where(MobaTeam.region == managed_team.region)
            .order_by(MobaTeam.name)
        )
        region_teams = region_teams_result.scalars().all()
        team_ids = [team.id for team in region_teams]
        roster_result = await session.execute(
            select(MobaPlayer, MobaPlayerContract)
            .join(
                MobaPlayerContract,
                MobaPlayerContract.player_id == MobaPlayer.id,
            )
            .where(
                MobaPlayerContract.team_id.in_(team_ids),
                MobaPlayerContract.is_active.is_(True),
            )
        )
        role_order = {
            role: index
            for index, role in enumerate(
                (
                    MobaPlayerRole.TOP,
                    MobaPlayerRole.JUNGLE,
                    MobaPlayerRole.MID,
                    MobaPlayerRole.ADC,
                    MobaPlayerRole.SUPPORT,
                )
            )
        }
        team_rosters: dict[int, list[dict]] = {
            team.id: [] for team in region_teams if team.id is not None
        }
        for player, contract in roster_result.all():
            team_rosters.setdefault(contract.team_id, []).append(
                {
                    "player": player,
                    "contract": contract,
                    "image_url": (
                        f"/api/moba/players/images/{Path(player.image_path).name}"
                        if player.image_path
                        else None
                    ),
                }
            )
        for roster in team_rosters.values():
            roster.sort(
                key=lambda entry: role_order.get(entry["player"].role, len(role_order))
            )

        standings_by_team = {
            team.id: {
                "team": team,
                "wins": 0,
                "losses": 0,
                "points": 0,
                "overall": (
                    sum(entry["player"].overall for entry in team_rosters[team.id])
                    // len(team_rosters[team.id])
                    if team_rosters[team.id]
                    else 0
                ),
            }
            for team in region_teams
            if team.id is not None
        }
        managed_standing = standings_by_team[managed_team.id]
        managed_standing.update(
            wins=save.wins,
            losses=save.losses,
            points=save.standings_points,
        )
        completed_fixtures_result = await session.execute(
            select(MobaCareerFixture, MobaMatch)
            .join(MobaMatch, MobaMatch.id == MobaCareerFixture.match_id)
            .where(
                MobaCareerFixture.save_id == save.id,
                MobaCareerFixture.status == "completed",
            )
            .order_by(MobaCareerFixture.match_day.desc())
        )
        recent_match = None
        for fixture, match in completed_fixtures_result.all():
            opponent = standings_by_team.get(fixture.opponent_team_id)
            if opponent:
                managed_won = (
                    match.result == MobaMatchResult.BLUE_WIN
                    if match.blue_team_id == managed_team.id
                    else match.result == MobaMatchResult.RED_WIN
                )
                if managed_won:
                    opponent["losses"] += 1
                else:
                    opponent["wins"] += 1
                    opponent["points"] += 3
            if recent_match is None:
                opponent_team = await session.get(MobaTeam, fixture.opponent_team_id)
                recent_match = {
                    "opponent": opponent_team.name if opponent_team else "Unknown team",
                    "result": (
                        "W"
                        if (
                            match.result == MobaMatchResult.BLUE_WIN
                            if match.blue_team_id == managed_team.id
                            else match.result == MobaMatchResult.RED_WIN
                        )
                        else "L"
                    ),
                    "date": fixture.match_day.isoformat(),
                }
        standings = sorted(
            standings_by_team.values(),
            key=lambda row: (
                -row["points"],
                -row["wins"],
                -row["overall"],
                row["team"].name.casefold(),
            ),
        )
        for position, row in enumerate(standings, start=1):
            row["position"] = position
        managed_position = managed_standing["position"]
        roster = team_rosters.get(managed_team.id, [])
        monthly_payroll = sum(entry["contract"].salary for entry in roster)
        league_name = (
            f"{managed_team.region} League"
            if managed_team.region
            else "Independent League"
        )
        current_page = "home"
        contentview = "pages/career_dashboard.html"
        return templates.TemplateResponse(
            request,
            "layout.html",
            {
                "request": request,
                "content": contentview,
                "sidebar": sidebar,
                "current_page": current_page,
                "managed_team": managed_team,
                "game_date": save.current_day.isoformat(),
                "career_save": save,
                "roster": roster,
                "standings": standings,
                "managed_position": managed_position,
                "league_name": league_name,
                "recent_match": recent_match,
                "monthly_payroll": monthly_payroll,
                "win_rate": (
                    round(save.wins * 100 / (save.wins + save.losses))
                    if save.wins + save.losses
                    else 0
                ),
            },
        )

    @app.get("/page/{page}")
    async def page(
        request: Request,
        page: str,
        session: Annotated[AsyncSession, Depends(get_session)],
    ):
        global current_page
        if page == "home":
            return RedirectResponse("/home", status_code=303)
        current_page = page
        contentview = f"pages/{current_page}.html"
        context = {
            "request": request,
            "content": contentview,
            "sidebar": sidebar,
            "current_page": current_page,
        }

        if page == "roster":
            try:
                account = await get_current_account(request, session)
                save = await get_current_save(account, session)
                if not save:
                    return RedirectResponse("/new-game", status_code=303)

                team = await session.get(MobaTeam, save.managed_team_id)
                if not team:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Your career team no longer exists.",
                    )

                result = await session.execute(
                    select(MobaPlayer, MobaPlayerContract)
                    .join(
                        MobaPlayerContract,
                        MobaPlayerContract.player_id == MobaPlayer.id,
                    )
                    .where(
                        MobaPlayerContract.team_id == team.id,
                        MobaPlayerContract.is_active.is_(True),
                    )
                    .order_by(MobaPlayerContract.player_id)
                )
                players = [
                    {
                        "player": player,
                        "contract": contract,
                        "image_url": (
                            f"/api/moba/players/images/{Path(player.image_path).name}"
                            if player.image_path
                            else None
                        ),
                    }
                    for player, contract in result.all()
                ]

                role_order = {
                    role: index
                    for index, role in enumerate(
                        (
                            MobaPlayerRole.TOP,
                            MobaPlayerRole.JUNGLE,
                            MobaPlayerRole.MID,
                            MobaPlayerRole.ADC,
                            MobaPlayerRole.SUPPORT,
                        )
                    )
                }
                players.sort(
                    key=lambda item: role_order.get(
                        item["player"].role, len(role_order)
                    )
                )
                context.update(
                    {
                        "content": "pages/managed_roster.html",
                        "managed_team": team,
                        "roster": players,
                        "career_save": save,
                    }
                )
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    return RedirectResponse("/login", status_code=303)
                raise
            except SQLAlchemyError as exc:
                logger.exception("Could not load the current career roster.")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Roster data could not be loaded because of a database error.",
                ) from exc

        return templates.TemplateResponse(
            request,
            "layout.html",
            context,
        )

    from frontend.routes.game import game_pages
    from frontend.routes.player import player_routes
    from frontend.routes.team import team_routes
    from frontend.routes.tournament import tournament_routes

    app.include_router(game_pages)
    app.include_router(player_routes)
    app.include_router(team_routes)
    app.include_router(tournament_routes)

    return app
