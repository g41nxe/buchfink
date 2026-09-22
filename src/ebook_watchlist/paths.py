"""Where the runtime keeps its data.

Everything mutable lives under one directory so a move to another host is a copy
(ADR 12). ``EBW_DATA_DIR`` overrides the default ``./data`` next to the repo.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    override = os.environ.get("EBW_DATA_DIR")
    root = Path(override).expanduser() if override else _REPO_ROOT / "data"
    return root.resolve()


def settings_path() -> Path:
    """Was der Betrieb braucht: Quellen, Kadenz, Budgets, Schwellwerte (#36)."""
    return data_dir() / "settings.yaml"


def seed_path() -> Path:
    """Das Saatgut — gelesen allein von ``run seed`` (#36).

    Getrennt von den Einstellungen, weil es nach dem Import nicht mehr gilt:
    was dann zaehlt, steht in der Datenbank. Eine Datei, die man bearbeiten
    kann, ohne dass etwas geschieht, soll wenigstens so heissen.
    """
    return data_dir() / "seed.yaml"


def watchlist_path() -> Path:
    return data_dir() / "watchlist.yaml"


def dismissed_path() -> Path:
    return data_dir() / "dismissed.yaml"


def owned_path() -> Path:
    return data_dir() / "owned.yaml"


def db_path() -> Path:
    return data_dir() / "snapshots.db"


def digests_dir() -> Path:
    return data_dir() / "digests"


def covers_dir() -> Path:
    """Titelbilder, einmal geholt (Ticket 15). Neben der Datenbank, weil sie
    zu ihr gehoeren: ohne die book-Zeile ist die Datei nur noch Muell."""
    return data_dir() / "covers"


def lock_path() -> Path:
    return data_dir() / "run.lock"
