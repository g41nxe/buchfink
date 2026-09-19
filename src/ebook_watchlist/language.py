"""Nur Funde in den Sprachen des Profils (#10).

Die DNB nennt zu jeder ISBN, die sie kennt, die Sprache. Benutzt wurde das
nirgends: eine englische Ausgabe kam auf den Stapel und bekam ein volles
Urteil, obwohl das Profil ausdruecklich auf deutschsprachige Literatur zielt.
Ein solcher Fund ist nicht *schwaecher* als ein deutscher — er kommt gar nicht
in Frage, und ihn zu beurteilen kostet einen Modellaufruf fuer nichts.

Eine Regel, zwei Stellen: der Lauf filtert vor dem Bewertungstor, der Stapel
beim Anzeigen. Beide fragen hier.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .models import MatchReason, Observation

if TYPE_CHECKING:
    from .config import Profile
    from .store import Store

LanguageOf = Callable[[str], "str | None"]

#: Die Sonderwerte von ISO 639-2: unbestimmt, mehrere Sprachen, ohne
#: sprachlichen Inhalt, nicht erfasst. Keiner sagt, dass ein Buch *nicht*
#: deutsch ist — eine zweisprachige Ausgabe traegt ``mul`` —, also zaehlen sie
#: wie Schweigen.
NOT_A_LANGUAGE = frozenset({"und", "mul", "zxx", "mis"})


def language_finder(store: Store) -> LanguageOf:
    """Einmal gelesen, fuer den ganzen Lauf oder die ganze Seite."""
    sprachen = store.dnb_languages()
    return sprachen.get


def is_foreign(observation: Observation, profile: Profile, language_of: LanguageOf) -> bool:
    """Ob die DNB diesen Fund **ausdruecklich** in einer fremden Sprache fuehrt.

    Unbekannt ist nie fremd. Viele Selbstverlagstitel haben keine ISBN, und die
    DNB kennt nicht jede — waere Schweigen ein Ausschluss, verschwaende ein
    grosser Teil des Stapels, ohne dass je jemand etwas ueber ihn wusste.

    Ein Watchlist-Titel ist nie fremd: was die Leserin selbst auf die Liste
    setzt, bleibt dort, in welcher Sprache auch immer.
    """
    if observation.match_reason is MatchReason.WATCHLIST or not observation.isbn:
        return False
    sprache = language_of(observation.isbn)
    if sprache is None or sprache in NOT_A_LANGUAGE:
        return False
    return sprache not in profile.languages
