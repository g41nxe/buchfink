"""Eine Zeile je Werk (ADR 42, Schritt 3).

Stapel, Startseite und Tagesbericht zeigen ein Werk einmal, auch wenn es in
mehreren Ausgaben oder bei mehreren Quellen auftaucht. Welche Ausgabe die Zeile
vertritt, entscheiden die Lesesprachen in ihrer Rangfolge, danach die Kosten
(ausleihbar vor günstig). Die anderen bleiben als „auch als …“ dabei.

Rein und ohne Store: was ein Eintrag ist, wie seine ISBN, Sprache und Kosten
heißen und welche ISBNs ein Werk bilden, kommt herein. So rechnen Stapel und
Tagesbericht mit derselben Regel.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence


def collapse[T](
    items: Iterable[T],
    *,
    isbn_of: Callable[[T], str | None],
    siblings: Mapping[str, set[str]],
    language_of: Callable[[T], str | None],
    languages: Sequence[str],
    cost: Callable[[T], tuple],
) -> list[tuple[T, list[T]]]:
    """Je Werk der vertretende Eintrag und die übrigen, in Rangfolge.

    Ohne ISBN steht ein Eintrag für sich. Die Reihenfolge der Werke folgt dem
    ersten Auftreten, damit eine Sortierung davor erhalten bleibt.
    """
    groups: dict[str, list[T]] = {}
    order: list[str] = []
    alone: list[tuple[int, T]] = []
    for position, item in enumerate(items):
        isbn = isbn_of(item)
        if not isbn:
            alone.append((position, item))
            continue
        key = min(siblings.get(isbn) or {isbn})
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    def rank(item: T) -> tuple:
        code = language_of(item)
        position = languages.index(code) if code in languages else len(languages)
        return (position, *cost(item))

    collapsed: dict[str, tuple[T, list[T]]] = {}
    for key, members in groups.items():
        ranked = sorted(members, key=rank)
        collapsed[key] = (ranked[0], ranked[1:])
    result = [collapsed[key] for key in order]
    for _, item in alone:
        result.append((item, []))
    return result
