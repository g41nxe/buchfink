"""Was die kleinen Aufträge tun (ADR 40).

Bis ADR 40 standen diese Arbeiten als Closures in `app.py` und liefen als
Fäden im Webprozess. Jetzt arbeitet sie der Hintergrunddienst ab, und der kennt
keine Closures: er bekommt eine Art (``recheck``, ``portrait``, ``identify``)
und einen Schlüssel und schlägt die Arbeit hier nach.

Jede Arbeit holt sich Store und Einstellungen selbst, im Moment, in dem sie
läuft — nicht beim Einstellen: der Auftrag soll gelten, was dann gilt.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from datetime import datetime

from .. import paths
from ..config import load_settings
from ..single import Report
from ..store import Store


def _recheck(book_id: Hashable) -> Report:
    """Der enge Lauf für einen Eintrag (Ticket 51)."""
    # Erst hier nachgeschlagen, nicht beim Import: Tests ersetzen
    # ``recheck.check_one``, und das soll auch dann greifen.
    from . import recheck

    return recheck.check_one(book_id)  # type: ignore[arg-type]


def _portrait(key: Hashable, *, again: bool = False) -> Report:
    """Einen Steckbrief anlegen (#45, #48).

    Der Schlüssel sagt, was beschrieben wird: ``("book", 39)`` für die
    Buchseite, ``("item", "beam", "7")`` für einen Fund. ``again``: der Knopf
    „neu beschreiben“ — auch fragen, wenn schon einer steht.
    """
    from . import book, discovery

    assert isinstance(key, tuple)
    store, settings, now = Store(paths.db_path()), load_settings(), datetime.now()
    if key[0] == "book":
        return Report(trouble=book.portray(store, settings, key[1], now=now, again=again))
    return Report(
        trouble=discovery.portray(store, settings, key[1], key[2], now=now, again=again)
    )


def _identify(key: Hashable) -> Report:
    """Erkennen, welches Buch in der Erstaufnahme gemeint ist (#47)."""
    from . import intake

    assert isinstance(key, tuple)
    store, settings, now = Store(paths.db_path()), load_settings(), datetime.now()
    return Report(trouble=intake.identify(store, settings, key[1], now=now))


#: Art -> Arbeit. Tests tragen hier eigene Arten ein.
WORK: dict[str, Callable[..., Report]] = {
    "recheck": _recheck,
    "portrait": _portrait,
    "identify": _identify,
}
