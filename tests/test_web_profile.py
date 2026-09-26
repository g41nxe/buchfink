"""Die Profilübersicht — ausdrücklich nur lesend (Ticket 09)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.relations import InterestKey, RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app
from ebook_watchlist.web import profile_page as view

NOW = datetime(2026, 9, 4, 22, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def test_interests_are_grouped_by_kind(client: TestClient, db: Store) -> None:
    db.put_interest("test", str(InterestKey.AUTHOR), "Chris Carter", now=NOW, tier="core")
    db.put_interest(
        "test", str(InterestKey.GENRE_CATEGORY),
        "belletristik/krimi-thriller/psychothriller", now=NOW, tier="core",
    )

    body = client.get("/profile").text

    assert "Chris Carter" in body
    assert "Psychothriller" in body


def test_a_weekly_author_says_so(client: TestClient, db: Store) -> None:
    """core wird jeden Lauf gefegt, extended einmal die Woche."""
    db.put_interest("test", str(InterestKey.AUTHOR), "Dave Eggers", now=NOW, tier="extended")
    assert "wöchentlich" in client.get("/profile").text


def test_a_theme_shows_its_readable_name_not_the_shop_path(
    client: TestClient, db: Store
) -> None:
    db.put_interest(
        "test", str(InterestKey.GENRE_CATEGORY),
        "belletristik/horror-mystery/horror-mystery-allgemein", now=NOW,
    )
    body = client.get("/profile").text
    assert "Horror &amp; Mystery" in body or "Horror & Mystery" in body


def test_the_thresholds_are_stated(client: TestClient) -> None:
    body = client.get("/profile").text
    assert "5,00 €" in body
    assert "10,00 €" in body
    assert "25 %" in body


def test_an_overdue_sweep_says_so(db: Store) -> None:
    """Ein Lauf, der nie stattfand, darf keine ganze Woche kosten (ADR 4)."""
    db.set_state("test", view.EXTENDED_SWEEP_KEY, NOW - timedelta(days=9))
    assert "überfällig" in view.build(db, load_settings()).next_sweep


def test_a_sweep_that_just_ran_names_the_day(db: Store) -> None:
    db.set_state("test", view.EXTENDED_SWEEP_KEY, datetime.now())
    assert "überfällig" not in view.build(db, load_settings()).next_sweep


def test_the_counts_cover_every_relation(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    db.put_relation("test", book.id, str(RelationKind.OWNED), now=NOW)

    body = client.get("/profile").text

    for label in ("in Beobachtung", "im Besitz", "Mag ich", "Kein Interesse",
                  "Ausgeschlossen"):
        assert label in body


def test_the_old_prose_profile_and_the_scheme_text_are_gone(client: TestClient) -> None:
    """Seit #52 zeigt die Seite nur noch das Profil aus der Datenbank: den alten
    Prosa-Text, den Verweis auf den Skill und die Rohfassung des Schemas gibt es
    nicht mehr."""
    body = client.get("/profile").text

    assert "Das Bewertungsschema" not in body
    assert "leseprofil-schaerfen" not in body
    assert "Die Figur trägt alles" not in body
    assert "Profilversion" not in body


def test_the_gate_threshold_is_stated(client: TestClient) -> None:
    """Die Schwelle ist ein Wert des Schemas und lässt sich nach den ersten
    echten Funden verstellen — sonst stünde sie nirgends (#52)."""
    body = client.get("/profile").text

    assert "Vorschläge" in body and "Sternen" in body


def test_no_write_route_exists_for_the_profile(client: TestClient) -> None:
    """Die Entscheidung steht im Ticket, also gehört sie geprüft."""
    app = create_app()
    writable = [
        route.path
        for route in app.routes
        if getattr(route, "methods", set()) - {"GET", "HEAD"}
    ]
    assert not any(path.startswith("/profile") for path in writable)


# --- die Bücher hinter den Zahlen (Ticket 49) -------------------------------


def owned_book(db: Store, title: str, author: str = "Wer Auch Immer") -> int:
    book = db.find_or_create_book(isbn=None, title=title, author=author, now=NOW)
    db.put_relation(load_settings().slug, book.id, str(RelationKind.OWNED), now=NOW)
    return book.id


def test_a_count_carries_the_books_behind_it(client: TestClient, db: Store) -> None:
    """Bis Ticket 49 stand hier nur eine Zahl. Seit Ticket 48 verlässt etwas die
    Watchlist — ohne diesen Rückweg wäre es nur über seine Nummer zu finden."""
    book_id = owned_book(db, "Cold Eternity", "S.A. Barnes")

    body = client.get("/profile").text

    assert "Cold Eternity" in body
    assert f'/book/{book_id}"' in body


def test_the_number_still_says_how_many(client: TestClient, db: Store) -> None:
    owned_book(db, "Cold Eternity")
    owned_book(db, "Providence")

    shelf = next(r for r in view.build(db, load_settings()).counts if r.kind == "owned")

    assert shelf.count == 2
    assert [b.title for b in shelf.books] == ["Cold Eternity", "Providence"]


def test_an_empty_shelf_cannot_be_opened(client: TestClient, db: Store) -> None:
    """Ein Regal ohne Bücher aufzuklappen zeigt nichts — der Knopf ist dann aus."""
    body = client.get("/profile").text

    assert "disabled" in body


def test_the_shelves_stay_read_only(client: TestClient, db: Store) -> None:
    """Die fünf Knöpfe stehen auf der Buchseite. Eine dritte Stelle, an der
    Beziehungen geschrieben werden, wäre eine zu viel (Ticket 49)."""
    owned_book(db, "Cold Eternity")

    body = client.get("/profile").text

    assert "<form" not in body


def test_a_relation_to_a_vanished_book_is_skipped(client: TestClient, db: Store) -> None:
    """Eine Beziehung ohne Buch-Zeile darf die Seite nicht sprengen."""
    book_id = owned_book(db, "Verschwunden")
    with db.session() as session:
        from ebook_watchlist.store import BookRow

        session.delete(session.get(BookRow, book_id))
        session.commit()

    shelf = next(r for r in view.build(db, load_settings()).counts if r.kind == "owned")

    assert shelf.count == 0


def test_one_counterweight_in_two_spellings_is_one_line() -> None:
    """„witzig · nur bei Cosy" und „witzig · nur bei Cozy" sind eine Sache in
    zwei Schreibweisen — auf der Seite eine Pille (26.09.2026)."""
    lines = (
        view.FacetLine("witzig", ("x",), genre="Cosy"),
        view.FacetLine("witzig", ("x",), genre="Cozy"),
        view.FacetLine("witzig", ("y",)),
        view.FacetLine("große Welt", ("z",), genre="Fantasy", book_id=4),
    )

    merged = view.merge_genres(lines)

    assert [(m.name, m.genre) for m in merged] == [
        ("witzig", "Cosy / Cozy"), ("witzig", None), ("große Welt", "Fantasy")]
    assert merged[2].book_id == 4
