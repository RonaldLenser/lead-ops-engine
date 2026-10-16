"""Operator command line: `leadops ...` (run on the server, or locally via `uv run leadops`).

    leadops api-keys create --name n8n-intake --scope leads:write
    leadops api-keys list
    leadops api-keys revoke --name n8n-intake

The full key is printed exactly once, by `create`. It is not stored and
cannot be shown again; a lost key is revoked and replaced.

Creation and revocation are written to audit_events (actor: system/cli).
Uses DATABASE_URL like the app: only row access is needed.
"""

import argparse
import asyncio
import re
import sys
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError

from leadops.config import get_settings
from leadops.db import repositories as repo
from leadops.db.session import create_engine, create_session_factory
from leadops.logging_config import configure_logging
from leadops.security.api_keys import Scope, generate_key

KEY_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,99}")
SCOPE_VALUES = [scope.value for scope in Scope]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="leadops", description="Lead Ops Engine operator CLI")
    groups = parser.add_subparsers(dest="group", required=True)

    keys = groups.add_parser("api-keys", help="manage API keys for machine clients")
    actions = keys.add_subparsers(dest="action", required=True)

    create = actions.add_parser("create", help="create a key and print it once")
    create.add_argument("--name", required=True, help="unique name, e.g. n8n-intake")
    create.add_argument(
        "--scope", dest="scopes", action="append", required=True, choices=SCOPE_VALUES
    )

    actions.add_parser("list", help="list keys (never shows secrets)")

    revoke = actions.add_parser("revoke", help="revoke a key by name")
    revoke.add_argument("--name", required=True)
    return parser


async def _create(name: str, scopes: list[str]) -> int:
    if not KEY_NAME.fullmatch(name):
        print("error: name must be lowercase letters, digits, _ or - (max 100)", file=sys.stderr)
        return 2
    key = generate_key()
    engine = create_engine(get_settings(), application_name="leadops-cli")
    try:
        async with create_session_factory(engine)() as session, session.begin():
            await repo.insert_api_key(
                session,
                name=name,
                prefix=key.prefix,
                key_sha256=key.digest,
                scopes=sorted(set(scopes)),
            )
            await repo.insert_audit_event(
                session,
                event_type="api_key.created",
                actor_type="system",
                actor_id="cli",
                request_id=None,
                data={"name": name, "prefix": key.prefix, "scopes": sorted(set(scopes))},
            )
    except IntegrityError:
        print(f"error: an API key named {name!r} already exists", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(
        f"Created API key {name!r} (prefix {key.prefix}, scopes {', '.join(sorted(set(scopes)))})"
    )
    print("Copy it now. It is not stored and will not be shown again:")
    print(key.full_key)
    return 0


async def _list() -> int:
    engine = create_engine(get_settings(), application_name="leadops-cli")
    try:
        async with create_session_factory(engine)() as session:
            keys = await repo.list_api_keys(session)
    finally:
        await engine.dispose()
    if not keys:
        print("No API keys.")
    for key in keys:
        state = f"revoked {key.revoked_at:%Y-%m-%d}" if key.revoked_at else "active"
        used = f"{key.last_used_at:%Y-%m-%d %H:%M}" if key.last_used_at else "never"
        print(
            f"{key.name:<24} {key.prefix}  {','.join(key.scopes):<32} {state:<18} last used {used}"
        )
    return 0


async def _revoke(name: str) -> int:
    engine = create_engine(get_settings(), application_name="leadops-cli")
    try:
        async with create_session_factory(engine)() as session, session.begin():
            revoked = await repo.revoke_api_key(session, name)
            if revoked is not None:
                await repo.insert_audit_event(
                    session,
                    event_type="api_key.revoked",
                    actor_type="system",
                    actor_id="cli",
                    request_id=None,
                    data={"name": name, "prefix": revoked.prefix},
                )
    finally:
        await engine.dispose()
    if revoked is None:
        print(f"error: no active API key named {name!r}", file=sys.stderr)
        return 1
    print(f"Revoked API key {name!r} (prefix {revoked.prefix})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)
    if args.group == "api-keys":
        if args.action == "create":
            return asyncio.run(_create(args.name, args.scopes))
        if args.action == "list":
            return asyncio.run(_list())
        if args.action == "revoke":
            return asyncio.run(_revoke(args.name))
    return 2


if __name__ == "__main__":
    sys.exit(main())
