"""Der Lauf liest seine Konfiguration aus der Datenbank (Ticket 05, ADR 10)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ebook_watchlist.config import Seed, Settings, WatchlistEntry
from ebook_watchlist.configuration import NotSeeded, load
from ebook_watchlist.diff import suppress_unseeded_interests
from ebook_watchlist.models import Delta, DeltaKind, MatchReason, Observation
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.run import EXIT_CONFIG_ERROR
from ebook_watchlist.run import main as run_main
from ebook_watchlist.seed import sow
from ebook_watchlist.store import Store

NOW = datetime(2026, 9, 4, 21, 0)
SETTINGS = Settings(slug="t", name="Test", strong_deal_max_cents=400)


def test_an_empty_database_says_so_rather_than_falling_back(store: Store) -> None:
    """Ein stiller Rückfall auf YAML hieße, monatelang gegen eine Datei zu
    laufen, von der alle annehmen, sie sei abgelöst."""
    with pytest.raises(NotSeeded, match="seed"):
        load(store, SETTINGS)


def test_the_watchlist_comes_from_relations(store: Store) -> None:
    sow(
        store,
        Settings(slug="t", name="Test"),
        Seed(),
        [WatchlistEntry(title="Blindflug", author="Peter Watts", notes="düster")],
        now=NOW,
    )
    configured = load(store, SETTINGS)

    assert [(e.title, e.author) for e in configured.watchlist] == [
        ("Blindflug", "Peter Watts")
    ]
    assert configured.watchlist[0].notes == "düster"


def test_a_deactivated_relation_is_not_watched_any_more(store: Store) -> None:
    sow(
        store, Settings(slug="t", name="T"), Seed(), [WatchlistEntry(title="Providence")], now=NOW
    )
    book = store.books()[0]
    store.deactivate_relation("t", book.id, str(RelationKind.WATCHING), now=NOW)

    with pytest.raises(NotSeeded):
        load(store, SETTINGS)


def test_a_restriction_survives_the_round_trip(store: Store) -> None:
    sow(
        store,
        Settings(slug="t", name="T"),
        Seed(),
        [WatchlistEntry(title="Providence", author="Max Barry", check_shop=False)],
        now=NOW,
    )
    entry = load(store, SETTINGS).watchlist[0]

    assert (entry.check_library, entry.check_shop) == (True, False)


def test_interests_become_the_two_author_lists(store: Store) -> None:
    sow(
        store,
        Settings(slug="t", name="T"),
        Seed(
            reference_authors=["Chris Carter"],
            extended_authors=["Dave Eggers"],
            genre_categories=["belletristik/krimi-thriller/psychothriller"],
        ),
        [],
        now=NOW,
    )
    configured = load(store, SETTINGS)

    assert configured.settings.reference_authors == ["Chris Carter"]
    assert configured.settings.extended_authors == ["Dave Eggers"]
    assert configured.settings.genre_categories == [
        "belletristik/krimi-thriller/psychothriller"
    ]


def test_the_settings_that_never_were_relations_stay_from_the_file(store: Store) -> None:
    """Schwellwerte, Quellen und Kontakt haben keine Zeile in ADR 18 und
    gehören weiter in eine Datei, die man versionieren kann."""
    sow(store, Settings(slug="t", name="T"), Seed(), [WatchlistEntry(title="X")], now=NOW)

    assert load(store, SETTINGS).settings.strong_deal_max_cents == 400


def test_free_text_book_lists_become_relations(store: Store) -> None:
    """Sie sind jetzt Beziehungen.

    Frueher blieb neben der Beziehung ein gleichnamiges Feld am Profil stehen,
    das ``configuration.load`` eigens leeren musste, damit niemand gegen eine
    veraltete YAML-Kopie arbeitete. Seit #36 gibt es das Feld nicht mehr: die
    Buchlisten stehen allein im Saatgut, und das gilt nur beim Import.
    """
    sow(
        store,
        Settings(slug="t", name="T"),
        Seed(
            liked_books=["Cry Baby - Gillian Flynn"],
            # Ohne ein Interesse gaebe es nichts zu tun, und der Lauf
            # verweigerte zu Recht.
            reference_authors=["Chris Carter"],
        ),
        [],
        now=NOW,
    )
    assert store.relations("t", kind=str(RelationKind.LIKED))
    assert not hasattr(load(store, SETTINGS).settings, "liked_books")


# --- Aussaat pro Interesse --------------------------------------------------


def discovery(item_id: str) -> Observation:
    return Observation(
        source="beam",
        source_item_id=item_id,
        title="Ein Fund",
        match_reason=MatchReason.PROFILE_AUTHOR,
        price_cents=199,
    )


def first_seen(observation: Observation) -> Delta:
    return Delta(DeltaKind.FIRST_SEEN, observation, None)


def test_a_second_author_no_longer_floods(store: Store) -> None:
    """Der behobene Fehler: alle Autor:innen teilten sich eine Aussaat, also
    säte die erste still an und jede weitere meldete ihre ganze Backlist."""
    carter, nesbo = discovery("a"), discovery("b")
    origin = {carter.key: 1, nesbo.key: 2}
    deltas = [first_seen(carter), first_seen(nesbo)]

    # Nur Interesse 1 wurde schon einmal gefegt.
    kept = suppress_unseeded_interests(deltas, origin, seeded={("beam", 1)})

    assert [delta.current.source_item_id for delta in kept] == ["a"]


def test_a_find_without_a_known_origin_passes(store: Store) -> None:
    """Das ist ein Watchlist-Treffer, und der hat keine Aussaat."""
    watched = Observation(
        source="beam",
        source_item_id="w",
        title="Beobachtet",
        match_reason=MatchReason.WATCHLIST,
    )
    deltas = [first_seen(watched)]
    assert suppress_unseeded_interests(deltas, {}, seeded=set()) == deltas


# --- durch den ganzen Lauf --------------------------------------------------


def test_a_fresh_install_refuses_to_run_and_names_the_command(
    unseeded_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main([]) == EXIT_CONFIG_ERROR
    assert "seed" in capsys.readouterr().err


def test_after_seeding_the_run_works(data_dir: Path) -> None:
    from ebook_watchlist.run import EXIT_OK

    assert run_main([]) == EXIT_OK
