"""Deine Sicht: was die Leserin zu einem gelesenen Buch sagt (#79).

Die Gründe stehen im Beutel ihrer Bewertung (``liked`` oder ``disliked``),
unter ``reasons``, je eine Liste von Familien (``relations.REASON_KINDS``):

- ``add``: was dem Steckbrief fehlt und das Buch für sie ausmachte;
- ``drop``: was der Steckbrief nennt, für sie aber nicht stimmt;
- ``here``: was sie nur an diesem Buch gestört hat (*nur hier* beim
  Gegengewicht, in der Erstaufnahme wie beim Nachschärfen).

Eine Stelle für Buchseite, Erstaufnahme und Urteil: vorher lasen und schrieben
drei Module den Beutel je auf eigene Art, und zwei verstanden *nur hier*
verschieden.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime

from .relations import REASON_KINDS
from .store import Store


def parse(details: str | None) -> tuple[dict, dict[str, list[str]]]:
    """Der Beutel und die Gründe darin; beides leer, wenn der Beutel kaputt ist."""
    try:
        bag = json.loads(details or "{}")
    except (TypeError, ValueError):
        return {}, {}
    if not isinstance(bag, dict):
        return {}, {}
    reasons = bag.get("reasons")
    if not isinstance(reasons, dict):
        return bag, {}
    return bag, {
        k: [f for f in v if isinstance(f, str)]
        for k, v in reasons.items()
        if k in REASON_KINDS and isinstance(v, list)
    }


def not_counted(reasons: dict[str, list[str]]) -> tuple[str, ...]:
    """Was beim Lernen der Geschmacksform an diesem Buch nicht zählt."""
    return tuple(dict.fromkeys([*reasons.get("drop", ()), *reasons.get("here", ())]))


def of(store: Store, slug: str, book_id: int, kind: str) -> tuple[dict, dict[str, list[str]]]:
    relation = next(
        (r for r in store.relations_of(slug, book_id) if r.kind == kind and r.active), None
    )
    return parse(relation.details if relation is not None else None)


def keep(
    store: Store,
    slug: str,
    book_id: int,
    kind: str,
    bag: dict,
    reasons: dict[str, list[str]],
    *,
    now: datetime,
) -> None:
    """Die Gründe in den Beutel schreiben; leere Listen fallen weg."""
    kept = {k: list(dict.fromkeys(reasons[k])) for k in REASON_KINDS if reasons.get(k)}
    if kept:
        bag["reasons"] = kept
    else:
        bag.pop("reasons", None)
    store.set_relation_details(slug, book_id, kind, bag, now=now)


def mark_only_here(
    store: Store, slug: str, book_id: int, kind: str, families: Iterable[str], *, now: datetime
) -> None:
    """*Nur hier*: die Familien zählen gegen nichts, auch nicht beim Lernen."""
    families = list(families)
    if not families:
        return
    bag, reasons = of(store, slug, book_id, kind)
    reasons["here"] = [*reasons.get("here", ()), *families]
    keep(store, slug, book_id, kind, bag, reasons, now=now)


def unmark(
    store: Store, slug: str, book_id: int, kind: str, families: Iterable[str], *, now: datetime
) -> None:
    """Die Familien zählen wieder: sie wurden eben ein Gegengewicht, also hat
    das Buch sie für sie getragen, und nicht nur hier."""
    families = set(families)
    bag, reasons = of(store, slug, book_id, kind)
    if not any(set(reasons.get(k, ())) & families for k in ("drop", "here")):
        return
    for k in ("drop", "here"):
        reasons[k] = [f for f in reasons.get(k, ()) if f not in families]
    keep(store, slug, book_id, kind, bag, reasons, now=now)
