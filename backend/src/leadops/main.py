"""Application entry point.

create_app() is an app factory: each call builds a fresh, fully configured
FastAPI instance. Tests pass their own Settings to get an isolated app.
Uvicorn calls it with --factory, so nothing (such as reading DATABASE_URL)
happens just because this module was imported.

Run locally (from backend/):
    uv run uvicorn leadops.main:create_app --factory --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from leadops import __version__
from leadops.api.errors import register_error_handlers
from leadops.api.middleware import RequestContextMiddleware
from leadops.api.routes import health
from leadops.config import Settings, get_settings
from leadops.db.session import create_engine, create_session_factory
from leadops.logging_config import configure_logging

logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    # Settings are validated here, before anything else runs: unsafe or missing
    # configuration stops startup with a clear error.
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        logger.info("app_started", env=settings.app_env, version=__version__)
        try:
            yield
        finally:
            await engine.dispose()
            logger.info("app_stopped")

    app = FastAPI(
        title="Lead Ops Engine",
        description="AI lead qualification with human approval.",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    return app
