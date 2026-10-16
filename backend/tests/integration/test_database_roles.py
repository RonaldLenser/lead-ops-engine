"""Least privilege, verified against the real database.

The application role must be able to work with rows but never change the
schema, and it must not be able to rewrite the audit history. If someone
later runs the app with the migrator or superuser role, or loosens the
grants, these tests fail.
"""

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine


async def _execute(database_url: str, statement: str) -> object:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            return await connection.scalar(text(statement))
    finally:
        await engine.dispose()


def run(database_url: str, statement: str) -> object:
    return asyncio.run(_execute(database_url, statement))


def test_app_role_connects_as_itself_and_not_as_a_superuser() -> None:
    url = os.environ["DATABASE_URL"]

    assert run(url, "SELECT current_user") == "leadops_app"
    assert run(url, "SELECT rolsuper FROM pg_roles WHERE rolname = current_user") is False


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE public.should_not_exist (id int)",
        "CREATE SCHEMA should_not_exist",
        "DROP TABLE alembic_version",
        "ALTER TABLE leads ADD COLUMN sneaky text",
    ],
)
def test_app_role_cannot_change_the_schema(ddl: str) -> None:
    with pytest.raises(ProgrammingError, match=r"permission denied|must be owner"):
        run(os.environ["DATABASE_URL"], ddl)


def test_app_role_can_read_the_migration_version() -> None:
    assert run(os.environ["DATABASE_URL"], "SELECT version_num FROM alembic_version") is not None


def test_migrator_role_owns_the_schema_objects() -> None:
    owner = run(
        os.environ["MIGRATION_DATABASE_URL"],
        "SELECT tableowner FROM pg_tables WHERE tablename = 'leads'",
    )

    assert owner == "leadops_migrator"


AUDIT_INSERT = (
    "INSERT INTO audit_events (id, actor_type, event_type) "
    "VALUES (gen_random_uuid(), 'system', 'test.event') RETURNING 1"
)


def test_app_role_can_append_and_read_audit_events() -> None:
    url = os.environ["DATABASE_URL"]

    assert run(url, AUDIT_INSERT) == 1
    assert run(url, "SELECT count(*) FROM audit_events") == 1


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET event_type = 'rewritten'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
def test_app_role_cannot_rewrite_audit_history(statement: str) -> None:
    url = os.environ["DATABASE_URL"]
    run(url, AUDIT_INSERT)

    with pytest.raises(ProgrammingError, match="permission denied"):
        run(url, statement)

    assert run(url, "SELECT count(*) FROM audit_events") == 1
