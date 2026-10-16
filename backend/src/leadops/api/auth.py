"""API-key authentication and scope checks for machine clients.

    Authorization: Bearer lok_<prefix>_<secret>

1. Parse the prefix (public) from the presented key.
2. Look up the key row by prefix.
3. Compare SHA-256(presented) with the stored digest in constant time. When
   no row exists, a dummy digest is compared anyway, so an unknown prefix
   costs the same time as a wrong secret.
4. Revoked keys fail exactly like wrong keys (same 401, same message).
5. A valid key without the route's scope gets 403.

The full key is never logged: only the prefix appears in logs, and the log
masker redacts anything shaped like a key as a second line of defense.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from leadops.api.deps import SessionFactoryDep
from leadops.db import repositories as repo
from leadops.errors import AuthenticationError, PermissionDeniedError
from leadops.security.api_keys import Scope, digest_matches, parse_prefix

logger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=False, description="API key: Bearer lok_<prefix>_<secret>")
_DUMMY_DIGEST = bytes(32)


@dataclass(frozen=True)
class AuthenticatedKey:
    id: uuid.UUID
    name: str
    prefix: str
    scopes: frozenset[str]


def require_api_key(scope: Scope) -> Callable[..., Awaitable[AuthenticatedKey]]:
    async def dependency(
        request: Request,
        session_factory: SessionFactoryDep,
        credentials: HTTPAuthorizationCredentials | None = Security(_bearer),  # noqa: B008
    ) -> AuthenticatedKey:
        if credentials is None:
            raise AuthenticationError()
        presented = credentials.credentials
        prefix = parse_prefix(presented)

        async with session_factory() as session:
            stored = await repo.find_api_key_by_prefix(session, prefix) if prefix else None
            valid = digest_matches(presented, stored.key_sha256 if stored else _DUMMY_DIGEST)
            if stored is None or not valid or stored.revoked_at is not None:
                logger.warning("api_key_rejected", key_prefix=prefix, path=request.url.path)
                raise AuthenticationError()
            if scope.value not in stored.scopes:
                logger.warning("api_key_missing_scope", key_prefix=prefix, scope=scope.value)
                raise PermissionDeniedError(f"API key lacks the {scope.value} scope")
            await repo.touch_api_key(session, stored.id)
            await session.commit()

        structlog.contextvars.bind_contextvars(api_key_prefix=stored.prefix)
        return AuthenticatedKey(
            id=stored.id, name=stored.name, prefix=stored.prefix, scopes=frozenset(stored.scopes)
        )

    return dependency
