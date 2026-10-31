# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from esm.config import FRONTEND_DIR
from esm.db import get_session
from esm.models.moba.career import MobaGameAccount
from esm.routes.auth import get_current_account
from esm.routes.career import get_current_save

game_pages = APIRouter()
templates = Jinja2Templates(directory=FRONTEND_DIR / "templates")


@game_pages.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(
        request, "account.html", {"request": request, "mode": "login"}
    )


@game_pages.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse(
        request, "account.html", {"request": request, "mode": "register"}
    )


@game_pages.get("/new-game")
async def new_game_page(
    request: Request,
    account: Annotated[MobaGameAccount, Depends(get_current_account)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    save = await get_current_save(account, session)
    if save:
        return RedirectResponse("/home", status_code=303)
    return templates.TemplateResponse(
        request, "new_game.html", {"request": request, "username": account.username}
    )
