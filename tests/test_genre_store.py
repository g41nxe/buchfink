"""BISAC je ISBN, mit Herkunft (ADR 37, #88)."""

from __future__ import annotations

from datetime import datetime

from ebook_watchlist.dnb import Record
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.store import Store

NOW = datetime(2026, 10, 4, 12, 0)


def seen(store: Store, *observations: Observation) -> None:
    store.append(store.start_run("t", "cli", NOW), "t", list(observations), NOW)


def at_overdrive(isbn: str, *codes: str) -> Observation:
    return Observation(source="overdrive", source_item_id=isbn[-4:], title="T", isbn=isbn,
                       bisac=codes, match_reason=MatchReason.GENRE_CATEGORY, observed_at=NOW)


def test_a_sighting_files_its_bisac_codes(store: Store) -> None:
    seen(store, at_overdrive("9783000000401", "FIC031080", "FIC031000"))

    assert store.bisac_codes(["9783000000401"]) == {
        "9783000000401": ("FIC031080", "FIC031000")}


def test_the_dnb_comes_first_and_both_are_kept(store: Store) -> None:
    """Alle Codes zählen; die der DNB stehen vorn (ADR 37)."""
    seen(store, at_overdrive("9783000000402", "FIC031000"))
    store.save_dnb("9783000000402", Record(title="T", bisac=("FIC031080",)), NOW)

    assert store.bisac_codes(["9783000000402"])["9783000000402"] == ("FIC031080", "FIC031000")


def test_a_new_answer_replaces_the_old_codes_of_its_origin(store: Store) -> None:
    store.save_dnb("9783000000403", Record(title="T", bisac=("FIC031000",)), NOW)
    store.save_dnb("9783000000403", Record(title="T", bisac=("FIC022020",)), NOW)

    assert store.bisac_codes(["9783000000403"])["9783000000403"] == ("FIC022020",)


def test_a_book_without_codes_has_none(store: Store) -> None:
    seen(store, at_overdrive("9783000000404"))

    assert store.bisac_codes(["9783000000404"]) == {}
