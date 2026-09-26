"""Nur Funde in den Sprachen des Profils (#10, #32).

Die DNB nennt zu jeder ISBN, die sie kennt, die Sprache. Benutzt wurde das
nirgends: eine englische Ausgabe kam auf den Stapel und bekam ein volles
Urteil, obwohl das Profil ausdruecklich auf deutschsprachige Literatur zielt.
Ein solcher Fund ist nicht *schwaecher* als ein deutscher — er kommt gar nicht
in Frage, und ihn zu beurteilen kostet einen Modellaufruf fuer nichts.

**Zwei Zeugen, einer mit Vorrang.** Die DNB kennt nur deutsche
Veroeffentlichungen; eine ungarische Ausgabe von *Wayward Pines* stand deshalb
mit ungarischem Klappentext im Stapel, ohne dass jemand widersprochen haette.
Die ISBN sagt es selbst: ihre Registrierungsgruppe nennt den Sprachraum, ohne
eine Anfrage und ohne neue Quelle. Gefragt wird sie aber erst, wenn die DNB
schweigt — die hatte das Buch in der Hand, die Gruppe kennt nur den Verlag
(#32).

Eine Regel, zwei Stellen: der Lauf filtert vor dem Bewertungstor, der Stapel
beim Anzeigen. Beide fragen hier.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .models import MatchReason, Observation

if TYPE_CHECKING:
    from .config import Settings
    from .store import Store

LanguageOf = Callable[[str], "str | None"]

#: Die Sonderwerte von ISO 639-2: unbestimmt, mehrere Sprachen, ohne
#: sprachlichen Inhalt, nicht erfasst. Keiner sagt, dass ein Buch *nicht*
#: deutsch ist — eine zweisprachige Ausgabe traegt ``mul`` —, also zaehlen sie
#: wie Schweigen.
NOT_A_LANGUAGE = frozenset({"und", "mul", "zxx", "mis"})


#: Registrierungsgruppe der ISBN -> Sprache, in den Codes der DNB
#: (ISO 639-2/B). Klein gehalten: jede Zeile hat einen Anlass, und was hier
#: fehlt, schweigt — behaupten ist schlimmer als schweigen. Gruppe 992 aus dem
#: Bestand steht deshalb nicht hier.
#:
#: Die einstelligen Gruppen sind Sprachraeume, die dreistelligen Laender: 2
#: heisst "franzoesischsprachig", 606 dagegen "in Rumaenien registriert". Ein
#: ungarischsprachiges Buch aus Rumaenien bekaeme von uns also ``rum``. Fuer
#: diese Regel macht das keinen Unterschied — beides steht nicht im Profil —,
#: richtig ist es trotzdem nicht.
GROUP_LANGUAGES: dict[str, str] = {
    "0": "eng",
    "1": "eng",
    "2": "fre",
    "3": "ger",
    "4": "jpn",
    "5": "rus",
    "606": "rum",
    "615": "hun",
    "963": "hun",
}


#: Wie eine Sprache der Leserin gegenueber heisst — als Adjektiv, weil es
#: auf der Kachel neben einem Buch steht ("englisch"). Was hier fehlt, steht
#: als Code da: ein seltener Code ist immer noch mehr Auskunft als keine.
LANGUAGE_NAMES: dict[str, str] = {
    "ger": "deutsch",
    "eng": "englisch",
    "fre": "französisch",
    "spa": "spanisch",
    "ita": "italienisch",
    "dut": "niederländisch",
    "swe": "schwedisch",
    "dan": "dänisch",
    "nor": "norwegisch",
    "pol": "polnisch",
    "por": "portugiesisch",
    "tur": "türkisch",
    "rus": "russisch",
    "jpn": "japanisch",
    "hun": "ungarisch",
    "rum": "rumänisch",
}


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def is_other_language(code: str | None, settings: Settings) -> bool:
    """Ob eine **ausdrueckliche** Sprache keine des Profils ist.

    Dieselbe Zurueckhaltung wie bei :func:`is_foreign`: keine Angabe und die
    Sonderwerte ("unbestimmt", "mehrsprachig") sagen nicht, dass ein Buch
    nicht deutsch ist.
    """
    return bool(code) and code not in NOT_A_LANGUAGE and code not in settings.languages


def language_of_isbn(isbn: str) -> str | None:
    """Die Sprache, die die Registrierungsgruppe nennt — oder nichts.

    Gelesen wird nur die Gruppe hinter dem Praefix (978 oder 979): erst ein
    Zeichen, dann drei. Die zwei- und vierstelligen Gruppen dazwischen stehen
    nicht in der Tabelle, und was nicht darin steht, schweigt.
    """
    digits = "".join(z for z in isbn if z.isdigit())
    if len(digits) != 13 or not digits.startswith(("978", "979")):
        return None
    rest = digits[3:]
    return GROUP_LANGUAGES.get(rest[:1]) or GROUP_LANGUAGES.get(rest[:3])


def language_finder(store: Store) -> LanguageOf:
    """Einmal gelesen, fuer den ganzen Lauf oder die ganze Seite."""
    languages = store.dnb_languages()
    return languages.get


def is_foreign(observation: Observation, settings: Settings, language_of: LanguageOf) -> bool:
    """Ob die DNB diesen Fund **ausdruecklich** in einer fremden Sprache fuehrt.

    Unbekannt ist nie fremd. Viele Selbstverlagstitel haben keine ISBN, und die
    DNB kennt nicht jede — waere Schweigen ein Ausschluss, verschwaende ein
    grosser Teil des Stapels, ohne dass je jemand etwas ueber ihn wusste.

    Ein Watchlist-Titel ist nie fremd: was die Leserin selbst auf die Liste
    setzt, bleibt dort, in welcher Sprache auch immer.
    """
    if observation.match_reason is MatchReason.WATCHLIST or not observation.isbn:
        return False
    language = language_of(observation.isbn)
    if language is None:
        # Nur wo die DNB den Titel gar nicht kennt, spricht die Nummer selbst
        # (#32). Sagt die DNB "unbestimmt" oder "mehrsprachig", hat sie das
        # Buch immerhin in der Hand gehabt — dann gilt ihr Schweigen, nicht
        # die Herkunft des Verlags.
        language = language_of_isbn(observation.isbn)
    if language is None or language in NOT_A_LANGUAGE:
        return False
    return language not in settings.languages
