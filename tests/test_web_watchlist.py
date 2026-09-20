"""Die Watchlist verwalten — das erste schreibende Bild (Ticket 06)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_profile
from ebook_watchlist.models import LinkOutcome
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app
from ebook_watchlist.web import watchlist as view

NOW = datetime(2026, 9, 4, 20, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    # follow_redirects, weil jede Schreibaktion auf die Liste zurueckleitet.
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


# --- die Liste --------------------------------------------------------------


def test_the_watched_books_are_listed(client: TestClient) -> None:
    body = client.get("/watchlist").text
    assert "Die sieben Schwestern" in body


def test_the_page_is_reachable_from_the_dashboard(client: TestClient) -> None:
    """Eine Seite ohne Weg dorthin ist keine Seite."""
    assert '/watchlist' in client.get("/uebersicht").text


# --- aufnehmen --------------------------------------------------------------


def test_a_book_can_be_added_by_title_and_author(client: TestClient, db: Store) -> None:
    client.post("/watchlist/add", data={"title": "Providence", "author": "Max Barry"})

    titles = {book.title for book in db.books()}
    assert "Providence" in titles


def test_adding_does_not_search_the_sources(client: TestClient, db: Store) -> None:
    """Die Oberflaeche scrapt nie (ADR 3). Sie schreibt die Beziehung; der
    naechste Lauf sucht das Buch — und bis dahin sagt die Seite das."""
    body = client.post(
        "/watchlist/add", data={"title": "Providence", "author": "Max Barry"}
    ).text

    book = next(b for b in db.books() if b.title == "Providence")
    assert db.book_sources(book.id) == []
    assert "noch nicht gesucht" in body


def test_an_empty_title_is_refused_quietly(client: TestClient, db: Store) -> None:
    before = len(db.books())
    client.post("/watchlist/add", data={"title": "   ", "author": "Wer auch immer"})
    assert len(db.books()) == before


def test_adding_the_same_book_twice_does_not_duplicate_it(
    client: TestClient, db: Store
) -> None:
    for _ in range(2):
        client.post("/watchlist/add", data={"title": "Providence", "author": "Max Barry"})
    assert [b.title for b in db.books()].count("Providence") == 1


# --- pausieren und fortsetzen ----------------------------------------------


def test_pausing_never_deletes(client: TestClient, db: Store) -> None:
    """Dass ein Buch einmal beobachtet wurde, ist selbst eine Auskunft (ADR 18)."""
    book = db.books()[0]

    client.post(f"/watchlist/{book.id}/active", data={"active": "0"})

    active = db.relations("test", kind=str(RelationKind.WATCHING))
    assert book.id not in {row.book_id for row in active}
    kept = [r for r in db.relations_of("test", book.id) if r.kind == RelationKind.WATCHING]
    assert kept and kept[0].active is False


def test_a_paused_entry_can_be_resumed(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    client.post(f"/watchlist/{book.id}/active", data={"active": "0"})

    client.post(f"/watchlist/{book.id}/active", data={"active": "1"})

    active = db.relations("test", kind=str(RelationKind.WATCHING))
    assert book.id in {row.book_id for row in active}


def test_a_paused_entry_still_shows_on_the_page(client: TestClient, db: Store) -> None:
    """Sonst waere Pausieren von Loeschen nicht zu unterscheiden."""
    book = db.books()[0]
    client.post(f"/watchlist/{book.id}/active", data={"active": "0"})

    body = client.get("/watchlist").text
    assert book.title in body
    assert "aktivieren" in body


# --- auf eine Art Quelle einschraenken --------------------------------------


def test_an_entry_can_be_restricted_to_one_kind_of_source(
    client: TestClient, db: Store
) -> None:
    book = db.books()[0]

    client.post(f"/book/{book.id}/restrict", data={"restrict": "library"})

    relation = next(
        r for r in db.relations_of("test", book.id) if r.kind == RelationKind.WATCHING
    )
    assert '"restrict": "library"' in relation.details


def test_an_empty_restriction_means_every_source_not_none(
    client: TestClient, db: Store
) -> None:
    book = db.books()[0]
    client.post(f"/book/{book.id}/restrict", data={"restrict": "shop"})

    client.post(f"/book/{book.id}/restrict", data={"restrict": ""})

    relation = next(
        r for r in db.relations_of("test", book.id) if r.kind == RelationKind.WATCHING
    )
    assert "restrict" not in relation.details


def test_an_unknown_restriction_is_refused(client: TestClient, db: Store) -> None:
    """Jede Schreibaktion geht durch dieselbe Pruefung wie der Lader (Ticket 05)."""
    book = db.books()[0]
    response = client.post(f"/book/{book.id}/restrict", data={"restrict": "beam"})

    assert response.status_code == 500
    relation = next(
        r for r in db.relations_of("test", book.id) if r.kind == RelationKind.WATCHING
    )
    assert "beam" not in relation.details


def test_restricting_keeps_the_note(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    db.put_relation(
        "test", book.id, str(RelationKind.WATCHING), now=NOW, note="wichtig"
    )

    client.post(f"/book/{book.id}/restrict", data={"restrict": "library"})

    relation = next(
        r for r in db.relations_of("test", book.id) if r.kind == RelationKind.WATCHING
    )
    assert "wichtig" in relation.details


# --- eine unklare Zuordnung von Hand festmachen -----------------------------


def test_an_unsure_link_asks_for_a_decision(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    db.put_book_source(
        book.id,
        "beam",
        outcome=str(LinkOutcome.UNSURE),
        url="https://beam.invalid/1",
        resolved_at=NOW,
        matched_title="Die sieben Schwestern - Band 2",
        matched_author="Lucinda Riley",
        reason="zwei gleich gute Treffer",
    )

    body = client.get("/watchlist").text
    assert "Die sieben Schwestern - Band 2" in body
    # Die Karte traegt jetzt den Titel selbst; "Das ist es" gab es, als es
    # genau eine Option gab (Ticket 41).
    assert "Welches Buch ist das richtige?" in body


def test_the_question_says_which_source_is_asking(client: TestClient, db: Store) -> None:
    """Die Entscheidung gilt für *eine* Quelle: derselbe Titel kann im Shop
    richtig zugeordnet sein und in der Bibliothek offen. Ohne den Namen steht
    die Frage da, als ginge es um das Buch überhaupt."""
    book = db.books()[0]
    db.put_book_source(
        book.id,
        "onleihe",
        outcome=str(LinkOutcome.UNSURE),
        url="https://voebb.invalid/1",
        resolved_at=NOW,
        matched_title="Achtsam morden im Hier und Jetzt",
        matched_author="Dusse, Karsten",
        reason="der gesuchte Titel steckt im gefundenen",
    )

    body = client.get("/watchlist").text

    # Im Fragetext selbst, nicht irgendwo auf der Seite: die Quellenkacheln
    # nennen die Onleihe ohnehin.
    frage = body[body.index("Welches Buch ist das richtige?") :][:400]
    assert "Onleihe" in frage


def test_a_not_found_link_asks_nobody(client: TestClient, db: Store) -> None:
    """Nicht im Katalog ist eine Antwort, keine Frage — genau die Verwechslung,
    die die alte Aufmerksamkeitsliste unbrauchbar machte (Ticket 04)."""
    book = db.books()[0]
    db.put_book_source(book.id, "onleihe", outcome=str(LinkOutcome.NOT_FOUND), resolved_at=NOW)

    body = client.get("/watchlist").text
    assert "Das ist es" not in body
    assert "nicht im Katalog" in body


def test_picking_a_candidate_records_that_a_human_decided(
    client: TestClient, db: Store
) -> None:
    """``confirmed`` statt ``linked``: ein Mensch hat entschieden, keine Heuristik."""
    book = db.books()[0]
    db.put_book_source(
        book.id, "beam", outcome=str(LinkOutcome.UNSURE), resolved_at=NOW,
        matched_title="Irgendwas", url="https://beam.invalid/1",
    )

    client.post(
        f"/watchlist/{book.id}/confirm",
        data={"source": "beam", "url": "https://beam.invalid/1"},
    )

    link = db.get_book_source(book.id, "beam")
    assert '"outcome": "confirmed"' in link.details
    assert link.url == "https://beam.invalid/1"


# --- die Zusammenstellung fuer sich ----------------------------------------


def test_entries_put_the_questions_first(db: Store) -> None:
    """Was ein Mensch entscheiden muss, steht oben."""
    quiet, asking = db.books()[0], db.find_or_create_book(
        isbn=None, title="Zzz Letzter", author="Wer", now=NOW
    )
    db.put_relation("test", asking.id, str(RelationKind.WATCHING), now=NOW)
    db.put_book_source(asking.id, "beam", outcome=str(LinkOutcome.UNSURE), resolved_at=NOW)

    rows = view.entries(db, load_profile())

    assert rows[0].book_id == asking.id
    assert rows[0].needs_attention
    assert any(row.book_id == quiet.id for row in rows)


def test_an_entry_shows_the_last_price_it_was_seen_at(db: Store) -> None:
    rows = {row.title: row for row in view.entries(db, load_profile())}
    schwarm = rows.get("Der Schwarm")
    if schwarm is not None and schwarm.latest is not None:
        assert schwarm.price is not None


# --- zwei Bibliotheken, eine Zeile ------------------------------------------


def test_one_library_lending_it_out_does_not_hide_the_other_one_having_it(
    db: Store,
) -> None:
    """Die Zeile zeigte die Beobachtung mit der hoechsten id — also die der
    zuletzt eingefuegten Quelle, und das ist die Reihenfolge in `profile.yaml`.
    Mit zwei Bibliotheken entschied der Zufall, welche von beiden die Zeile
    beschreibt: sagte die eine "ausleihbar" und die andere "verliehen", stand
    dort die falsche von beiden.

    "Ausleihbar" ist eine Aussage ueber das *Buch*: hat eine der Bibliotheken
    es da, hat die Leserin es da."""
    from ebook_watchlist.models import Availability, MatchReason, Observation

    profile = load_profile()
    buch = db.find_or_create_book(isbn=None, title="Dark Matter", author="Crouch", now=NOW)
    db.put_relation(profile.slug, buch.id, str(RelationKind.WATCHING), now=NOW)

    def sichtung(quelle: str, verfuegbarkeit: Availability) -> None:
        run_id = db.start_run(profile.slug, "cli", NOW)
        db.append(
            run_id,
            profile.slug,
            [
                Observation(
                    source=quelle,
                    source_item_id="1",
                    title="Dark Matter",
                    match_reason=MatchReason.WATCHLIST,
                    book_id=buch.id,
                    availability=verfuegbarkeit,
                    observed_at=NOW,
                )
            ],
            NOW,
        )

    sichtung("onleihe", Availability.AVAILABLE)
    # Zuletzt eingefuegt, also frueher der Gewinner.
    sichtung("overdrive", Availability.UNAVAILABLE)

    zeile = next(e for e in view.entries(db, profile) if e.book_id == buch.id)

    assert zeile.availability == "ausleihbar"
    assert zeile.borrowable


def test_a_library_without_a_price_does_not_erase_the_shop_price(db: Store) -> None:
    """Eine Bibliothek nennt keinen Preis. War ihre Beobachtung die juengste,
    stand in der Zeile nichts — obwohl der Shop einen genannt hatte."""
    from ebook_watchlist.models import Availability, MatchReason, Observation

    profile = load_profile()
    buch = db.find_or_create_book(isbn=None, title="Ein Buch", author="Wer", now=NOW)
    db.put_relation(profile.slug, buch.id, str(RelationKind.WATCHING), now=NOW)

    quellen = (("beam", 499, None), ("overdrive", None, Availability.UNKNOWN))
    for quelle, preis, verfuegbar in quellen:
        run_id = db.start_run(profile.slug, "cli", NOW)
        db.append(
            run_id,
            profile.slug,
            [
                Observation(
                    source=quelle,
                    source_item_id="1",
                    title="Ein Buch",
                    match_reason=MatchReason.WATCHLIST,
                    book_id=buch.id,
                    price_cents=preis,
                    availability=verfuegbar,
                    observed_at=NOW,
                )
            ],
            NOW,
        )

    zeile = next(e for e in view.entries(db, profile) if e.book_id == buch.id)

    assert zeile.price == "4,99 €"
