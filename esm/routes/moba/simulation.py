# SPDX-FileCopyrightText: 2025 Pedrenrique G. Guimarães <admin@esportsmanager.net>
# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from esm import db as db_module
from esm.config import FRONTEND_DIR
from esm.db import get_session
from esm.models.moba.career import MobaCareerFixture, MobaGameAccount, MobaGameSave
from esm.models.moba.champion import MobaChampion
from esm.models.moba.moba_match import (
    MobaMatch,
    MobaMatchResult,
)
from esm.models.moba.moba_match_simulation import (
    MobaMatchSimulation,
    MobaMatchStatus,
)
from esm.models.moba.player import MobaPlayer, MobaPlayerRole
from esm.models.moba.player_simulation import MobaPlayerSimulation
from esm.models.moba.team import MobaTeam
from esm.models.moba.team_simulation import MobaTeamSimulation
from esm.routes.auth import get_current_account
from frontend.sidebar import sidebar

logger = logging.getLogger(__name__)

simulation_routes = APIRouter(
    prefix="/simulation",
    tags=["moba_simulation"],
    responses={404: {"description": "Simulation not found"}},
)

templates_dir = FRONTEND_DIR / "templates"
templates = Jinja2Templates(directory=templates_dir)


@dataclass
class SimulationSession:
    sim_id: str
    simulation: MobaMatchSimulation
    match_id: int | None = None
    result_persisted: bool = False
    paused: bool = False
    speed: float = 1.0
    task: asyncio.Task | None = None


_SIMULATIONS: dict[str, SimulationSession] = {}
_BASE_TICK_SECONDS = 0.5


async def _run_simulation_loop(sess: SimulationSession):
    try:
        while sess.simulation.state.status != MobaMatchStatus.COMPLETED:
            if sess.paused:
                await asyncio.sleep(0.1)
                continue
            # Step the simulation
            sess.simulation.step()
            # Sleep based on speed multiplier
            sleep_for = max(0.05, _BASE_TICK_SECONDS / max(0.25, sess.speed))
            await asyncio.sleep(sleep_for)
        if sess.simulation.state.status == MobaMatchStatus.COMPLETED:
            await _persist_match_result(sess)
    except Exception:
        logger.exception("Simulation %s failed", sess.sim_id)
        sess.paused = True


async def _persist_match_result(sess: SimulationSession) -> None:
    if sess.match_id is None or sess.result_persisted:
        return
    manager = db_module.db_manager
    if manager is None:
        logger.error("Cannot persist match %s without an initialized database", sess.match_id)
        return

    async with manager.async_session_maker() as session:
        match = await session.get(MobaMatch, sess.match_id)
        fixture_result = await session.execute(
            select(MobaCareerFixture).where(
                MobaCareerFixture.match_id == sess.match_id,
                MobaCareerFixture.status == "in_progress",
            )
        )
        fixture = fixture_result.scalars().first()
        if not match or not fixture:
            logger.error("No active career fixture found for match %s", sess.match_id)
            return

        match.status = MobaMatchStatus.COMPLETED
        match.end_time = datetime.now(UTC)
        winner = sess.simulation.state.winner
        if winner == 1:
            match.result = MobaMatchResult.BLUE_WIN
        elif winner == 2:
            match.result = MobaMatchResult.RED_WIN
        else:
            logger.error("Completed match %s has no winner", sess.match_id)
            return

        save = await session.get(MobaGameSave, fixture.save_id)
        if not save:
            logger.error("No career save found for match %s", sess.match_id)
            return
        if match.result == MobaMatchResult.BLUE_WIN:
            save.wins += 1
            save.standings_points += 3
        else:
            save.losses += 1
        save.updated_at = datetime.now(UTC)
        fixture.status = "completed"
        await session.commit()
        sess.result_persisted = True


