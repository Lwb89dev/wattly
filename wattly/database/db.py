"""Database engine/session management.

A single :class:`Database` object is created by the app factory and
shared via ``app.extensions["wattly_db"]``; services receive sessions
explicitly so they stay testable without Flask.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from wattly.config import Config
from wattly.database import migrations


class Database:
    def __init__(self, config: Config) -> None:
        Path(config.data_dir).mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            config.database_url, connect_args={"check_same_thread": False}
        )
        _enable_sqlite_fk(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def migrate(self) -> None:
        migrations.run_migrations(self.engine)

    def session(self) -> Session:
        return self.session_factory()

    def healthcheck(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return True
        except Exception:
            return False


def _enable_sqlite_fk(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
