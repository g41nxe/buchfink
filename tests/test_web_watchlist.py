"""Die Watchlist verwalten — das erste schreibende Bild (Ticket 06)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_profile
from ebook_watchlist.models import LinkOutcome, MatchReason, Observation
from ebook_watchlist.ratings import BY_MODEL
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app, sorting
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
    assert 'aria-label="fortsetzen"' in body


# --- die vier Zeichen der Zeile (#22) ---------------------------------------


def test_the_row_offers_four_actions_instead_of_a_menu(client: TestClient) -> None:
    """Dieselben Zeichen wie auf der Vorschlagsseite, nur zwei mehr: das Menue
    verbarg, was man tun kann, und niemand oeffnet es zum Nachsehen."""
    body = client.get("/watchlist").text

    for label in ("Ausschließen", "Hab ich", "jetzt nachsehen", "pausieren"):
        assert f'aria-label="{label}"' in body
    assert "ic-dots" not in body


def test_a_paused_entry_offers_resuming_instead_of_pausing(
    client: TestClient, db: Store
) -> None:
    book = db.books()[0]
    client.post(f"/watchlist/{book.id}/active", data={"active": "0"})

    body = client.get("/watchlist").text

    assert 'aria-label="fortsetzen"' in body
    assert "ic-play" in body


def test_finishing_an_entry_offers_to_take_it_back(client: TestClient, db: Store) -> None:
    """Kein Dialog vorher, ein Weg zurueck danach — wie auf der Startseite
    (ADR 30)."""
    book = db.books()[0]

    body = client.post(
        f"/watchlist/{book.id}/abschliessen", data={"kind": str(RelationKind.OWNED)}
    ).text

    assert book.title in body
    assert "Rückgängig" in body


def test_taking_a_finished_entry_back_puts_it_on_the_list_again(
    client: TestClient, db: Store
) -> None:
    book = db.books()[0]
    client.post(f"/watchlist/{book.id}/abschliessen", data={"kind": str(RelationKind.OWNED)})

    client.post(
        "/watchlist/zuruecknehmen",
        data={"book_id": str(book.id), "kind": str(RelationKind.OWNED)},
    )

    watching = db.relations("test", kind=str(RelationKind.WATCHING))
    assert book.id in {row.book_id for row in watching}
    owned = db.relations("test", kind=str(RelationKind.OWNED))
    assert book.id not in {row.book_id for row in owned}


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


# --- je Quellenart ein Zeichen mit Zahl (#35) -------------------------------


def zustand(name: str, art: str, gefunden: bool = True) -> view.SourceState:
    return view.SourceState(
        name=name,
        outcome=str(LinkOutcome.LINKED if gefunden else LinkOutcome.NOT_FOUND),
        url=f"https://{name}.invalid/1" if gefunden else None,
        matched_title=None,
        matched_author=None,
        reason="",
        category=art,
        display=name.capitalize(),
    )


def test_two_libraries_become_one_symbol_with_a_count() -> None:
    """Acht Zeichen in einer Zeile sind kein Ueberblick mehr, sondern ein
    Muster — und welche Bibliothek welches ist, sieht man ohnehin nicht."""
    gruppen = view.source_groups(
        (zustand("onleihe", "library", gefunden=False),
         zustand("overdrive", "library"),
         zustand("beam", "shop"))
    )

    assert [(g.category, g.count, g.found) for g in gruppen] == [
        ("library", 2, True), ("shop", 1, True)]


def test_a_category_nobody_found_stays_dull() -> None:
    gruppen = view.source_groups(
        (zustand("onleihe", "library", gefunden=False),
         zustand("overdrive", "library", gefunden=False))
    )

    assert gruppen[0].found is False


def test_the_symbol_links_to_the_source_that_has_it() -> None:
    """Eine Quelle hat es: dorthin fuehrt der Klick. Mehrere: die Erste von
    ihnen, denn eine Zeile hat nur ein Ziel."""
    gruppen = view.source_groups(
        (zustand("onleihe", "library", gefunden=False), zustand("overdrive", "library"))
    )

    assert gruppen[0].url == "https://overdrive.invalid/1"


def test_the_hint_names_every_source_of_the_category() -> None:
    """Die Zahl sagt wie viele, der Hinweis welche."""
    gruppen = view.source_groups(
        (zustand("onleihe", "library", gefunden=False), zustand("overdrive", "library"))
    )

    assert gruppen[0].hint == "Overdrive: gefunden · Onleihe: nicht im Katalog"


# --- die Bewertung in der Zeile (#16) ---------------------------------------


def test_the_row_carries_the_judgement_of_the_gate(client: TestClient, db: Store) -> None:
    """Dieselbe Spalte wie im Stapel: Sterne und Pitch aus dem Urteil des
    Werkzeugs. Die Zeile sagte bisher nur, was ein Buch kostet — nicht, ob es
    sich lohnt."""
    book = db.books()[0]
    db.append(
        db.start_run("test", "cli", NOW),
        "test",
        [Observation(source="beam", source_item_id="1", title=book.title,
                     match_reason=MatchReason.WATCHLIST, book_id=book.id,
                     isbn="9783000000042", price_cents=999, observed_at=NOW)],
        NOW,
    )
    db.put_rating("isbn:9783000000042", stars=4, confidence="belegt",
                  reason="Passt zum Profil.", profile_version=3, now=NOW,
                  origin=BY_MODEL, pitch="Ein Forscher, 1977 tief in einer Mine.")

    eintrag = next(e for e in view.entries(db, load_profile()) if e.book_id == book.id)

    assert eintrag.stars == 4
    assert eintrag.pitch == "Ein Forscher, 1977 tief in einer Mine."
    assert "Ein Forscher" in client.get("/watchlist").text


def test_a_title_nobody_judged_shows_no_stars(db: Store) -> None:
    """Null Sterne waeren eine Aussage, "noch nicht bewertet" ist keine."""
    eintrag = view.entries(db, load_profile())[0]

    assert eintrag.stars is None
    assert eintrag.pitch is None


# --- sortieren (#37) --------------------------------------------------------


def test_the_list_offers_every_sort_key(client: TestClient) -> None:
    """Ein Auswahlfeld, und darin stehen die Schluessel mit ihrer Richtung."""
    body = client.get("/watchlist").text

    assert "Sortiert nach" in body
    for order in sorting.WATCHLIST:
        assert order.label in body


def test_the_address_decides_the_order(client: TestClient, db: Store) -> None:
    alt = view.add(db, "test", title="Zuerst da", author=None, now=datetime(2026, 1, 1))
    neu = view.add(db, "test", title="Eben erst", author=None, now=datetime(2026, 9, 1))
    assert alt != neu

    body = client.get("/watchlist?sortiert=neu").text

    assert body.index("Eben erst") < body.index("Zuerst da")


def test_the_chosen_order_is_the_one_the_field_shows(client: TestClient) -> None:
    """Sonst sortiert die Seite nach dem einen und behauptet das andere."""
    body = client.get("/watchlist?sortiert=preis").text
    assert 'value="preis" selected' in body


def test_an_unknown_order_falls_back_instead_of_failing(client: TestClient) -> None:
    """Ein Tippfehler in der Adresse ist kein Grund, die Liste zu verweigern
    (ADR 7)."""
    antwort = client.get("/watchlist?sortiert=gibtsnicht")

    assert antwort.status_code == 200
    assert f'value="{sorting.WATCHLIST[0].slug}" selected' in antwort.text


def test_the_filter_for_open_assignments_keeps_the_order(
    client: TestClient, db: Store
) -> None:
    """Ein Filter wirft die Reihenfolge nicht weg."""
    book = db.books()[0]
    db.put_book_source(
        book.id, "beam", outcome=str(LinkOutcome.UNSURE), resolved_at=NOW,
        matched_title="Irgendwas", url="https://beam.invalid/1",
    )

    body = client.get("/watchlist?sortiert=preis").text

    assert "nur=unklar" in body
    assert "sortiert=preis" in body


def test_the_default_order_stays_out_of_the_links(client: TestClient) -> None:
    """`?sortiert=offen` an jedem Verweis waere Laerm: die Voreinstellung gilt
    ohnehin."""
    assert "sortiert=offen" not in client.get("/watchlist").text
