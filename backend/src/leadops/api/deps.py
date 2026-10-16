"""FastAPI dependencies: shared resources handed to route functions.

Routes declare what they need (for example `engine: EngineDep`) and FastAPI
provides it. Tests can override any dependency.
"""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from leadops.api.client_ip import client_ip
from leadops.api.rate_limit import TokenBucketLimiter
from leadops.config import Settings
from leadops.errors import RateLimitedError


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


def get_client_ip(request: Request, settings: SettingsDep) -> str:
    return client_ip(request, settings.trusted_proxy_networks)


ClientIpDep = Annotated[str, Depends(get_client_ip)]


def enforce_rate_limit(request: Request, limiter_name: str, identity: str) -> None:
    limiter: TokenBucketLimiter = request.app.state.rate_limiters[limiter_name]
    decision = limiter.hit(identity)
    if not decision.allowed:
        raise RateLimitedError(decision.retry_after_seconds)


def limit_intake_by_ip(request: Request, ip: ClientIpDep) -> None:
    """Runs before authentication, so it also slows down API-key guessing."""
    enforce_rate_limit(request, "intake_ip", ip)
