"""Abzüge nach dem Urteil — Regeln, die nicht das Modell anwendet (#28).

Das Modell beurteilt das Buch. Was an einer Liste hängt statt an einem Urteil,
wendet der Code an: gleich bei jedem Buch, nachprüfbar, und ohne dass ein Modell
es mal doppelt und mal gar nicht abzieht. Der Abzug steht neben dem Urteil,
damit die Leserin sieht, warum ein Buch unter die Schwelle fiel.
"""

from __future__ import annotations

import re

#: Die Marke, die neben dem Urteil steht.
SELF_PUBLISHED = "Selbstverlag"

#: Plattformen, über die Autor:innen selbst veröffentlichen. Gemessen im Stapel
#: vom 2026-09-19: 21 von 30 Büchern kamen über eine davon, neobooks allein
#: vierzehnmal. Kleinverlage stehen bewusst nicht hier — sie haben ein
#: Lektorat, und ob sie taugen, entscheidet die Leseprobe. Gesucht wird ohne
#: Rücksicht auf Groß- und Kleinschreibung und an Wortgrenzen, damit "BoD"
#: nicht in "Bodensee" steckt.
SELF_PUBLISHING_PLATFORMS = (
    "neobooks",
    "epubli",
    "tredition",
    "books on demand",
    "bod",
    "tolino media",
    "independently published",
    "kindle direct publishing",
    "createspace",
    "xinxii",
    "twentysix",
    "bookmundo",
)

_PLATFORM = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in SELF_PUBLISHING_PLATFORMS) + r")\b",
    re.IGNORECASE,
)


def is_self_published(publisher: str | None) -> bool:
    """Ob dieser Verlag eine Selbstverlags-Plattform ist. Ohne Angabe: nein."""
    return bool(publisher and _PLATFORM.search(publisher))


def deductions_for(publisher: str | None) -> tuple[str, ...]:
    """Die Abzüge für ein Buch, je einer Stern."""
    return (SELF_PUBLISHED,) if is_self_published(publisher) else ()
