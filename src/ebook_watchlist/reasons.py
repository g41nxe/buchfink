"""Warum ein Buch überhaupt vorgeschlagen wird (Ticket 14).

Eine einzige Stelle für die Formulierung, weil Digest und Weboberfläche sonst
dasselbe zweimal und verschieden sagen.

Die Anzeige zeigte bisher einen Preis und einen Regalnamen und überliess der
Leserin, einen Zusammenhang zu erschliessen, den es nicht gibt: *21 — Fremder
Schatten* stand für 10,99 € auf einer Seite mit Deal-Abzeichen, obwohl der
Preis an seiner Aufnahme keinen Anteil hatte. Ausgeschrieben ist der Anlass
nachprüfbar — und man sieht, wie dünn "neu in einem Regal" ist. Genau das ist
das Argument für das Bewertungstor (ADR 19), an der Stelle, an der die Leserin
es sehen kann.
"""

from __future__ import annotations

from .models import MatchReason, Observation

#: Was die Leserin sieht, wo der Code ``genre_category`` sagt. "Regal" war der
#: Begriff des Shops, nicht ihrer.
GENRE_CATEGORY_WORD = "Thema"

_SHELF_NAMES = {
    "psychothriller": "Psychothriller",
    "horror-mystery-allgemein": "Horror & Mystery",
    "science-fiction-allgemein": "Science-Fiction",
    "space-opera": "Space Opera",
    "military-sf": "Military SF",
    "spionage": "Spionage",
}


def genre_category_name(category: str | None) -> str | None:
    """``belletristik/krimi-thriller/psychothriller`` → ``Psychothriller``.

    Unbekannte Pfade werden nicht erraten, sondern lesbar gemacht: der letzte
    Abschnitt ohne Bindestriche. Eine Liste, die jeden Shop-Pfad kennen müsste,
    wäre bei der ersten neuen Kategorie still veraltet.
    """
    if not category:
        return None
    if "/" not in category and category != category.lower():
        # Kein Pfad, sondern schon ein Name — die Sammlung einer Bibliothek
        # („Lucky Day", #74). ``capitalize`` machte daraus „Lucky day".
        return category.strip()
    last = category.strip("/").rsplit("/", 1)[-1]
    return _SHELF_NAMES.get(last) or last.replace("-", " ").strip().capitalize() or None


def _is_library(source: str) -> bool:
    """Ob die Quelle eine Bibliothek ist — nach ihrer Art, wie sie heißt."""
    from .sources.registry import KINDS

    return KINDS.get(source) == "library"


def why_shown(observation: Observation) -> str:
    """Ein Satzteil, der den Anlass benennt — nicht den Match Reason.

    Bei Autor:innen wird die Verbindung zur Leserin genannt, nicht die
    Kategorie: "von Simon Beckett, den du liest" sagt mehr als "Autor:in".
    """
    if observation.match_reason is MatchReason.WATCHLIST:
        return "steht auf deiner Watchlist"

    if observation.match_reason is MatchReason.PROFILE_AUTHOR:
        author = (observation.author or "").strip()
        if not author:
            return "neu von einer Autor:in, der du folgst"
        return f"neu von {author}, der du folgst"

    category_name = genre_category_name(observation.category)
    if category_name and _is_library(observation.source):
        # Eine Sammlung der Bibliothek ist kein Regal im Shop: was darin steht,
        # lässt sich gleich leihen (#74).
        return f"sofort ausleihbar aus „{category_name}“"
    if category_name:
        return f"neu im {GENRE_CATEGORY_WORD} {category_name}"
    return f"neu in einem {GENRE_CATEGORY_WORD}, dem du folgst"


def short_why(observation: Observation) -> str:
    """Die Kurzform für ein Etikett in der Oberfläche.

    Ohne das Wort "Thema" davor: die Pille steht immer in Bernstein und neben
    "Autor:in" (Petrol) — die Farbe sagt schon, dass es ein Thema ist, der
    Name selbst braucht den Vorspann nicht (Watchlist, Vorschläge, Startseite).
    """
    if observation.match_reason is MatchReason.WATCHLIST:
        return "Watchlist"
    if observation.match_reason is MatchReason.PROFILE_AUTHOR:
        return "Autor:in"
    return genre_category_name(observation.category) or GENRE_CATEGORY_WORD
