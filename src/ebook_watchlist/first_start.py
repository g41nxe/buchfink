"""Der allererste Start: die Beispiele einspielen (#104).

Bis #104 begann der Schnellstart mit dem Kopieren dreier Dateien aus
``examples/`` nach ``data/`` und einem ``ebw seed``. Jetzt tut das der erste
Start selbst, wenn es noch keine ``settings.yaml`` gibt: die Beispiele kommen
nach ``data/``, wo man sie lesen und ändern kann, und das Saatgut in die
Datenbank. Danach ist die Datenbank die Wahrheit, und die Oberfläche der Ort,
an dem man etwas ändert.

Eine vorhandene Datei wird nie überschrieben; ein zweiter Start ändert nichts.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import paths

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

#: Was aus den Beispielen kommt. ``owned.yaml`` und ``dismissed.yaml`` nicht:
#: ein fremder Besitz wäre im eigenen Regal falsch.
FILES = ("settings.yaml", "seed.yaml", "watchlist.yaml")


def ensure() -> bool:
    """Beim ersten Start die Beispiele einspielen. Gibt zurück, ob etwas geschah.

    Erster Start heißt: weder ``settings.yaml`` noch eine Datenbank. Fehlt nur
    die Datei, ist das ein Fehler, den der Lauf laut sagt — eine bestehende
    Installation still mit Beispielen aufzufüllen, wäre die falsche Antwort.
    """
    if (
        paths.settings_path().is_file()
        or paths.db_path().exists()
        or not (EXAMPLES / "settings.yaml").is_file()
    ):
        return False
    target = paths.data_dir()
    target.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        if (EXAMPLES / name).is_file() and not (target / name).exists():
            shutil.copyfile(EXAMPLES / name, target / name)

    from .config import load_seed, load_settings, load_watchlist
    from .relations import RelationKind
    from .seed import sow
    from .store import Store

    settings = load_settings()
    store = Store(paths.db_path())
    if store.interests(settings.slug) or store.relations(
        settings.slug, kind=str(RelationKind.WATCHING)
    ):
        return True
    sow(store, settings, load_seed(), load_watchlist(), now=datetime.now())
    print(f"Erster Start: Beispiele nach {target} kopiert und eingespielt.", file=sys.stderr)
    return True
