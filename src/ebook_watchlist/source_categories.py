"""Die gesammelten Quellkategorien als Liste (#92, `ebw categories`).

Je Kategorie eine Zeile: Quelle, Nummer, Name, wie oft, wann zuletzt, ein
Beispieltitel — und ob die Nummer schon in der Genre-Tabelle der Quelle steht.
Eingetragen wird von Hand in ``<quelle>/selectors.GENRES``; die Liste zeigt,
was noch fehlt.
"""

from __future__ import annotations

from collections.abc import Iterable

from .store import Store


def report(store: Store, sources: Iterable) -> list[str]:
    rows = store.source_categories()
    if not rows:
        return ["Noch keine Quellkategorien gesammelt."]
    mapped: dict[str, dict[str, list[str]]] = {}
    for source in sources:
        for code, address in getattr(source, "genre_addresses", {}).items():
            mapped.setdefault(source.name, {}).setdefault(str(address), []).append(code)
    name_width = max(len(row.name) for row in rows)
    lines = []
    for row in rows:
        codes = mapped.get(row.source, {}).get(row.number)
        example = f"z. B. „{row.example}“" if row.example else ""
        lines.append(
            f"{row.source} {row.number:>6} {row.name:<{name_width}}  {row.count:>4}×  "
            f"zuletzt {row.last_seen:%d.%m.%Y}  "
            f"{'→ ' + ', '.join(codes) if codes else '—'}  {example}".rstrip()
        )
    return lines
