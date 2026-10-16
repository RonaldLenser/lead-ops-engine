"""Guard against running destructive test setup on the wrong database.

Integration tests roll every migration back to nothing and truncate tables.
Pointed at a real database by mistake (a copied .env, a wrong shell
variable), that would wipe it. Before any destructive step, ALL of these
must hold, or the test session stops:

1. ALLOW_DESTRUCTIVE_TEST_DB is exactly "true" (an explicit opt-in).
2. The URL's host is local: localhost, 127.0.0.1, or ::1.
3. The URL's database name ends in "_test".
4. After connecting, the server itself reports a current_database() ending
   in "_test" (catches proxies, connection poolers, or URL tricks that make
   the name in the URL differ from the database actually reached).
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

OPT_IN_VARIABLE = "ALLOW_DESTRUCTIVE_TEST_DB"
SAFE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
TEST_DATABASE_SUFFIX = "_test"


class UnsafeTestDatabaseError(RuntimeError):
    pass


def check_destructive_target(database_url: str, environ: Mapping[str, str]) -> None:
    """Static checks (1-3). Raises UnsafeTestDatabaseError with the reason."""
    if environ.get(OPT_IN_VARIABLE) != "true":
        raise UnsafeTestDatabaseError(
            f"Refusing destructive test setup: set {OPT_IN_VARIABLE}=true to allow resetting "
            "the test database."
        )
    parts = urlsplit(database_url)
    if parts.hostname not in SAFE_HOSTS:
        raise UnsafeTestDatabaseError(
            f"Refusing destructive test setup: host {parts.hostname!r} is not local "
            f"({', '.join(sorted(SAFE_HOSTS))})."
        )
    database = parts.path.lstrip("/")
    if not database.endswith(TEST_DATABASE_SUFFIX):
        raise UnsafeTestDatabaseError(
            f"Refusing destructive test setup: database {database!r} does not end in "
            f"{TEST_DATABASE_SUFFIX!r}."
        )


async def check_server_database(database_url: str) -> None:
    """Check 4: ask the server which database this connection really reached."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            name = await connection.scalar(text("SELECT current_database()"))
    finally:
        await engine.dispose()
    if not isinstance(name, str) or not name.endswith(TEST_DATABASE_SUFFIX):
        raise UnsafeTestDatabaseError(
            f"Refusing destructive test setup: server reports database {name!r}."
        )
