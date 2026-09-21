"""Builds the Sources a Profile asks for.

``profile.yaml`` names them::

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
from ..config import ConfigError, Profile
from ..http import HttpClient
from .base import Source
from .beam import BeamSource
from .fake import FakeSource
from .onleihe import OnleiheSource
from .onleihe import selectors as onleihe_selectors
from .overdrive import OverdriveSource


def _build_fake(name: str, options: dict, client: HttpClient) -> Source:
    fixture = options.get("fixture")
    if not fixture:
        raise ConfigError(f"profile.yaml: source {name!r} needs a 'fixture' path")
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
            raise ConfigError(f"profile.yaml: source {name!r}: 'media' must be a list")
        media = []
        for wanted in raw_media:
            icon = onleihe_selectors.MEDIUM_BY_NAME.get(str(wanted).casefold())
            if icon is None:
                known = ", ".join(sorted(onleihe_selectors.MEDIUM_BY_NAME))
                raise ConfigError(
                    f"profile.yaml: source {name!r}: unknown medium {wanted!r} (known: {known})"
                )
            media.append(icon)
    return OnleiheSource(client=client, name=name, media=media)


def _build_overdrive(name: str, options: dict, client: HttpClient) -> Source:
    # Keine Optionen: nur deutsche EPUB-E-Books, und die Einrichtung steht in
    # `selectors.py`. Wer eine andere OverDrive-Bibliothek braucht, gibt ihr
    # dort einen Schluessel — eine Einstellung, die noch niemand gebraucht hat,
    # waere nur eine Zeile, die niemand liest.
    return OverdriveSource(client=client, name=name)


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
DISPLAY: dict[str, str] = {"onleihe": "Onleihe", "overdrive": "OverDrive"}


def category(profile: Profile, name: str) -> str:
    """``"library"`` oder ``"shop"`` fuer eine konfigurierte Quelle."""
    options = profile.sources.get(name) or {}
    kind = options.get("kind", name) if isinstance(options, dict) else name
    return KINDS.get(kind, "shop")


def label(profile: Profile, name: str) -> str:
    """Wie die Quelle der Leserin gegenueber heisst.

    Ihr eigener Name, wo sie einen hat, den die Leserin kennt — sonst die Art.
    """
    options = profile.sources.get(name) or {}
    kind = options.get("kind", name) if isinstance(options, dict) else name
    if eigener := DISPLAY.get(kind):
        return eigener
    return LIBRARY if category(profile, name) == "library" else SHOP


def shops(profile: Profile) -> list[str]:
    """Die Namen der Quellen, bei denen man kaufen kann.

    Gefragt, statt ``"beam"`` hinzuschreiben: der Quellenname ist Konfiguration,
    und er war schon einmal an drei Stellen in die Oberflaeche gerutscht
    (Ticket 05, Review). Wer Preise vergleicht, meint *einen Shop*, nicht
    diesen.
    """
    return [name for name in profile.sources if category(profile, name) == "shop"]


_BUILDERS: dict[str, Callable[[str, dict, HttpClient], Source]] = {
    "fake": _build_fake,
    "onleihe": _build_onleihe,
    "overdrive": _build_overdrive,
    "beam": _build_beam,
}


def build_sources(profile: Profile, client: HttpClient) -> list[Source]:
    if not profile.sources:
        raise ConfigError("profile.yaml: no 'sources' configured — nothing to check")

    sources: list[Source] = []
    for name, options in profile.sources.items():
        options = options or {}
        if not isinstance(options, dict):
            raise ConfigError(f"profile.yaml: options for source {name!r} must be a mapping")
        kind = options.get("kind", name)
        builder = _BUILDERS.get(kind)
        if builder is None:
            known = ", ".join(sorted(_BUILDERS))
            raise ConfigError(f"profile.yaml: unknown source {kind!r} (known: {known})")
        sources.append(builder(name, options, client))
    return sources