def _serialize_simulation(sim: MobaMatchSimulation) -> dict[str, Any]:
    def serialize_team(ts: MobaTeamSimulation) -> dict[str, Any]:
        return {
            "team": {
                "id": ts.team.id,
                "name": ts.team.name,
                "logo_path": getattr(ts.team, "logo_path", None),
            },
            "state": {
                "towers": ts.state.towers.model_dump(),
                "inhibitors": ts.state.inhibitors.model_dump(),
                "dragons": ts.state.dragons,
                "barons": ts.state.barons,
                "grubs": ts.state.grubs,
                "first_blood": ts.state.first_blood,
                "first_tower": ts.state.first_tower,
                "win_probability": ts.state.win_probability,
            },
            "players": [
                {
                    "id": ps.player.id,
                    "name": ps.player.nick_name
                    or f"{ps.player.first_name} {ps.player.last_name}",
                    "role": (ps.role.value if ps.role else None),
                    "champion": {
                        "id": ps.champion.id,
                        "name": ps.champion.name,
                        "image_path": getattr(ps.champion, "image_path", None),
                        "primary_role": getattr(ps.champion, "primary_role", None),
                    },
                    "kills": ps.kills,
                    "deaths": ps.deaths,
                    "assists": ps.assists,
                    "farm": ps.farm,
                    "points": ps.points,
                    "kda": ps.kda,
                    "strength": ps.get_strength(),
                    "score": ps.get_score(),
                }
                for ps in ts.players
            ],
            "summary": {
                "kills": ts.kills,
                "deaths": ts.deaths,
                "assists": ts.assists,
                "kda": ts.kda,
                "points": ts.points,
                "towers_remaining": ts.towers_remaining,
                "inhibitors_exposed": ts.are_inhibitors_exposed,
            },
        }

    return {
        "status": sim.state.status.value,
        "time": sim.state.time,
        "minutes": sim.state.minutes_played,
        "seconds": sim.state.seconds_played,
        "winner": sim.state.winner,
        "team1": serialize_team(sim.team1),
        "team2": serialize_team(sim.team2),
        "commentary": list(sim.commentary_log),
        "enabled_events": [
            {"event": ev.value, "jungle_type": (jt.value if jt else None)}
            for ev, jt in sim.enabled_events
        ],
    }


