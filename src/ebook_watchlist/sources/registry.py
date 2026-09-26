"""Builds the Sources the settings ask for.

``settings.yaml`` names them::

    sources:
      onleihe:
      fake:
        kind: fake
        fixture: fake-source.yaml

The key is the Source's name in the Snapshot; ``kind`` picks the implementation
and defaults to the key, so the common case needs no options at all.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import paths
from ..config import ConfigError, Settings
from ..http import HttpClient
from .base import Source
from .beam import BeamSource
from .fake import FakeSource
from .onleihe import OnleiheSource
from .onleihe import selectors as onleihe_selectors
from .onleihe.parse import OnleiheList
from .overdrive import OverdriveSource
from .overdrive.parse import Collection


def _build_fake(name: str, options: dict, client: HttpClient) -> Source:
    fixture = options.get("fixture")
    if not fixture:
        raise ConfigError(f"settings.yaml: source {name!r} needs a 'fixture' path")
    path = Path(fixture)
    if not path.is_absolute():
        path = paths.data_dir() / path
    return FakeSource(fixture=path, name=name)


def _build_onleihe(name: str, options: dict, client: HttpClient) -> Source:
    raw_media = options.get("media")
    if raw_media is None:
        media = onleihe_selectors.DEFAULT_MEDIA
    else:
        if not isinstance(raw_media, list):
            raise ConfigError(f"settings.yaml: source {name!r}: 'media' must be a list")
        media = []
        for wanted in raw_media:
            icon = onleihe_selectors.MEDIUM_BY_NAME.get(str(wanted).casefold())
            if icon is None:
                known = ", ".join(sorted(onleihe_selectors.MEDIUM_BY_NAME))
                raise ConfigError(
                    f"settings.yaml: source {name!r}: unknown medium {wanted!r} (known: {known})"
                )
            media.append(icon)
    # Listen, aus denen Vorschläge kommen (#74), etwa:
    #   lists:
    #   - {path: "lrMediaList,0-0-0-107-0-0-0-0-0-0-0.html", name: Zuletzt zurückgegeben}
    raw_lists = options.get("lists") or []
    if not isinstance(raw_lists, list):
        raise ConfigError(f"settings.yaml: source {name!r}: 'lists' must be a list")
    lists = []
    for entry in raw_lists:
        if not isinstance(entry, dict) or not entry.get("path") or not entry.get("name"):
            raise ConfigError(f"settings.yaml: source {name!r}: a list needs 'path' and 'name'")
        lists.append(
            OnleiheList(str(entry["path"]), str(entry["name"]), bool(entry.get("fiction", True)))
        )
    return OnleiheSource(client=client, name=name, media=media, lists=tuple(lists))


def _build_overdrive(name: str, options: dict, client: HttpClient) -> Source:
    # Die Bibliothek selbst steht in `selectors.py` — eine andere hat noch
    # niemand gebraucht. Einstellbar sind nur die Sammlungen, aus denen
    # Vorschläge kommen (#74), etwa:
    #
    #   collections:
    #     - {id: 1572172, name: Lucky Day}             # Belletristik (FIC)
    #     - {id: …, name: …, bisac: [FIC031, FIC028]}  # nur Thriller und SF
    raw = options.get("collections") or []
    if not isinstance(raw, list):
        raise ConfigError(f"settings.yaml: source {name!r}: 'collections' must be a list")
    collections = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("name"):
            raise ConfigError(
                f"settings.yaml: source {name!r}: a collection needs 'id' and 'name'"
            )
        bisac = entry.get("bisac")
        if bisac is not None and not isinstance(bisac, list):
            raise ConfigError(f"settings.yaml: source {name!r}: 'bisac' must be a list")
        collections.append(
            Collection(
                str(entry["id"]),
                str(entry["name"]),
                tuple(str(b) for b in bisac) if bisac is not None else ("FIC",),
            )
        )
    return OverdriveSource(client=client, name=name, collections=tuple(collections))


def _build_beam(name: str, options: dict, client: HttpClient) -> Source:
    return BeamSource(client=client, name=name)


#: Welcher Art eine Quelle ist. Die Oberflaeche zeigt die Art, nicht den Namen:
#: "voebb" war nie ein Wort fuer die Leserin, und wie ihre Bibliothek in dieser
#: Installation heisst, entscheidet die Konfiguration (Ticket 14).
#:
#: Hier und nicht in einer Vorlage, weil die Registry ohnehin die Stelle ist,
#: die weiss, *was* eine Quelle ist.
KINDS: dict[str, str] = {
    "onleihe": "library",
    "overdrive": "library",
    "beam": "shop",
    "fake": "shop",
}

LIBRARY = "Bibliothek"
SHOP = "Shop"

#: In welcher Reihenfolge die Arten erscheinen — im Buchkopf, in den
#: Listenzeilen, ueberall. Bibliothek vor Shop: leihen kostet nichts, und wer
#: leihen kann, fragt nicht mehr nach dem Preis (#21).
CATEGORY_ORDER: tuple[str, ...] = ("library", "shop")

#: Wo die Art als Beschriftung nicht mehr reicht. Ticket 14 zeigte die *Art*
#: statt des Namens, und das war richtig: "voebb" war nie ein Wort fuer die
#: Leserin. Mit zwei Bibliotheken trug die Regel nicht mehr — die Buchseite
#: zeigte zwei Kacheln "BIBLIOTHEK", die eine "verliehen", die andere "nicht im
#: Katalog", und welche welche war, stand nirgends.
#:
#: "Onleihe" und "OverDrive" sind dagegen sehr wohl Woerter fuer die Leserin:
#: das sind die beiden Stellen, an denen sie ausleiht. Was hier fehlt, faellt
#: weiterhin auf die Art zurueck — ein einzelner Shop bleibt "Shop".
#:
#: Geschluesselt nach **Quellname**, nicht nach Art: `voebb: {kind: onleihe}`
#: ist dieselbe Software, aber ein anderer Verbund — nach Art geschluesselt
#: hiessen beide "Onleihe", und die Einrichtung haette nichts dagegen sagen
#: koennen (#14).
DISPLAY: dict[str, str] = {"onleihe": "Onleihe", "overdrive": "OverDrive"}


def category(settings: Settings, name: str) -> str:
    """``"library"`` oder ``"shop"`` fuer eine konfigurierte Quelle."""
    options = settings.sources.get(name) or {}
    kind = options.get("kind", name) if isinstance(options, dict) else name
    return KINDS.get(kind, "shop")


def label(settings: Settings, name: str) -> str:
    """Wie die Quelle der Leserin gegenueber heisst.

    Drei Stufen, in dieser Reihenfolge (#14):

    1. **Die Tabelle** — das Werkzeug kennt die Plattformen, die es
       unterstuetzt, und niemand muss "Onleihe" von Hand eintragen.
    2. **Die Einrichtung** (``name:`` in der Konfiguration) — sie springt ein,
       wo die Tabelle nichts weiss. Eine zweite Bibliothek desselben Bauart
       braucht das, denn wie sie heisst, haengt an der Installation.
    3. **Die Art** — ein einzelner Shop bleibt "Shop"; solange es je Art eine
       gibt, ist das kein Verlust, und "beam" war nie ein Wort fuer die
       Leserin (Ticket 14).
    """
    options = settings.sources.get(name) or {}
    if own := DISPLAY.get(name):
        return own
    if isinstance(options, dict) and (from_institution := options.get("name")):
        return str(from_institution)
    return LIBRARY if category(settings, name) == "library" else SHOP


def shops(settings: Settings) -> list[str]:
    """Die Namen der Quellen, bei denen man kaufen kann.

    Gefragt, statt ``"beam"`` hinzuschreiben: der Quellenname ist Konfiguration,
    und er war schon einmal an drei Stellen in die Oberflaeche gerutscht
    (Ticket 05, Review). Wer Preise vergleicht, meint *einen Shop*, nicht
    diesen.
    """
    return [name for name in settings.sources if category(settings, name) == "shop"]


_BUILDERS: dict[str, Callable[[str, dict, HttpClient], Source]] = {
    "fake": _build_fake,
    "onleihe": _build_onleihe,
    "overdrive": _build_overdrive,
    "beam": _build_beam,
}


def build_sources(settings: Settings, client: HttpClient) -> list[Source]:
    if not settings.sources:
        raise ConfigError("settings.yaml: no 'sources' configured — nothing to check")

    sources: list[Source] = []
    for name, options in settings.sources.items():
        options = options or {}
        if not isinstance(options, dict):
            raise ConfigError(f"settings.yaml: options for source {name!r} must be a mapping")
        kind = options.get("kind", name)
        builder = _BUILDERS.get(kind)
        if builder is None:
            known = ", ".join(sorted(_BUILDERS))
            raise ConfigError(f"settings.yaml: unknown source {kind!r} (known: {known})")
        sources.append(builder(name, options, client))
    return sources
