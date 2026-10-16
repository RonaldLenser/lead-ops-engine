"""Declarative base for all ORM models.

No models exist yet (M1 has no domain tables). The base is defined now so
Alembic has metadata to compare against and so every future table gets the
same constraint naming convention from the first migration on.

Why a naming convention: without one, PostgreSQL invents constraint names,
and a later migration that drops or alters a constraint has to guess them.
With it, every name is predictable (for example uq_contacts_email_normalized).
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
