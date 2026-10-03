"""Eine beobachtete Reihe fegen: je Quelle, unter ihrer eigenen Adresse (ADR 35, #85).

Keine Anfrage geht ins Netz: OverDrive und beam antworten aus Stubs, die
Onleihe aus der Reihenliste „Die sieben Schwestern" vom 03.10.2026.
"""

from __future__ import annotations

import json

from conftest import onleihe_fixture, overdrive_fixture
from ebook_watchlist.sources.beam import parse as beam_parse
from ebook_watchlist.sources.beam.source import BeamSource
from ebook_watchlist.sources.onleihe.source import OnleiheSource
from ebook_watchlist.sources.overdrive.source import OverdriveSource


class StubClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.requests.append((url, params))
        return self.text


def test_overdrive_sweeps_a_series_by_its_number() -> None:
    """Die ganze Reihe auf einmal, ausgeliehene Bände eingeschlossen — auf der
    Watchlist zählt auch, was gerade verliehen ist."""
    item = json.loads(overdrive_fixture("collection-lucky-day.json"))
    reckless = next(i for i in item["items"] if i["title"] == "Steinernes Fleisch")
    client = StubClient(json.dumps({"items": [reckless], "totalItems": 1}))

    (found,) = OverdriveSource(client=client).by_series("Reckless", "Cornelia Funke", "1817267")

    url, params = client.requests[0]
    assert params["seriesId"] == "1817267"
    assert "showOnlyAvailable" not in params
    assert (found.title, found.series_index) == ("Steinernes Fleisch", "1")


def test_without_an_address_a_source_is_not_asked() -> None:
    client = StubClient("")

    assert OverdriveSource(client=client).by_series("Reckless", "Cornelia Funke", None) == []
    assert OnleiheSource(client).by_series("Reckless", "Cornelia Funke", None) == []
    assert client.requests == []


def test_the_onleihe_sweeps_its_series_list() -> None:
    """Nur E-Books, auch verliehene; der Band steht im Untertitel der Karte."""
    client = StubClient(onleihe_fixture("series-list.html"))

    found = OnleiheSource(client).by_series("Die sieben Schwestern", "Lucinda Riley", "1730790992")

    assert "simpleMediaList,0-0-0-109-0-0-0-0-0-1730790992-0.html" in client.requests[0][0]
    assert sorted((f.title, f.series_index) for f in found) == [
        ("Atlas - Die Geschichte von Pa Salt", "8"),
        ("Die sieben Schwestern", "1"),
        ("Die verschwundene Schwester", "7"),
    ]
    assert all(f.isbn and f.series == "Die sieben Schwestern" for f in found)


def tile(product_id: str, title: str, author: str, subtitle: str | None = None) -> beam_parse.Tile:
    return beam_parse.Tile(product_id=product_id, order_number=f"978300000{product_id:0>4}",
                           title=title, author=author, price_cents=999,
                           url=f"https://beam.invalid/{product_id}", subtitle=subtitle)


def test_beam_keeps_only_titles_of_the_series_by_its_author() -> None:
    """beam hat keine Reihenseite: gesucht wird der Name, behalten nur, was von
    derselben Autor:in ist und die Reihe im Titel trägt — sonst stünde ihr
    halbes Werk auf der Watchlist."""

    class Beam(BeamSource):
        def search(self, query, page_size=0, page=None):
            self.asked = query
            return [
                tile("1", "Wayward Pines: Ausbruch", "Blake Crouch"),
                tile("2", "Psychose", "Blake Crouch", subtitle="Wayward Pines 1"),
                tile("3", "Dark Matter", "Blake Crouch"),
                tile("4", "Wayward Pines: Fanbuch", "Jemand Anderes"),
            ]

    beam = Beam(client=StubClient(""))  # type: ignore[arg-type]

    found = beam.by_series("Ein Wayward-Pines-Thriller", "Blake Crouch", None)

    assert beam.asked == "Wayward Pines"
    assert sorted(f.title for f in found) == ["Psychose", "Wayward Pines: Ausbruch"]
