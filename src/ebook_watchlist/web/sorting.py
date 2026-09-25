"""Wonach die beiden Listen sortieren (#37).

Eine Stelle für Watchlist und Vorschläge: beide zeigen dieselbe Wahl im selben
Auswahlfeld, und zweimal dieselben Schlüssel zu schreiben hieße, sie
auseinanderlaufen zu lassen — „Preis" soll in beiden Listen dasselbe tun und
dasselbe heißen.

Die Voreinstellung ist der **erste** Eintrag der Reihe, nicht ein Sonderfall
daneben. Vorher galt in jeder Liste eine ungeschriebene Reihenfolge; sobald es
eine zweite gibt, gehört sie benannt, sonst steht sie als Zufall der Abfrage da.

Jeder Schlüssel sortiert **aufsteigend** — was zuerst stehen soll, muss also im
Schlüsselwert klein sein. Deshalb die Verneinungen (`not entry.borrowable`) und
die negativen Zahlen: eine Richtung je Schlüssel, in einer Vergleichsfunktion,
statt `reverse=True` und dann Ausnahmen für die Ränge, die andersherum laufen.

Die Wahl steht in der Adresse (`?sortiert=preis`) und ist damit teilbar. Der
Browser merkt sie sich zusätzlich, aber nur, um eine leere Adresse zu füllen —
was dasteht, gilt.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

#: Nullpunkt für „wie jung ist das". Nicht ``datetime.min``: dessen
#: ``timestamp()`` wirft unter Windows, und die Differenz ist der ruhigere Weg.
_EPOCH = datetime(1970, 1, 1)


def _newest_first(moment: datetime | None) -> float:
    """Je jünger, desto kleiner — und ohne Zeitpunkt ans Ende.

    „Kein Zeitpunkt" ist nicht „uralt": eine Zeile, die niemand gesehen hat,
    gehört nicht ans eine Ende der Reihe, sondern hinter alles, was eine
    Auskunft hat.
    """
    if moment is None:
        return float("inf")
    return -(moment - _EPOCH).total_seconds()


def _title(row: Any) -> str:
    """Der Gleichstandsbrecher für jeden Schlüssel.

    Darum gibt es „Titel" nicht als eigene Wahl: alphabetisch ist die Liste
    ohnehin überall, wo der Schlüssel nichts mehr unterscheidet.
    """
    return (row.title or "").casefold()


@dataclass(frozen=True, slots=True)
class Order:
    """Ein Schlüssel, wie ihn Adresse und Auswahlfeld kennen."""

    #: Was in der Adresse steht (`?sortiert=preis`).
    slug: str
    #: Was im Auswahlfeld steht. Nennt die Richtung mit — „Preis" allein sagt
    #: nicht, ob das Teure oben steht.
    label: str
    key: Callable[[Any], tuple]


def _by_price(row: Any) -> tuple:
    """Das Günstigste zuerst, Preisloses ans Ende.

    Eine Bibliothek nennt keinen Preis. Ohne den ersten Rang stünde sie mit 0
    Cent vor jedem Schnäppchen — „umsonst" wäre dann eine Behauptung, die
    niemand aufgestellt hat.
    """
    return (row.price_cents is None, row.price_cents or 0, _title(row))


WATCHLIST: tuple[Order, ...] = (
    # Die bisherige Reihenfolge der Seite, jetzt mit Namen.
    Order(
        "offen",
        "offene zuerst, dann A–Z",
        lambda entry: (not entry.needs_attention, _title(entry)),
    ),
    Order("frei", "ausleihbar zuerst", lambda entry: (not entry.borrowable, _title(entry))),
    Order("preis", "günstigste zuerst", _by_price),
    Order(
        "neu",
        "zuletzt hinzugefügt",
        lambda entry: (_newest_first(entry.added_at), _title(entry)),
    ),
)

SUGGESTIONS: tuple[Order, ...] = (
    # Die bisherige Reihenfolge des Stapels, jetzt mit Namen: das Beste zuerst,
    # Unbewertetes ans Ende — es ist keine Empfehlung, sondern eine offene Frage.
    Order(
        "sterne",
        "beste Übereinstimmung zuerst",
        # Nach Prozent, nicht nach Sternen: die Sterne fassen zusammen, die
        # Zahl ordnet (ADR 33). Ohne Urteil steht ein Fund am Ende.
        lambda item: (item.percent is None, -(item.percent or 0), _title(item)),
    ),
    Order("frei", "ausleihbar zuerst", lambda item: (not item.borrowable, _title(item))),
    Order(
        "anlass",
        "Autor:in vor Thema",
        # Dieselbe Unterscheidung wie die Filterpillen darüber, nur ordnend
        # statt wegwerfend: der Kanal, den die Leserin selbst gewählt hat,
        # steht vor dem Regal, dem noch niemand zugestimmt hat.
        lambda item: (str(item.reason) != "profile_author", _title(item)),
    ),
    Order("preis", "günstigste zuerst", _by_price),
    Order(
        "neu",
        "zuletzt gesehen",
        lambda item: (_newest_first(item.observed_at), _title(item)),
    ),
)


OWNED: tuple[Order, ...] = (
    # Meine Bücher (#71): ein Bestand, keine Aufgabe — also alphabetisch zuerst,
    # und hier ist der Titel eine eigene Wahl, weil er die Voreinstellung ist.
    Order("titel", "Titel A–Z", lambda book: (_title(book),)),
    Order("autor", "Autor:in A–Z", lambda book: ((book.author or "").casefold(), _title(book))),
    Order("neu", "zuletzt vermerkt", lambda book: (_newest_first(book.since), _title(book))),
    Order(
        "sterne",
        "beste Übereinstimmung zuerst",
        lambda book: (book.percent is None, -(book.percent or 0), _title(book)),
    ),
)


def resolve(orders: tuple[Order, ...], slug: str | None) -> Order:
    """Der gemeinte Schlüssel — die Voreinstellung, wenn die Adresse Unsinn nennt.

    Nie ein Fehler: eine unbekannte Sortierung ist ein Tippfehler in der
    Adresse, kein Grund, die Liste zu verweigern (ADR 7).
    """
    for order in orders:
        if order.slug == slug:
            return order
    return orders[0]


def chosen(orders: tuple[Order, ...], slug: str | None) -> tuple[Order, str]:
    """Der geltende Schlüssel — und was davon in eine Adresse gehört.

    Das Zweite ist leer, solange die Voreinstellung gilt: sie wirkt ohnehin,
    und ein `?sortiert=offen` an jedem Verweis der Seite wäre Lärm. Eine
    Stelle für beide Listen, damit die Regel nicht an zwei Orten steht und an
    einem davon veraltet.
    """
    order = resolve(orders, slug)
    return order, ("" if order is orders[0] else order.slug)


def apply(orders: tuple[Order, ...], rows: Iterable[Any], slug: str | None) -> list:
    """Die Zeilen in der gewählten Reihenfolge."""
    return sorted(rows, key=resolve(orders, slug).key)
