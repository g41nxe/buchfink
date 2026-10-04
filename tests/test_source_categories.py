"""Quellkategorien sammeln: die Onleihe-Nummern aus den Detailseiten (#92)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ebook_watchlist.sources.onleihe.parse import parse_detail
from ebook_watchlist.store import Store

FIXTURES = Path(__file__).parent / "fixtures" / "onleihe"
NOW = datetime(2026, 10, 4, 12, 0)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_the_detail_page_names_its_categories() -> None:
    """Eine flache Liste unter „Kategorie:", kein Pfad — ohne die Kommas."""
    assert parse_detail(fixture("detail-unavailable.html")).categories == (
        ("2", "Belletristik & Unterhaltung"),
        ("160", "Romane & Erzählungen"),
        ("616", "Historisches"),
    )
    assert parse_detail(fixture("detail-available.html")).categories == (
        ("2", "Belletristik & Unterhaltung"),
    )


def test_the_store_counts_each_category(store: Store) -> None:
    store.note_categories("onleihe", (("155", "Krimi & Thriller"),), example="Die Spur",
                          now=NOW)
    store.note_categories("onleihe", (("155", "Krimi & Thriller"), ("185", "Kriminalkomödie")),
                          example="Mord mit Aussicht", now=datetime(2026, 10, 5))

    rows = {row.number: row for row in store.source_categories()}
    assert rows["155"].count == 2
    assert rows["155"].last_seen == datetime(2026, 10, 5)
    assert rows["155"].example == "Mord mit Aussicht"
    assert (rows["185"].name, rows["185"].count) == ("Kriminalkomödie", 1)
    assert {row.source for row in rows.values()} == {"onleihe"}


def test_gathering_evidence_notes_the_categories(data_dir: Path) -> None:
    """Die Detailseite ist für den Steckbrief ohnehin geholt — keine Anfrage mehr."""
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.evidence import gather
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.sources.base import Item

    store, settings = Store(paths.db_path()), load_settings()

    class Source:
        name = "onleihe"

        def item(self, source_item_id: str) -> Item:
            return Item(source_item_id=source_item_id, title="Die Spur",
                        categories=(("155", "Krimi & Thriller"),))

    find = Observation(source="onleihe", source_item_id="7", title="Die Spur",
                       match_reason=MatchReason.GENRE_CATEGORY)

    gather(store, settings, [find], [Source()])

    (row,) = store.source_categories()
    assert (row.source, row.number, row.name, row.example) == (
        "onleihe", "155", "Krimi & Thriller", "Die Spur")


def test_the_report_says_which_numbers_are_already_mapped(store: Store) -> None:
    from ebook_watchlist.source_categories import report

    store.note_categories("onleihe", (("155", "Krimi & Thriller"), ("185", "Kriminalkomödie")),
                          example="Die Spur", now=NOW)

    class Source:
        name = "onleihe"
        genre_addresses = {"FIC022000": "155"}

    lines = report(store, [Source()])

    (crime,) = [line for line in lines if " 155 " in line]
    (comedy,) = [line for line in lines if " 185 " in line]
    assert "Krimi & Thriller" in crime and "FIC022000" in crime and "Die Spur" in crime
    assert "Kriminalkomödie" in comedy and "FIC" not in comedy


def test_without_categories_the_report_says_so(store: Store) -> None:
    from ebook_watchlist.source_categories import report

    assert report(store, []) == ["Noch keine Quellkategorien gesammelt."]
