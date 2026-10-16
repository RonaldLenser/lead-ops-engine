"""Helpers shared by integration tests: API keys, signed requests, row counts."""

import asyncio
import json
import os
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from leadops.db import repositories as repo
from leadops.db.session import create_session_factory
from leadops.integrations.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, compute_signature
from leadops.security.api_keys import generate_key

ApiKeyFactory = Callable[..., str]


def make_api_key_factory(database_url: str) -> ApiKeyFactory:
    def create(
        name: str = "test-client", scopes: tuple[str, ...] = ("leads:write",), revoked: bool = False
    ) -> str:
        async def insert() -> str:
            key = generate_key()
            engine = create_async_engine(database_url)
            try:
                async with create_session_factory(engine)() as session, session.begin():
                    await repo.insert_api_key(
                        session,
                        name=name,
                        prefix=key.prefix,
                        key_sha256=key.digest,
                        scopes=list(scopes),
                    )
                    if revoked:
                        await repo.revoke_api_key(session, name)
            finally:
                await engine.dispose()
            return key.full_key

        return asyncio.run(insert())

    return create


def bearer(key: str, idempotency_key: str | None = "req-1") -> dict[str, str]:
    headers = {"Authorization": f"Bearer {key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def signed(
    body: dict[str, Any] | bytes, secret: str, timestamp: int | None = None
) -> tuple[bytes, dict[str, str]]:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    ts = int(time.time()) if timestamp is None else timestamp
    return raw, {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: str(ts),
        SIGNATURE_HEADER: compute_signature(secret, ts, raw),
    }


def query(sql: str, database_url: str | None = None) -> list[Any]:
    """Run a read query as the migrator (sees everything) and return rows."""

    async def run() -> list[Any]:
        engine = create_async_engine(database_url or os.environ["MIGRATION_DATABASE_URL"])
        try:
            async with engine.connect() as connection:
                return list((await connection.execute(text(sql))).all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def counts() -> dict[str, int]:
    tables = ("inbound_events", "contacts", "leads", "workflow_runs", "jobs", "audit_events")
    return {table: query(f"SELECT count(*) FROM {table}")[0][0] for table in tables}  # noqa: S608
