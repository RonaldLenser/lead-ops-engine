"""Guards against the readiness check and the migrations drifting apart."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from leadops.db.schema import SCHEMA_REVISION

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_schema_revision_matches_the_single_alembic_head() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))

    heads = script.get_heads()

    assert len(heads) == 1, f"Migrations have diverged into multiple heads: {heads}"
    assert heads[0] == SCHEMA_REVISION, (
        f"Newest migration is {heads[0]} but SCHEMA_REVISION is {SCHEMA_REVISION}. "
        "Update src/leadops/db/schema.py."
    )
