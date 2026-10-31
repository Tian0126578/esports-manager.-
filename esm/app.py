# SPDX-FileCopyrightText: 2025 Pedrenrique G. Guimarães <admin@esportsmanager.net>
# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from . import db
from .config import Config
from .db import DatabaseManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = Config()
    config.load_config()
    manager = DatabaseManager(config.database_url)
    db.db_manager = manager
    try:
        await manager.create_db_and_tables()
        yield
    finally:
        await manager.engine.dispose()
        db.db_manager = None


def create_api(lifespan: Callable | None = lifespan):
    app = FastAPI(
        title="eSports Manager API",
        description="A free and open source eSports manager game API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["health"])
    async def health_check():
        if db.db_manager is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        try:
            async with db.db_manager.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503, detail="Database is unavailable"
            ) from exc
        return {"status": "ok", "database": "ok"}

    from .routes.auth import auth_routes
    from .routes.career import career_routes
    from .routes.moba import moba_router

    app.include_router(moba_router, prefix="/api")
    app.include_router(auth_routes, prefix="/api")
    app.include_router(career_routes, prefix="/api")

    return app
