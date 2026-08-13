from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, detect_capabilities, load_settings
from app.logging import log_event
logger = logging.getLogger(__name__)


@asynccontextmanager
async def controller_lifespan(app: FastAPI):
    log_event(logger, "controller_started")
    yield
    log_event(logger, "controller_stopped")


def create_app(
    *,
    settings: Settings | None = None,
    capabilities: Mapping[str, bool] | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    resolved_capabilities = dict(capabilities or detect_capabilities(resolved_settings))

    app = FastAPI(title="PC TV Controller", version="0.1.0", lifespan=controller_lifespan)
    app.state.settings = resolved_settings
    app.state.capabilities = resolved_capabilities

    @app.get("/api/health")
    async def health() -> dict[str, bool | str]:
        return {
            "status": "ok",
            "backend": True,
            "frontend": False,
            "brave_available": bool(app.state.capabilities.get("brave_available", False)),
            "edge_available": bool(app.state.capabilities.get("edge_available", False)),
            "mpv_available": bool(app.state.capabilities.get("mpv_available", False)),
        }

    return app


app = create_app()
