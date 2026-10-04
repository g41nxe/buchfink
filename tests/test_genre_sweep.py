"""Ein Thema fegen: nur wo die Quelle eine Adresse hat, angesät je Adresse (ADR 37)."""

from __future__ import annotations

from datetime import datetime

from ebook_watchlist.config import Settings
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.sources.base import RunContext, sweep_interests
from ebook_watchlist.store import Store

NOW = datetime(2026, 10, 4, 12, 0)


class Shelf:
    """Eine Quelle, die nur Thriller kennt."""

    name = "shelf"
    genre_addresses = {"FIC031000": "thriller-regal"}
    asked: list[str]

    def __init__(self) -> None:
        self.asked = []

    def genre_address(self, code: str) -> str | None:
        from ebook_watchlist.sources.base import Source

        return Source.genre_address(self, code)  # type: ignore[arg-type]

    def by_author(self, author: str) -> list[Observation]:
        return []

    def by_category(self, code: str) -> list[Observation]:
        self.asked.append(code)
        return [Observation(source=self.name, source_item_id="1", title="T",
                            match_reason=MatchReason.GENRE_CATEGORY, category=code)]

    def extra_discoveries(self) -> list[Observation]:
        return []


def sweep(store: Store, themes: list[str]) -> tuple[Shelf, RunContext]:
    for value in themes:
        store.put_interest("t", "thema", value, now=NOW)
    context = RunContext(profile_slug="t", store=store, now=NOW)
    context.interests = {("thema", row.value): row.id for row in store.interests("t")}
    shelf = Shelf()
    sweep_interests(shelf, Settings(slug="t", name="T", genre_categories=themes), context, [])
    return shelf, context


def test_a_theme_without_an_address_is_neither_asked_nor_seeded(store: Store) -> None:
    """Review 04.10.2026: vorher galt es als angesät, und kam die Adresse
    später dazu, flutete der erste Durchgang den Tagesbericht."""
    shelf, context = sweep(store, ["FIC028000"])

    assert shelf.asked == []
    assert context.swept == set()


def test_a_theme_remembers_the_address_it_was_seeded_under(store: Store) -> None:
    shelf, context = sweep(store, ["FIC031080"])
    (key,) = context.swept

    assert context.addresses[key] == "thriller-regal"
    store.mark_interest_seeded(key[1], key[0], now=NOW, address="thriller-regal")
    assert store.is_interest_seeded(key[1], key[0], address="thriller-regal")
    # Eine andere Adresse ist ein anderes Regal: dort ist noch nichts angesät.
    assert not store.is_interest_seeded(key[1], key[0], address="anderes-regal")


def test_a_theme_that_is_no_code_is_said_out_loud(store: Store, capsys) -> None:
    """Ein alter Pfad, den die Migration nicht kannte, fegt nicht mehr — das
    gehört gesagt, sonst sähe es aus wie ein ruhiger Tag."""
    shelf, _ = sweep(store, ["belletristik/irgendwas"])

    assert shelf.asked == []
    assert "belletristik/irgendwas" in capsys.readouterr().err
