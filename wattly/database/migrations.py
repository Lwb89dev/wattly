"""Minimal ordered-migration runner (schema versioning without Alembic).

Each migration is an (version, name, callable(engine)) triple; applied
versions are tracked in ``schema_migrations``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

Migration = tuple[int, str, Callable[[Engine], None]]

_SCHEMA_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _create_initial_schema(engine: Engine) -> None:
    from wattly.database import models  # noqa: F401 (register metadata)

    models.Base.metadata.create_all(engine)
    # Helpful composite indexes for the history filters.
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bills_period ON bills(billing_period_start)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bills_amount ON bills(total_amount_cents)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bills_kwh ON bills(total_kwh)"))


MIGRATIONS: list[Migration] = [
    (1, "initial schema", _create_initial_schema),
]


def run_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(_SCHEMA_VERSIONS_DDL))
        applied = {
            row[0]
            for row in conn.execute(text("SELECT version FROM schema_migrations"))
        }
    for version, name, fn in MIGRATIONS:
        if version in applied:
            continue
        fn(engine)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO schema_migrations (version, name) VALUES (:v, :n)"),
                {"v": version, "n": name},
            )


def schema_version(engine: Engine) -> int:
    try:
        with engine.connect() as conn:
            row: Any = conn.execute(
                text("SELECT MAX(version) FROM schema_migrations")
            ).first()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0
