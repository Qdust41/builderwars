"""FastAPI app factory.

Run locally:  uv run uvicorn api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.dependencies import build_container
from api.routes import devices, events, health, jobs, projects, sessions
from api.settings import Settings
from domain.common import InvalidStateTransitionError, NotFoundError, PermissionDeniedError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Builderwars Platform API", version="0.1.0")
    app.state.container = build_container(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Dev-User"],
    )

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)

    @app.exception_handler(PermissionDeniedError)
    async def _forbidden(_: Request, exc: PermissionDeniedError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_403_FORBIDDEN)

    @app.exception_handler(InvalidStateTransitionError)
    async def _conflict(_: Request, exc: InvalidStateTransitionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_409_CONFLICT)

    for router in (
        health.router,
        projects.router,
        devices.router,
        sessions.router,
        events.router,
        jobs.router,
    ):
        app.include_router(router)
    return app


app = create_app()
