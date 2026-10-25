"""Der Kern des `Store`: die Datei, die Verbindung, die Sitzung (#103)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import (
    create_engine,
    event,
)
from sqlalchemy.orm import Session

from ..migrations import migrate
from .rows import (
    Base,
    _tune_sqlite,
)


class StoreCore:
    """Besitzt die SQLite-Datei. Das Schema entsteht beim ersten Gebrauch."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{path}")
        event.listen(self._engine, "connect", _tune_sqlite)
        # Einmal je Datei, nicht je Verbindung: der Modus steht dauerhaft in
        # der Datenbank, ihn bei jedem Verbindungsaufbau zu setzen waere Arbeit
        # ohne Wirkung.
        with self._engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        migrate(self._engine, Base.metadata)

    def session(self) -> Session:
        return Session(self._engine)

