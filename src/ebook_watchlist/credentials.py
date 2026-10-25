"""Geheimnisse: aus der Umgebung, sonst aus ``data/secrets.env`` (#104).

Gelesen wird genau der eine Name, nach dem gefragt wird — die Datei landet
nicht als Ganzes in der Umgebung, und nichts davon wird je ausgegeben. Ein
leerer Wert gilt als nicht gesetzt: so steht in der Datei, was es gibt, ohne
dass es etwas tut.
"""

from __future__ import annotations

import os

from . import paths

FILE_NAME = "secrets.env"


def secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    path = paths.data_dir() / FILE_NAME
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, rest = line.strip().partition("=")
        if sep and key.strip() == name:
            value = rest.strip().strip('"').strip("'")
            return value or None
    return None
