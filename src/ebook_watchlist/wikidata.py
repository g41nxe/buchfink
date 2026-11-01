"""Reihe und Band aus Wikidata (ADR 45).

Wo keine Quelle eine Reihe nennt — *Kriegsklingen* führt beam als „Die
Klingen-Saga“ ohne Band, OverDrive gar nicht, die DNB mit leerem Feld —, kennt
Wikidata sie oft: das Werk hängt über „Teil der Serie“ (P179) an der Reihe,
die Bandnummer steht als Zusatz daran (P1545). In beide Richtungen: vom Titel
zur Reihe, und von der Reihe zu ihren Bänden.

Gefragt wird über den **deutschen Titel**, nicht die ISBN: Wikidata führt
Werke, kaum Ausgaben. Angenommen wird deshalb nur genau ein Werk, dessen
Autor:in passt; alles andere gilt als „kennt Wikidata nicht“.

Ein Werk der Reihe **ohne** Band spielt in derselben Welt, ist aber keine
Fortsetzung (*Racheklingen* neben der Klingen-Trilogie) — es wird gemerkt,
aber nicht als Band abgelegt.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

from .cleaning import author_key
from .http import HttpClient

SPARQL_URL = "https://query.wikidata.org/sparql"


@dataclass(frozen=True, slots=True)
class Membership:
    """Was Wikidata zu einem Werk sagt."""

    #: Das Werk, als Q-Nummer.
    item: str
    #: Die Reihe, als Q-Nummer und mit ihrem deutschen (sonst englischen) Namen.
    series_item: str | None = None
    series_name: str | None = None
    #: Der Band; ``None`` heißt: in derselben Welt, keine Fortsetzung.
    volume: str | None = None


def _literal(text: str) -> str:
    """Ein Titel als SPARQL-Zeichenkette."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def membership_query(title: str) -> str:
    return (
        "SELECT ?item ?authorLabel ?series ?seriesLabel ?ord WHERE { "
        f"?item rdfs:label {_literal(title)}@de . ?item wdt:P50 ?author . "
        "OPTIONAL { ?item p:P179 ?st . ?st ps:P179 ?series . "
        "OPTIONAL { ?st pq:P1545 ?ord } } "
        'SERVICE wikibase:label { bd:serviceParam wikibase:language "de,en". } }'
    )


def volumes_query(series_item: str) -> str:
    return (
        "SELECT ?item ?label ?ord WHERE { "
        f"?item p:P179 ?st . ?st ps:P179 wd:{series_item} . ?st pq:P1545 ?ord . "
        '?item rdfs:label ?label . FILTER(lang(?label) = "de") }'
    )


def _same_author(label: str, author: str | None) -> bool:
    if not author:
        return False
    mine, theirs = author_key(author), author_key(label)
    if mine == theirs:
        return True
    # „Dmitry Glukhovsky“ gegen „Dmitri Gluchowski“ trägt das nicht — aber
    # ein fehlender Mittelname soll nicht trennen: der Nachname entscheidet.
    return bool(mine) and bool(theirs) and mine.split()[-1] == theirs.split()[-1]


def parse_membership(text: str, author: str | None) -> Membership | None:
    """Genau ein Werk mit passender Autor:in, oder ``None``."""
    rows = json.loads(text).get("results", {}).get("bindings", [])
    authors: dict[str, list[str]] = defaultdict(list)
    series: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
    for row in rows:
        item = _qid(row["item"]["value"])
        authors[item].append(row.get("authorLabel", {}).get("value", ""))
        if "series" in row:
            series[item].append((
                _qid(row["series"]["value"]),
                row.get("seriesLabel", {}).get("value", ""),
                row.get("ord", {}).get("value"),
            ))
    matching = [item for item, names in authors.items()
                if any(_same_author(name, author) for name in names)]
    if len(matching) != 1:
        return None
    item = matching[0]
    found = sorted(set(series[item]), key=lambda s: s[2] is None)  # mit Band zuerst
    if not found:
        return Membership(item)
    series_item, name, volume = found[0]
    return Membership(item, series_item, name or None, volume)


def parse_volumes(text: str) -> list[tuple[str, str]]:
    """(Band, deutscher Titel) je Band der Reihe, nach Band geordnet."""
    rows = json.loads(text).get("results", {}).get("bindings", [])
    found = {(row["ord"]["value"], row["label"]["value"]) for row in rows}

    def order(entry: tuple[str, str]) -> tuple[float, str]:
        try:
            return (float(entry[0]), entry[1])
        except ValueError:
            return (float("inf"), entry[1])

    return sorted(found, key=order)


@dataclass(slots=True)
class Wikidata:
    """Fragt Wikidata — sparsam, wie die DNB: einmal je Buch, mit Budget."""

    client: HttpClient
    base: str = SPARQL_URL
    asked: int = field(default=0)

    def _ask(self, query: str) -> str:
        self.asked += 1
        return self.client.get(self.base, params={"query": query, "format": "json"})

    def membership(self, title: str, author: str | None) -> Membership | None:
        return parse_membership(self._ask(membership_query(title)), author)

    def volumes(self, series_item: str) -> list[tuple[str, str]]:
        return parse_volumes(self._ask(volumes_query(series_item)))
