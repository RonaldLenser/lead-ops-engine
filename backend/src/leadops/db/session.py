"""Database engine and session factory.

The engine owns a pool of open connections (opening one per request is slow).
A session is a short-lived unit of work borrowed from that pool.

Creating the engine does not connect. The app therefore starts even when the
database is down, and /readyz reports it instead of the process crashing.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from leadops.config import Settings


def create_engine(settings: Settings, application_name: str = "leadops-api") -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,  # detect dead connections (for example after a DB restart)
        echo=settings.db_echo,
        connect_args={
            "timeout": settings.db_connect_timeout_seconds,
            # Shows up in pg_stat_activity, so you can tell the API from the worker later.
            "server_settings": {"application_name": application_name},
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay readable after commit. Async code needs
    # this because reloading an expired attribute would be a hidden database call.
    return async_sessionmaker(engine, expire_on_commit=False)
