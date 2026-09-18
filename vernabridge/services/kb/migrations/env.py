"""Alembic environment: connects migrations to our models and to VB_DB_DSN.

Kept as small as possible. The database URL comes from the VB_DB_DSN
environment variable only — never from a file in the repo.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from vb_kb.db import Base


def _dsn() -> str:
    dsn = os.environ.get("VB_DB_DSN")
    if not dsn:
        raise RuntimeError("Set VB_DB_DSN to run migrations, e.g. postgresql+psycopg://...")
    return dsn


def run_migrations_online() -> None:
    engine = create_engine(_dsn())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline (--sql) mode is not supported; run against a real database.")
run_migrations_online()
