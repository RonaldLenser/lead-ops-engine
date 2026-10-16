"""The ORM models and the migrations describe the same schema."""

from alembic import command

from tests.integration.conftest import alembic_config


def test_models_and_migrations_have_not_drifted() -> None:
    # Runs Alembic autogenerate against the migrated database; raises if the
    # models would produce any new operation (a column, table, index, FK...).
    command.check(alembic_config())
