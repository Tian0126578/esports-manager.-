# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
import os
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from esm.db import get_session
from esm.models.moba.career import MobaGameAccount, MobaLoginSession
from esm.services.authentication import (
    create_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)

auth_routes = APIRouter(prefix="/auth", tags=["authentication"])

SESSION_COOKIE = "esm_session"
SESSION_DURATION_SECONDS = 30 * 24 * 60 * 60


class AccountCredentials(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    password: str = Field(min_length=12, max_length=128)


def _set_session_cookie(response: Response, token: str) -> None:
    secure_cookie = os.getenv("ESM_COOKIE_SECURE", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DURATION_SECONDS,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        path="/",
    )


async def get_current_account(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MobaGameAccount:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to access your game.",
        )

    result = await session.execute(
        select(MobaLoginSession).where(
            MobaLoginSession.token_hash == hash_session_token(token),
            MobaLoginSession.expires_at > int(time.time()),
        )
    )
    login_session = result.scalars().first()
    account = (
        await session.get(MobaGameAccount, login_session.account_id)
        if login_session
        else None
    )
    if not account:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Sign in again.",
        )
    return account


async def _issue_session(
    account: MobaGameAccount,
    response: Response,
    session: AsyncSession,
) -> dict[str, int | str]:
    token = create_session_token()
    session.add(
        MobaLoginSession(
            account_id=account.id,
            token_hash=hash_session_token(token),
            expires_at=int(time.time()) + SESSION_DURATION_SECONDS,
        )
    )
    await session.commit()
    _set_session_cookie(response, token)
    return {"id": account.id, "username": account.username}


@auth_routes.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    credentials: AccountCredentials,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    username = credentials.username.lower()
    existing = await session.execute(
        select(MobaGameAccount).where(MobaGameAccount.username == username)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Username is already in use.")

    account = MobaGameAccount(
        username=username,
        password_hash=hash_password(credentials.password),
    )
    session.add(account)
    try:
        await session.flush()
        result = await _issue_session(account, response, session)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Username is already in use."
        ) from exc
    return result


@auth_routes.post("/login")
async def login(
    credentials: AccountCredentials,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    username = credentials.username.lower()
    result = await session.execute(
        select(MobaGameAccount).where(MobaGameAccount.username == username)
    )
    account = result.scalars().first()
    if not account or not verify_password(
        credentials.password, account.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    return await _issue_session(account, response, session)


@auth_routes.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        result = await session.execute(
            select(MobaLoginSession).where(
                MobaLoginSession.token_hash == hash_session_token(token)
            )
        )
        login_session = result.scalars().first()
        if login_session:
            await session.delete(login_session)
            await session.commit()
    response.delete_cookie(
        SESSION_COOKIE, httponly=True, secure=_cookie_is_secure(), samesite="lax"
    )


def _cookie_is_secure() -> bool:
    return os.getenv("ESM_COOKIE_SECURE", "false").lower() in {
        "1",
        "true",
        "yes",
    }
