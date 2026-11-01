"""Der enge Lauf lernt die ISBN wie der große (ADR 18).

Anlass (01.11.2026): neun Bände der Klingen-Saga, nach Titel und Autor:in
aufgenommen, standen nach ihrer Prüfung ohne ISBN da — beam hatte sie
gefunden und die ISBN genannt, aber nur der große Lauf trägt sie ins Buch
ein. Ohne ISBN fehlten Reihe, Wikidata und das Formular „Reihe von Hand“.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ebook_watchlist import paths, single
from ebook_watchlist.config import WatchlistEntry
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.store import Store

NOW = datetime(2026, 11, 1, 11, 9)


def test_the_narrow_run_learns_the_isbn_of_a_book_entered_by_title(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(paths.db_path())
    book = store.find_or_create_book(isbn=None, title="Friedensklingen",
                                     author="Joe Abercrombie", now=NOW)
    monkeypatch.setattr(single, "_entry_for", lambda *a, **k: WatchlistEntry(
        title="Friedensklingen", author="Joe Abercrombie"))

    class Source:
        name = "beam"

        def watch(self, entries, context):
            return [Observation(source="beam", source_item_id="623219",
                                title="Friedensklingen - Die Klingen-Saga",
                                author="Abercrombie, Joe", match_reason=MatchReason.WATCHLIST,
                                isbn="9783641164744", book_id=book.id)]

    monkeypatch.setattr(single, "build_sources", lambda settings, client: [Source()])
    monkeypatch.setattr(single, "fetch_for_candidates", lambda *a, **k: None)

    single.check_one(book.id, now=NOW)

    found = store.book(book.id)
    assert found is not None and found.isbn == "9783641164744"


def test_the_narrow_run_asks_wikidata_for_the_series(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wer von Hand neu prüft, will auch die Reihe wissen — nicht erst nach
    dem nächsten großen Lauf (ADR 45). Eine Frage je Prüfung."""
    from ebook_watchlist.wikidata import Membership

    store = Store(paths.db_path())
    book = store.find_or_create_book(isbn="9783641068806", title="Feuerklingen",
                                     author="Joe Abercrombie", now=NOW)
    monkeypatch.setattr(single, "_entry_for", lambda *a, **k: WatchlistEntry(
        title="Feuerklingen", author="Joe Abercrombie", isbn="9783641068806"))

    class Source:
        name = "beam"

        def watch(self, entries, context):
            return []

    asked: list[tuple[str, str | None]] = []

    class FakeWikidata:
        def __init__(self, client):
            pass

        def membership(self, title, author):
            asked.append((title, author))
            return Membership("Q2", "Q9", "Klingenwelt", "2")

    monkeypatch.setattr(single, "build_sources", lambda settings, client: [Source()])
    monkeypatch.setattr(single, "fetch_for_candidates", lambda *a, **k: None)
    monkeypatch.setattr(single, "Wikidata", FakeWikidata)

    single.check_one(book.id, now=NOW)

    assert asked == [("Feuerklingen", "Joe Abercrombie")]
    named = store.series_of(["9783641068806"])["9783641068806"]
    assert (named.name, named.volume) == ("Klingenwelt", "2")