async def _build_team_sim(
    db: AsyncSession,
    team_id: int,
    roster: list[dict[str, Any]],
) -> MobaTeamSimulation:
    team = await db.get(MobaTeam, team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")
    players: list[MobaPlayerSimulation] = []
    for slot in roster:
        player = await db.get(MobaPlayer, int(slot["player_id"]))
        champion = await db.get(MobaChampion, int(slot["champion_id"]))
        if not player or not champion:
            raise HTTPException(status_code=404, detail="Player or Champion not found")
        role_str = slot.get("role")
        role = None
        if role_str:
            try:
                role = MobaPlayerRole(role_str.lower())
            except ValueError:
                role = None
        ps = MobaPlayerSimulation(player=player, champion=champion, role=role)
        players.append(ps)
    return MobaTeamSimulation(team=team, players=players)


@simulation_routes.post("/create")
async def create_simulation(
    payload: dict[str, Any],
    account: Annotated[MobaGameAccount, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    Create a new simulation session.
    Expected payload:
    {
      "team1_id": int,
      "team2_id": int,
      "team1_roster": [ {"player_id": int, "champion_id": int, "role": "top"|... } x5 ],
      "team2_roster": [ ... ]
    }
    """
    try:
        t1 = await _build_team_sim(
            session, int(payload["team1_id"]), payload["team1_roster"]
        )  # type: ignore[index]
        t2 = await _build_team_sim(
            session, int(payload["team2_id"]), payload["team2_roster"]
        )  # type: ignore[index]
    except KeyError:
        raise HTTPException(status_code=400, detail="Invalid roster payload")

    match_id = payload.get("match_id")
    if match_id is not None:
        match = await session.get(MobaMatch, int(match_id))
        save_result = await session.execute(
            select(MobaGameSave).where(MobaGameSave.account_id == account.id)
        )
        save = save_result.scalars().first()
        fixture_result = await session.execute(
            select(MobaCareerFixture).where(
                MobaCareerFixture.match_id == int(match_id),
                MobaCareerFixture.save_id == (save.id if save else -1),
                MobaCareerFixture.status == "in_progress",
            )
        )
        fixture = fixture_result.scalars().first()
        if (
            not match
            or not save
            or not fixture
            or match.blue_team_id != int(payload["team1_id"])
            or match.red_team_id != int(payload["team2_id"])
        ):
            raise HTTPException(
                status_code=403, detail="Match is not part of your active career."
            )
        match.status = MobaMatchStatus.IN_PROGRESS
        await session.commit()

    sim = MobaMatchSimulation(team1=t1, team2=t2)
    sim.state.update_jungle_objectives()
    sim_id = uuid.uuid4().hex
    sess = SimulationSession(
        sim_id=sim_id,
        simulation=sim,
        match_id=int(match_id) if match_id is not None else None,
    )
    _SIMULATIONS[sim_id] = sess
    return {"sim_id": sim_id}


def _get_session_or_404(sim_id: str) -> SimulationSession:
    sess = _SIMULATIONS.get(sim_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return sess


@simulation_routes.post("/start/{sim_id}")
async def start_simulation(sim_id: str):
    sess = _get_session_or_404(sim_id)
    if sess.simulation.state.status == MobaMatchStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Simulation already ended")
    if sess.task and not sess.task.done():
        # Already running
        return {"status": "already running"}
    sess.paused = False
    # Ensure objectives are initialized
    if not sess.simulation.state.jungle_objectives:
        sess.simulation.state.update_jungle_objectives()
    # Create and start the background loop
    loop = asyncio.get_event_loop()
    sess.task = loop.create_task(_run_simulation_loop(sess))
    # Also start if not started
    if sess.simulation.state.status == MobaMatchStatus.NOT_STARTED:
        sess.simulation.start()
    return {"status": "started"}


@simulation_routes.post("/pause/{sim_id}")
async def pause_simulation(sim_id: str):
    sess = _get_session_or_404(sim_id)
    sess.paused = True
    return {"status": "paused"}


@simulation_routes.post("/resume/{sim_id}")
async def resume_simulation(sim_id: str):
    sess = _get_session_or_404(sim_id)
    sess.paused = False
    if not sess.task or sess.task.done():
        loop = asyncio.get_event_loop()
        sess.task = loop.create_task(_run_simulation_loop(sess))
    return {"status": "resumed"}


@simulation_routes.post("/speed/{sim_id}")
async def set_speed(sim_id: str, speed: float = 1.0):
    sess = _get_session_or_404(sim_id)
    sess.speed = max(0.25, min(8.0, speed))
    return {"speed": sess.speed}


@simulation_routes.get("/state/{sim_id}")
async def get_state(sim_id: str):
    sess = _get_session_or_404(sim_id)
    if sess.simulation.state.status == MobaMatchStatus.COMPLETED:
        await _persist_match_result(sess)
    data = _serialize_simulation(sess.simulation)
    data.update({"paused": sess.paused, "speed": sess.speed, "sim_id": sim_id})
    return data


@simulation_routes.get("/view/{sim_id}")
async def view_simulation(sim_id: str, request: Request):
    _get_session_or_404(sim_id)

    context = {
        "request": request,
        "sim_id": sim_id,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "pages/match_live.html",
            context,
        )

    layout_context = {
        **context,
        "content": "pages/match_live.html",
        "sidebar": sidebar,
        "current_page": "matches",
    }

    return templates.TemplateResponse(
        request,
        "layout.html",
        layout_context,
    )


@simulation_routes.delete("/{sim_id}")
async def delete_simulation(sim_id: str):
    sess = _SIMULATIONS.pop(sim_id, None)
    if not sess:
        raise HTTPException(status_code=404, detail="Simulation not found")
    # cancel background task if running
    if sess.task and not sess.task.done():
        sess.task.cancel()
    return {"status": "deleted"}
