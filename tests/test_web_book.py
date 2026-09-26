"""Eine Seite je Buch (Ticket 07).

Die Seite, die das Modell aus ADR 18 zum ersten Mal auszahlt: dieselben
Angaben lagen vorher über vier Dateien verstreut, die einander nicht kannten.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import needs_vocabulary, portrayer_via
from ebook_watchlist import paths
from ebook_watchlist.config import Settings, load_settings
from ebook_watchlist.models import Availability, LinkOutcome, MatchReason, Observation
from ebook_watchlist.portrait import PortrayalUnavailable
from ebook_watchlist.ratings import BY_READER, book_subject
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import book as view
from ebook_watchlist.web import create_app

NOW = datetime(2026, 9, 4, 20, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def sighting(db: Store, book_id: int, *, when: datetime, price: int | None = None,
             availability: Availability | None = None, title: str = "Die sieben Schwestern",
             source: str = "beam", reservations: int | None = None,
             available_from: str | None = None) -> None:
    run_id = db.start_run("test", "cli", when)
    db.append(
        run_id,
        "test",
        [
            Observation(
                source=source,
                source_item_id="1",
                title=title,
                match_reason=MatchReason.WATCHLIST,
                book_id=book_id,
                price_cents=price,
                availability=availability,
                reservation_count=reservations,
                available_from=available_from,
                observed_at=when,
            )
        ],
        when,
    )


# --- die Seite --------------------------------------------------------------


def test_the_page_shows_the_book(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    body = client.get(f"/book/{book.id}").text
    assert book.title in body


def test_an_unknown_book_is_a_404_not_a_crash(client: TestClient) -> None:
    assert client.get("/book/9999").status_code == 404


def test_the_watchlist_links_to_it(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    assert f"/book/{book.id}" in client.get("/watchlist").text


# --- Beziehungen ------------------------------------------------------------


def test_every_relation_can_be_set_from_here(client: TestClient, db: Store) -> None:
    book = db.books()[0]

    client.post(f"/book/{book.id}/relation", data={"kind": "owned", "active": "1"})

    kinds = {row.kind for row in db.relations_of("test", book.id) if row.active}
    assert str(RelationKind.OWNED) in kinds


def test_several_relations_hold_at_once(client: TestClient, db: Store) -> None:
    """Cold Eternity ist owned *und* war watching — der Normalfall (ADR 18)."""
    book = db.books()[0]
    client.post(f"/book/{book.id}/relation", data={"kind": "owned", "active": "1"})
    client.post(f"/book/{book.id}/relation", data={"kind": "liked", "active": "1"})

    kinds = {row.kind for row in db.relations_of("test", book.id) if row.active}
    assert {"watching", "owned", "liked"} <= kinds


def test_switching_a_relation_off_keeps_it_as_history(client: TestClient, db: Store) -> None:
    """Dass ein Buch einmal beobachtet wurde, ist selbst eine Auskunft (ADR 18)
    — die Beziehung wird stillgelegt, nicht geloescht. Die Seite zeigt sie
    nicht mehr: was gerade *nicht* gilt, beantwortet keine Frage."""
    book = db.books()[0]

    client.post(f"/book/{book.id}/relation", data={"kind": "watching", "active": "0"})

    kept = [r for r in db.relations_of("test", book.id) if r.kind == "watching"]
    assert kept and kept[0].active is False


def test_an_unknown_relation_is_refused(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    response = client.post(f"/book/{book.id}/relation", data={"kind": "besitze", "active": "1"})
    assert response.status_code == 500


# --- was die Quellen sagen --------------------------------------------------


def test_a_slightly_different_title_is_not_repeated(client: TestClient, db: Store) -> None:
    """„Die sieben Schwestern / Roman" ist dasselbe Buch mit Zusatz. Bis #34
    stand es trotzdem in der Zeile und sagte, dass alles stimmt; jetzt steht
    der fremde Titel nur, wo er wirklich fremd ist (ADR 9)."""
    book = db.books()[0]
    db.put_book_source(
        book.id, "beam", outcome=str(LinkOutcome.LINKED), url="https://beam.invalid/1",
        resolved_at=NOW, matched_title="Die sieben Schwestern / Roman", matched_author="Riley",
    )

    body = client.get(f"/book/{book.id}").text
    assert "Die sieben Schwestern / Roman" not in body
    # Der Verweis haengt am Namen der Quelle, nicht an einem eigenen Wort.
    assert 'href="https://beam.invalid/1"' in body


def test_a_wildly_different_title_is_flagged(client: TestClient, db: Store) -> None:
    """Kein Urteil, nur ein Hinweis — der Vergleich entscheidet nichts."""
    book = db.books()[0]
    db.put_book_source(
        book.id, "beam", outcome=str(LinkOutcome.LINKED), resolved_at=NOW,
        matched_title="Handbuch der Gartenbewässerung",
    )

    body = client.get(f"/book/{book.id}").text
    assert "ganz anders" in body
    assert "Handbuch der Gartenbewässerung" in body


def test_a_matching_title_is_not_flagged(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    db.put_book_source(
        book.id, "beam", outcome=str(LinkOutcome.LINKED), resolved_at=NOW,
        matched_title="Die sieben Schwestern — Band 1",
    )
    assert "ganz anders" not in client.get(f"/book/{book.id}").text


# --- die Geschichte ---------------------------------------------------------


def test_a_book_nobody_has_seen_says_so(client: TestClient, db: Store) -> None:
    fresh = db.find_or_create_book(isbn=None, title="Ganz neu", now=NOW)
    body = client.get(f"/book/{fresh.id}").text
    assert "Noch nichts gesehen" in body


def test_one_price_is_not_called_a_history(client: TestClient, db: Store) -> None:
    """Ein Punkt ist kein Verlauf. Das zu sagen ist ehrlicher, als eine Linie
    zu zeichnen, die nichts zeigt.

    Der Satz nennt den Betrag und zaehlt *Preise*: vier Laeufe mit derselben
    Zahl sind vier Beobachtungen und trotzdem kein Verlauf. Vorher hiess es
    "ein Verlauf entsteht erst mit weiteren Laeufen" — darunter standen vier."""
    book = db.books()[0]
    sighting(db, book.id, when=NOW, price=999)

    body = client.get(f"/book/{book.id}").text
    assert "Immer 9,99 €" in body


def test_unchanged_prices_do_not_fill_the_list(db: Store) -> None:
    """Eine Zeile je Lauf wäre nach einem Jahr eine Wand aus derselben Zahl."""
    book = db.books()[0]
    for day in range(4):
        sighting(db, book.id, when=NOW + timedelta(days=day), price=999)
    sighting(db, book.id, when=NOW + timedelta(days=5), price=499)

    page = view.build(db, load_settings(), book.id)
    points = view.price_points(page.history)

    assert [point.price for point in points] == ["9,99 €", "4,99 €"]


def test_the_full_history_is_still_there(db: Store) -> None:
    """Zusammengefasst wird nur die Preisliste; gespeichert bleibt jede Sichtung."""
    book = db.books()[0]
    for day in range(3):
        sighting(db, book.id, when=NOW + timedelta(days=day), price=999)

    page = view.build(db, load_settings(), book.id)
    assert len(page.history) >= 3


def test_the_table_shows_the_last_five_sightings_and_says_so(
    client: TestClient, db: Store
) -> None:
    """Elf Zeilen mit elfmal demselben Betrag sind kein Verlauf, sondern
    Rauschen — und sie schoben alles darunter aus dem Bild. Was sich geaendert
    hat, steht ohnehin darueber in der Preisliste."""
    book = db.books()[0]
    for day in range(8):
        sighting(db, book.id, when=NOW + timedelta(days=day), price=900 + day)

    page = view.build(db, load_settings(), book.id)
    assert len(page.recent_history) == 5
    assert page.hidden_history == 3
    # Die neuesten fuenf, nicht die aeltesten.
    assert page.recent_history[0].price == "9,07 €"

    assert "3 ältere" in client.get(f"/book/{book.id}").text


def test_availability_appears_for_a_library(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE, source="onleihe")

    assert "ausleihbar" in client.get(f"/book/{book.id}").text


def test_the_newest_sighting_comes_first(db: Store) -> None:
    book = db.books()[0]
    sighting(db, book.id, when=NOW, price=999)
    sighting(db, book.id, when=NOW + timedelta(days=1), price=499)

    page = view.build(db, load_settings(), book.id)
    assert page.history[0].price == "4,99 €"


def test_a_bargain_is_marked_in_the_history(db: Store) -> None:
    book = db.books()[0]
    sighting(db, book.id, when=NOW, price=399)

    page = view.build(db, load_settings(), book.id)
    assert page.history[0].deal is True


# --- was der Review gefunden hat -------------------------------------------


def test_the_reader_never_sees_an_internal_source_name(client: TestClient, db: Store) -> None:
    """"onleihe" war nie ein Wort für die Leserin — und welche Quelle eine
    Bibliothek ist, sagt die Registry, nicht eine Liste in der Vorlage."""
    book = db.books()[0]
    db.put_book_source(book.id, "onleihe", outcome=str(LinkOutcome.LINKED), resolved_at=NOW)
    sighting(db, book.id, when=NOW, source="onleihe", availability=Availability.AVAILABLE)

    body = client.get(f"/book/{book.id}").text

    assert "onleihe" not in body
    assert "beam" not in body
    assert "Bibliothek" in body


def test_a_source_that_agrees_on_the_title_says_nothing(db: Store) -> None:
    """Sonst wiederholte die Spalte in jeder Zeile denselben Titel."""
    book = db.books()[0]
    sighting(db, book.id, when=NOW, title=book.title)

    page = view.build(db, load_settings(), book.id)
    assert page.history[0].other_title is None


def test_a_source_that_disagrees_is_recorded(db: Store) -> None:
    book = db.books()[0]
    sighting(db, book.id, when=NOW, title="Ganz anderer Titel")

    page = view.build(db, load_settings(), book.id)
    assert page.history[0].other_title == "Ganz anderer Titel"


def test_a_single_price_gets_a_sentence_not_a_list(client: TestClient, db: Store) -> None:
    """Bei einem Punkt stünde die Zahl sonst dreimal auf der Seite."""
    book = db.books()[0]
    sighting(db, book.id, when=NOW, price=999)

    body = client.get(f"/book/{book.id}").text
    assert "Immer 9,99 €" in body
    assert "Preisänderungen" not in body


def test_two_prices_get_the_list(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    sighting(db, book.id, when=NOW, price=999)
    sighting(db, book.id, when=NOW + timedelta(days=1), price=499)

    body = client.get(f"/book/{book.id}").text
    assert "Preisänderungen" in body


# --- wessen Sterne (Ticket 21) ----------------------------------------------


def test_a_book_without_a_judgement_shows_nothing_rather_than_zero_stars(
    client: TestClient, db: Store
) -> None:
    """Nicht bewertet und "passt überhaupt nicht" sind zwei Auskünfte."""
    book = db.books()[0]

    body = client.get(f"/book/{book.id}").text

    assert "Noch nicht bewertet" in body
    assert "zurücknehmen" not in body


def test_she_can_set_her_own_stars(client: TestClient, db: Store) -> None:
    book = db.books()[0]

    client.post(f"/book/{book.id}/stars", data={"stars": "4"})

    row = db.rating(book_subject(book.id), origin=BY_READER)
    assert row.stars == 4
    assert "zurücknehmen" in client.get(f"/book/{book.id}").text


def test_taking_them_back_writes_no_zero(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    client.post(f"/book/{book.id}/stars", data={"stars": "4"})

    client.post(f"/book/{book.id}/stars", data={"stars": ""})

    assert db.rating(book_subject(book.id), origin=BY_READER) is None
    assert "Noch nicht bewertet" in client.get(f"/book/{book.id}").text


def test_a_nonsense_star_count_is_refused(client: TestClient, db: Store) -> None:
    book = db.books()[0]

    assert client.post(f"/book/{book.id}/stars", data={"stars": "9"}).status_code == 400
    assert client.post(f"/book/{book.id}/stars", data={"stars": "vier"}).status_code == 400


# --- warum das hier steht (Ticket 22) ---------------------------------------


def discovery(db: Store, book_id: int, *, reason: MatchReason, author: str | None = None,
              category: str | None = None, when: datetime = NOW) -> None:
    """Eine Sichtung, die keine Watchlist-Pruefung war."""
    run_id = db.start_run("test", "cli", when)
    db.append(
        run_id,
        "test",
        [
            Observation(
                source="beam",
                source_item_id="7",
                title="Ein Fund",
                match_reason=reason,
                book_id=book_id,
                author=author,
                category=category,
                price_cents=399,
                observed_at=when,
            )
        ],
        when,
    )


def test_a_discovery_names_the_author_who_brought_it_in(
    client: TestClient, db: Store
) -> None:
    """Dieselben Worte wie im Digest — wer eine Entdeckung nicht ueber den
    Digest oeffnet, bekam bisher keine Antwort auf "warum sehe ich das"."""
    book = db.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    discovery(db, book.id, reason=MatchReason.PROFILE_AUTHOR, author="Jo Nesbø")

    body = client.get(f"/book/{book.id}").text

    assert "neu von Jo Nesbø, der du folgst" in body


def test_a_discovery_from_a_thema_says_which(client: TestClient, db: Store) -> None:
    book = db.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    discovery(
        db,
        book.id,
        reason=MatchReason.GENRE_CATEGORY,
        category="belletristik/krimi-thriller/psychothriller",
    )

    body = client.get(f"/book/{book.id}").text

    assert "neu im Thema Psychothriller" in body
    assert "Regal" not in body  # das war der Begriff des Shops, nicht ihrer


def test_a_watchlist_title_explains_nothing(client: TestClient, db: Store) -> None:
    """Warum es dasteht, weiss die Leserin — sie hat es hingeschrieben."""
    book = db.books()[0]
    sighting(db, book.id, when=NOW, price=999)

    body = client.get(f"/book/{book.id}").text

    assert "steht auf deiner Watchlist" not in body
    assert "neu von" not in body


def test_the_reason_survives_a_later_watchlist_check(client: TestClient, db: Store) -> None:
    """Ein entdecktes Buch, das sie dann beobachtet, hat weiterhin einen
    Anlass — die Watchlist-Sichtung darf ihn nicht verdecken."""
    book = db.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    discovery(db, book.id, reason=MatchReason.PROFILE_AUTHOR, author="Jo Nesbø")
    sighting(db, book.id, when=NOW + timedelta(days=1), title="Ein Fund")

    assert "neu von Jo Nesbø, der du folgst" in client.get(f"/book/{book.id}").text


def test_foreign_voices_stand_apart_from_the_fit(client, db) -> None:
    """Eine 4 aus 1641 fremden Stimmen ist etwas ganz anderes als die
    Übereinstimmung mit dem Profil. Sie stehen für sich (ADR 19, Ticket 54)."""
    from ebook_watchlist.ratings import BY_ONLEIHE_READERS

    book = db.find_or_create_book(
        isbn="9783641117009", title="Die sieben Schwestern", author="Riley", now=NOW
    )
    db.put_rating(f"book:{book.id}", stars=4, confidence="belegt",
                  reason="Durchschnitt der Leser:innen aus 1641 Stimmen",
                  profile_version=0, now=NOW, origin=BY_ONLEIHE_READERS, votes=1641)

    body = client.get(f"/book/{book.id}").text

    assert "Was andere Leser:innen sagen" in body
    assert "1641 Stimmen" in body


# --- der Kopf, der die Frage beantwortet (Ticket 52) ------------------------


def test_the_head_carries_price_and_availability(client: TestClient, db: Store) -> None:
    """Preis und Verfügbarkeit standen in der **letzten** Tabelle der Seite —
    700 Pixel unter dem Titel. Wer die Seite öffnet, will genau das wissen."""
    from ebook_watchlist.models import MatchReason, Observation

    settings = load_settings()
    book = db.find_or_create_book(isbn=None, title="Das Knochenband", author="MacBride", now=NOW)
    db.put_relation(settings.slug, book.id, str(RelationKind.WATCHING), now=NOW)
    # Ohne Zuordnung keine Kachel: die Kachel *ist* die Quelle, nicht die
    # Beobachtung.
    db.put_book_source(book.id, "beam", outcome="linked", url="https://beam.invalid/1",
                       resolved_at=NOW, reason="")
    run_id = db.start_run(settings.slug, "cli", NOW)
    db.append(run_id, settings.slug, [
        Observation(source="beam", source_item_id="1", title="Das Knochenband",
                    author="MacBride", match_reason=MatchReason.WATCHLIST,
                    price_cents=299, book_id=book.id, blurb="Ein abgründiger Fall."),
    ], NOW)

    body = client.get(f"/book/{book.id}").text

    head = body[: body.find("Bewertung")]
    assert "2,99" in head
    assert "kachelbild" in head


def test_the_blurb_lives_on_the_book_not_in_every_observation(db: Store) -> None:
    """Er ist ein Stammdatum und kein Messwert: in jeder Beobachtung stünde er
    täglich neu, rund zehn Megabyte im Jahr für denselben Text (Ticket 52)."""
    from ebook_watchlist.models import MatchReason, Observation

    settings = load_settings()
    book = db.find_or_create_book(isbn=None, title="Egal", author="Wer", now=NOW)
    db.put_relation(settings.slug, book.id, str(RelationKind.WATCHING), now=NOW)
    run_id = db.start_run(settings.slug, "cli", NOW)
    db.append(run_id, settings.slug, [
        Observation(source="beam", source_item_id="1", title="Egal", author="Wer",
                    match_reason=MatchReason.WATCHLIST, price_cents=299,
                    book_id=book.id, blurb="Ein langer Text."),
    ], NOW)

    assert db.book(book.id).blurb == "Ein langer Text."
    observed = db.observations_for_book(settings.slug, book.id)
    assert [o.blurb for o in observed] == [None]


def test_a_discovery_keeps_its_blurb_in_the_observation(db: Store) -> None:
    """Eine Entdeckung hat keine Buch-Zeile (ADR 18) — und das Bewertungstor
    liest ihren Klappentext genau dort."""
    from ebook_watchlist.models import MatchReason, Observation

    settings = load_settings()
    run_id = db.start_run(settings.slug, "cli", NOW)
    db.append(run_id, settings.slug, [
        Observation(source="beam", source_item_id="9", title="Ein Fund", author="Wer",
                    match_reason=MatchReason.GENRE_CATEGORY, price_cents=399,
                    blurb="Ein Schiff, allein im Dunkeln."),
    ], NOW)

    discovery = db.latest_discoveries(settings.slug)[0]
    assert discovery.blurb == "Ein Schiff, allein im Dunkeln."


def test_the_longer_blurb_wins(db: Store) -> None:
    """Die Kachel einer Suchseite trägt einen Anriss, die Detailseite den
    ganzen Text — welche zuerst kommt, entscheidet der Zufall des Laufs."""
    from ebook_watchlist.models import MatchReason, Observation

    settings = load_settings()
    book = db.find_or_create_book(isbn=None, title="Egal", author="Wer", now=NOW)
    run_id = db.start_run(settings.slug, "cli", NOW)

    def write(text: str) -> None:
        db.append(run_id, settings.slug, [
            Observation(source="beam", source_item_id="1", title="Egal", author="Wer",
                        match_reason=MatchReason.WATCHLIST, book_id=book.id, blurb=text),
        ], NOW)

    write("Der ganze Text, viel laenger als der Anriss.")
    write("Kurz …")

    assert db.book(book.id).blurb == "Der ganze Text, viel laenger als der Anriss."


def test_two_houses_are_still_settled_by_length(db: Store) -> None:
    """Seit Ticket 56 liefert auch die Bibliothek einen Klappentext — und damit
    stellt sich die Frage, wer gewinnt, wenn beide einen haben.

    Sie bleibt vorerst beantwortet wie bisher: der laengere. Gemessen sind es
    2 von 23 zugeordneten Buechern, die an beiden Haeusern haengen, und 52 der
    53 Buch-Zeilen tragen ueberhaupt keinen Klappentext. Eine Vorrangregel fuer
    zwei Faelle waere geraten, nicht gemessen; dieser Test haelt fest, was
    heute geschieht, damit eine spaetere Regel eine Entscheidung ist und kein
    Versehen."""
    from ebook_watchlist.models import MatchReason, Observation

    settings = load_settings()
    book = db.find_or_create_book(isbn=None, title="Egal", author="Wer", now=NOW)
    run_id = db.start_run(settings.slug, "cli", NOW)
    db.append(run_id, settings.slug, [
        Observation(source="beam", source_item_id="1", title="Egal", author="Wer",
                    match_reason=MatchReason.WATCHLIST, book_id=book.id,
                    blurb="Der Text des Shops."),
        Observation(source="onleihe", source_item_id="2", title="Egal", author="Wer",
                    match_reason=MatchReason.WATCHLIST, book_id=book.id,
                    blurb="Der Text der Bibliothek, mit Pressestimmen davor."),
    ], NOW)

    assert db.book(book.id).blurb == "Der Text der Bibliothek, mit Pressestimmen davor."


def test_the_title_can_be_corrected_from_the_book_page(client: TestClient, db: Store) -> None:
    """Bis hierher gab es das Umbenennen nur auf der Watchlist, und dort nur,
    wenn keine Quelle den Titel fand (ADR 27). Es ist aber eine Eigenschaft
    dieses Buchs."""
    settings = load_settings()
    book = db.find_or_create_book(isbn=None, title="Dunkle Gefilde", author="Morgan", now=NOW)
    db.put_relation(settings.slug, book.id, str(RelationKind.WATCHING), now=NOW)
    db.put_book_source(book.id, "beam", outcome="not_found", url=None, resolved_at=NOW, reason="")

    client.post(f"/book/{book.id}/edit",
                data={"title": "Profit", "author": "Richard K. Morgan", "note": "Konzernduelle."})

    assert db.book(book.id).title == "Profit"
    # Die Zuordnung faellt weg — sie galt fuer den alten Titel.
    assert db.get_book_source(book.id, "beam") is None


def test_editing_the_title_leaves_the_note_alone(client: TestClient, db: Store) -> None:
    """Die Notiz geht in keine Entscheidung ein und kommt aus `notes:` in der
    Watchlist-Datei — das Formular fasst sie deshalb nicht an. Fasste es sie
    doch an, loeschte jedes Berichtigen sie still mit."""
    settings = load_settings()
    book = db.find_or_create_book(isbn=None, title="Egal", author="Wer", now=NOW)
    db.put_relation(settings.slug, book.id, str(RelationKind.WATCHING), now=NOW)
    db.set_relation_details(settings.slug, book.id, str(RelationKind.WATCHING),
                            {"note": 'Band 1, Originaltitel "Market Forces".'}, now=NOW)

    client.post(f"/book/{book.id}/edit", data={"title": "Anders", "author": "Wer"})

    assert view.build(db, settings, book.id).note == 'Band 1, Originaltitel "Market Forces".'


# --- der grosse Lauf (#15) --------------------------------------------------


def test_a_running_run_is_named_in_the_head(client: TestClient, db: Store) -> None:
    """Der grosse Lauf fasst jedes Buch an; bisher sah man auf der Buchseite
    nicht, dass sich die Angaben gleich aendern koennen (#15)."""
    import os

    book = db.books()[0]
    assert "Ein Lauf ist gerade unterwegs" not in client.get(f"/book/{book.id}").text

    # Jetzt und mit lebendem Prozess: ein Lauf von vor Tagen gilt zu Recht als
    # abgebrochen, nicht als unterwegs.
    db.start_run(load_settings().slug, "cli", datetime.now(), pid=os.getpid())

    assert "Ein Lauf ist gerade unterwegs" in client.get(f"/book/{book.id}").text


# --- zwei Bibliotheken, zwei Kacheln ----------------------------------------


def make_sighting(name: str, *, label: str, availability: str, when: datetime) -> view.Sighting:
    return view.Sighting(
        when=when, name=name, source=label, price=None,
        availability=availability, other_title=None, deal=False,
    )


def test_two_libraries_do_not_share_one_tile() -> None:
    """Die Kachel suchte ihre Sichtung ueber die *Beschriftung*. Mit einer
    Bibliothek ging das gut; mit zweien fand die Onleihe-Kachel die Sichtung
    von OverDrive und behauptete "verliehen" fuer einen Titel, den die Onleihe
    gar nicht fuehrt."""
    earlier, later = datetime(2026, 9, 11, 12), datetime(2026, 9, 11, 21)
    history = (
        make_sighting("overdrive", label="Bibliothek", availability="verliehen", when=later),
        make_sighting("onleihe", label="Bibliothek", availability="unklar", when=earlier),
    )

    newest = view._latest_per_source(history)

    # Zwei Quellen, zwei Eintraege — nicht einer, der den anderen verdeckt.
    assert {s.name for s in newest} == {"onleihe", "overdrive"}


def test_a_tile_asks_for_its_own_source_not_for_its_label() -> None:
    earlier, later = datetime(2026, 9, 11, 12), datetime(2026, 9, 11, 21)
    page = view.Page(
        book_id=1, title="Dark Matter", author=None, series=None, isbn=None,
        cover_file=None, relations=(), sources=(), judgements=(), origin=None,
        history=(
            make_sighting("overdrive", label="Bibliothek", availability="verliehen", when=later),
            make_sighting("onleihe", label="Bibliothek", availability="unklar", when=earlier),
        ),
        latest=(
            make_sighting("overdrive", label="Bibliothek", availability="verliehen", when=later),
            make_sighting("onleihe", label="Bibliothek", availability="unklar", when=earlier),
        ),
    )

    assert page.latest_at("overdrive").availability == "verliehen"
    assert page.latest_at("onleihe").availability == "unklar"


def test_the_book_page_names_series_and_volume(client: TestClient, db: Store) -> None:
    """Reihe und Band stehen im Kopf neben der Autor:in (#10)."""
    from ebook_watchlist.dnb import Record

    book = db.find_or_create_book(isbn="9783426306406", title="Autorität",
                                  author="Jeff VanderMeer", now=NOW)
    db.save_dnb("9783426306406", Record(series="Southern Reach", series_index="2"), NOW)
    db.series_from_dnb()

    assert "Southern Reach, Band 2" in client.get(f"/book/{book.id}").text


# --- je Quellenart eine Kachel (#33) ----------------------------------------


def three_sources() -> Settings:
    """Zwei Bibliotheken und ein Shop — der Fall, fuer den der Kopf gebaut wird."""
    return Settings(slug="test", name="Testprofil",
                   sources={"onleihe": {}, "overdrive": {}, "beam": {}})


def linked(db: Store, book_id: int, *names: str, without: str = "") -> None:
    """Die Quellen ans Buch haengen — ohne Verknuepfung kennt der Kopf sie nicht.

    ``ohne`` nennt die Quelle, die nachgesehen und nichts gefunden hat.
    """
    for name in names:
        db.put_book_source(
            book_id,
            name,
            outcome=str(LinkOutcome.NOT_FOUND if name == without else LinkOutcome.LINKED),
            resolved_at=NOW,
        )


def test_each_category_becomes_one_tile(db: Store) -> None:
    """Drei Quellen, zwei Kacheln: die Seite beantwortet zwei Fragen — kann ich
    es leihen, was kostet es —, und beide haben genau eine Antwort."""
    book = db.books()[0]
    linked(db, book.id, "overdrive", "onleihe", "beam")
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE, source="overdrive")
    sighting(db, book.id, when=NOW, source="onleihe")
    sighting(db, book.id, when=NOW, price=999, source="beam")

    kinds = view.build(db, three_sources(), book.id).categories

    assert [kind.category for kind in kinds] == ["library", "shop"]


def test_the_library_tile_names_the_source_that_has_it(db: Store) -> None:
    """Zwei Bibliotheken, eine hat es: die Kachel nennt sie, statt zweimal
    "nicht im Katalog" nebeneinanderzustellen."""
    book = db.books()[0]
    linked(db, book.id, "onleihe", "overdrive")
    sighting(db, book.id, when=NOW, source="onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE, source="overdrive")

    library = view.build(db, three_sources(), book.id).categories[0]

    assert library.best is not None
    assert library.best.name == "overdrive"
    assert library.sighting is not None
    assert library.sighting.availability == "ausleihbar"


def test_the_shop_tile_names_the_cheapest(db: Store) -> None:
    """Der zweitguenstigste Preis aendert keine Entscheidung."""
    book = db.books()[0]
    linked(db, book.id, "beam", "fake")
    sighting(db, book.id, when=NOW, price=1299, source="beam")
    sighting(db, book.id, when=NOW, price=499, source="fake")

    shop = view.build(
        db,
        Settings(slug="test", name="Testprofil", sources={"beam": {}, "fake": {}}),
        book.id,
    ).categories[0]

    assert shop.category == "shop"
    assert shop.best is not None and shop.best.name == "fake"
    assert shop.sighting is not None and shop.sighting.price == "4,99 €"


def test_every_source_of_a_category_is_listed(db: Store) -> None:
    """Die Uebersicht bleibt: je Quelle eine Blase unter ihrer Kachel."""
    book = db.books()[0]
    linked(db, book.id, "onleihe", "overdrive", "beam")
    sighting(db, book.id, when=NOW, source="onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE, source="overdrive")
    sighting(db, book.id, when=NOW, price=999, source="beam")

    kinds = view.build(db, three_sources(), book.id).categories

    assert [len(kind.sources) for kind in kinds] == [2, 1]
    # Die beste zuerst, damit die Blasenreihe liest wie die Kachel darueber.
    assert kinds[0].sources[0].name == "overdrive"


def test_a_category_without_a_find_has_no_best(db: Store) -> None:
    """Kennt keine Bibliothek das Buch, steht in der Kachel "nicht im Katalog"
    — und kein Name, denn es gibt keinen zu nennen."""
    book = db.books()[0]
    linked(db, book.id, "onleihe", "overdrive", "beam",
               without="onleihe")
    db.put_book_source(book.id, "overdrive", outcome=str(LinkOutcome.NOT_FOUND),
                       resolved_at=NOW)
    sighting(db, book.id, when=NOW, price=999, source="beam")

    library = view.build(db, three_sources(), book.id).categories[0]

    assert library.best is None
    assert len(library.sources) == 2


# --- die Quellen, eine Zeile je Quelle (#34) --------------------------------


def test_the_section_is_called_sources(client: TestClient, db: Store) -> None:
    """Sie zeigte, welche Quelle welchen Titel meint — das zieht in den roten
    Kasten um. Was bleibt, ist die Uebersicht ueber alle Quellen."""
    book = db.books()[0]
    linked(db, book.id, "beam")

    body = client.get(f"/book/{book.id}").text

    head = body[body.index("#ic-plug") :][:200]
    assert "Quellen" in head
    assert "Zuordnung" not in head


def test_a_library_row_says_how_long_the_wait_is(db: Store) -> None:
    """Statt eines Strichs die Auskunft, die man braucht: wie viele vor mir."""
    book = db.books()[0]
    linked(db, book.id, "onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.UNAVAILABLE,
             source="onleihe", reservations=3)

    make_sighting = view.build(db, three_sources(), book.id).latest_at("onleihe")

    assert make_sighting is not None
    assert make_sighting.hold == "3 Vormerkungen"


def test_a_returning_copy_names_the_date(db: Store) -> None:
    book = db.books()[0]
    linked(db, book.id, "onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.UNAVAILABLE,
             source="onleihe", available_from="12.10.2026")

    make_sighting = view.build(db, three_sources(), book.id).latest_at("onleihe")

    assert make_sighting is not None and make_sighting.hold == "frei ab 12.10.2026"


def test_a_borrowable_copy_has_nothing_to_wait_for(db: Store) -> None:
    book = db.books()[0]
    linked(db, book.id, "onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE,
             source="onleihe", reservations=0)

    make_sighting = view.build(db, three_sources(), book.id).latest_at("onleihe")

    assert make_sighting is not None and make_sighting.hold is None


def test_the_source_row_links_on_the_name(client: TestClient, db: Store) -> None:
    """Der eigene Verweis "dort ansehen" sagte dasselbe ein zweites Mal."""
    book = db.books()[0]
    db.put_book_source(book.id, "beam", outcome=str(LinkOutcome.LINKED),
                       url="https://beam.invalid/1", resolved_at=NOW)

    body = client.get(f"/book/{book.id}").text

    assert "dort ansehen" not in body
    assert 'href="https://beam.invalid/1"' in body


def test_the_row_repeats_the_title_only_when_it_differs(client: TestClient, db: Store) -> None:
    """Sonst stand in jeder Zeile "nennt es ..." und sagte jedes Mal, dass
    alles stimmt — die Warnung steht ohnehin im roten Kasten darueber (ADR 9)."""
    book = db.books()[0]
    db.put_book_source(book.id, "beam", outcome=str(LinkOutcome.LINKED),
                       matched_title=book.title, resolved_at=NOW)

    assert "nennt es" not in client.get(f"/book/{book.id}").text


def test_a_lent_out_copy_still_names_its_library(db: Store) -> None:
    """Gefuehrt und gerade verliehen ist nicht dasselbe wie "nicht im Katalog":
    das eine heisst warten, das andere anderswo suchen."""
    book = db.books()[0]
    linked(db, book.id, "onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.UNAVAILABLE,
             source="onleihe", reservations=3)

    library = view.build(db, three_sources(), book.id).categories[0]

    assert library.best is not None and library.best.name == "onleihe"
    assert library.sighting is not None
    assert library.sighting.availability == "verliehen"


def test_a_borrowable_library_beats_a_lent_out_one(db: Store) -> None:
    book = db.books()[0]
    linked(db, book.id, "onleihe", "overdrive")
    sighting(db, book.id, when=NOW, availability=Availability.UNAVAILABLE, source="onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE, source="overdrive")

    library = view.build(db, three_sources(), book.id).categories[0]

    assert library.best is not None and library.best.name == "overdrive"


# --- der Steckbrief (#45) ----------------------------------------------------


class StubAsker:
    """Ein Bewerter, der nur gefragt wird — so wie ihn der Steckbrief braucht."""

    def __init__(self, answer) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def ask(self, text: str, max_tokens: int = 300) -> str:
        self.asked.append(text)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def wait_for_portrait(client: TestClient, path: str) -> str:
    """Den Knopf druecken und warten, bis der Hintergrundjob fertig ist."""
    client.post(f"{path}/portrait")
    for _ in range(250):
        status = client.get(f"{path}/portrait")
        if status.headers.get("HX-Refresh") == "true":
            break
        threading.Event().wait(0.02)
    else:
        raise AssertionError("der Steckbrief wurde nicht fertig")
    return client.get(path).text


def _leopard() -> str:
    """Die Antwort zu *Leopard* aus dem Versuch vom 23.09., gekürzt."""
    import json

    return json.dumps({
        "bekannt": True, "titel": "Leopard", "autor": "Jo Nesbø",
        "originaltitel": "Panserhjerte", "genre": "Kriminalroman",
        "untergenre": "Nordic Noir", "pitch": "Harry Hole jagt einen Mörder.",
        "merkmale": [
            {"id": "brooding", "satz": "Harry Hole wird zurückgeholt.", "beleg": "wissen"},
            {"id": "violent", "satz": "Der Leopoldsapfel wird genau ausgemalt.",
             "beleg": "wissen"},
            {"id": "flawed", "satz": "Er greift zur Flasche.", "beleg": "wissen"},
            {"id": "intricate", "satz": "Die Opfer verbindet etwas.", "beleg": "wissen"},
            {"id": "intensifying", "satz": "In Oslo zieht es an.", "beleg": "wissen"},
        ],
        "erzaehlmuster": [
            {"id": "pursuit", "satz": "Der Mörder ist Hole voraus.", "beleg": "wissen"},
        ],
    }, ensure_ascii=False)


@needs_vocabulary
def test_the_button_draws_a_portrait_once(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dasselbe Buch trägt immer denselben Steckbrief: ein zweiter Klick
    kostet keinen Aufruf (ADR 33)."""
    book = db.books()[0]
    asker = StubAsker(_leopard())
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(asker))

    body = wait_for_portrait(client, f"/book/{book.id}")
    wait_for_portrait(client, f"/book/{book.id}")

    assert len(asker.asked) == 1
    assert f"Titel: {book.title}" in asker.asked[0]
    # Nach Familien gruppiert: "brutal" steht unter "hart".
    assert "hart" in body and "gezeichnete Figur" in body
    assert "Der Leopoldsapfel wird genau ausgemalt." in body
    assert "Nordic Noir" in body


class _Changing(StubAsker):
    """Antwortet der Reihe nach; die letzte Antwort gilt für jede weitere Frage."""

    def __init__(self, *answers: str) -> None:
        super().__init__(answers[0])
        self.answers = answers

    def ask(self, text: str, max_tokens: int = 300) -> str:
        self.asked.append(text)
        return self.answers[min(len(self.asked), len(self.answers)) - 1]


def new_portrait(client: TestClient, path: str) -> str:
    """Den Knopf „neu beschreiben“ drücken und auf den Hintergrundjob warten."""
    client.post(f"{path}/portrait?again=1")
    for _ in range(250):
        if client.get(f"{path}/portrait").headers.get("HX-Refresh") == "true":
            break
        threading.Event().wait(0.02)
    else:
        raise AssertionError("der Steckbrief wurde nicht fertig")
    return client.get(path).text


@needs_vocabulary
def test_the_reader_can_ask_for_a_new_portrait_and_it_replaces_the_old_one(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein dünner Steckbrief macht das Urteil dünn (*Dark Matter*, 25.09.2026:
    ein falsches Muster statt *Rätsel*). Die Leserin soll neu fragen können; der
    neue Steckbrief kommt dazu, der alte bleibt in der Tabelle (ADR 5)."""
    book = db.books()[0]
    new = _leopard().replace("Der Leopoldsapfel wird genau ausgemalt.", "Ein ganz anderer Satz.")
    asker = _Changing(_leopard(), new)
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(asker))
    body = wait_for_portrait(client, f"/book/{book.id}")
    assert "Der Leopoldsapfel wird genau ausgemalt." in body

    body = new_portrait(client, f"/book/{book.id}")

    assert len(asker.asked) == 2
    assert "Ein ganz anderer Satz." in body
    assert "Der Leopoldsapfel wird genau ausgemalt." not in body


@needs_vocabulary
def test_a_plain_click_still_costs_nothing_when_a_portrait_exists(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = db.books()[0]
    asker = StubAsker(_leopard())
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(asker))
    wait_for_portrait(client, f"/book/{book.id}")

    wait_for_portrait(client, f"/book/{book.id}")

    assert len(asker.asked) == 1


@needs_vocabulary
def test_the_page_offers_the_new_description_only_next_to_an_existing_portrait(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = db.books()[0]
    again = f'hx-post="/book/{book.id}/portrait?again=1"'
    assert again not in client.get(f"/book/{book.id}").text  # es gibt noch keinen

    monkeypatch.setattr(view, "build_portrayer", portrayer_via(StubAsker(_leopard())))
    body = wait_for_portrait(client, f"/book/{book.id}")

    assert again in body


@needs_vocabulary
def test_a_book_the_model_does_not_know_says_so(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = db.books()[0]
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(StubAsker('{"bekannt": false}')))

    body = wait_for_portrait(client, f"/book/{book.id}")

    assert "kennt dieses Buch nicht" in body


def _give_blurb(db: Store, book_id: int, blurb: str) -> None:
    from ebook_watchlist.store import BookRow

    with db.session() as session:
        session.get(BookRow, book_id).blurb = blurb
        session.commit()


@needs_vocabulary
def test_an_unknown_answer_without_text_is_asked_again_once_a_blurb_is_there(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein Watchlist-Buch wird beim Anlegen nur mit Titel und Autor:in beschrieben.
    Kommt später der Klappentext, darf „kennt das Modell nicht“ nicht für immer
    stehen (fünf Bücher am 25.09.2026)."""
    book = db.books()[0]
    _give_blurb(db, book.id, "")  # kein Text
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(StubAsker('{"bekannt": false}')))
    assert "kennt dieses Buch nicht" in wait_for_portrait(client, f"/book/{book.id}")

    _give_blurb(db, book.id, "Ein Klappentext, der das Buch endlich beschreibt.")
    asker = StubAsker(_leopard())
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(asker))
    body = wait_for_portrait(client, f"/book/{book.id}")

    assert len(asker.asked) == 1 and "endlich beschreibt" in asker.asked[0]
    assert "kennt dieses Buch nicht" not in body and "Nordic Noir" in body


@needs_vocabulary
def test_the_button_returns_for_an_unknown_book_once_a_text_is_there(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Buchseite fragt nie von selbst; der Knopf ist der Weg. Er stand nur,
    solange es keinen Steckbrief gab — ein gespeichertes „unbekannt“ nahm ihn weg,
    und die zweite Chance war nicht zu erreichen."""
    book = db.books()[0]
    button = f'hx-post="/book/{book.id}/portrait"'
    _give_blurb(db, book.id, "")
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(StubAsker('{"bekannt": false}')))
    body = wait_for_portrait(client, f"/book/{book.id}")
    assert "kennt dieses Buch nicht" in body and button not in body  # noch kein Text

    _give_blurb(db, book.id, "Ein Klappentext, der das Buch endlich beschreibt.")

    assert button in client.get(f"/book/{book.id}").text


@needs_vocabulary
def test_an_unknown_answer_given_with_text_stays_and_costs_no_second_call(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = db.books()[0]
    _give_blurb(db, book.id, "Ein Redaktionsvorwort statt einer Inhaltsangabe.")
    asker = StubAsker('{"bekannt": false}')
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(asker))

    wait_for_portrait(client, f"/book/{book.id}")
    body = wait_for_portrait(client, f"/book/{book.id}")

    assert len(asker.asked) == 1
    assert "kennt dieses Buch nicht" in body
    assert f'hx-post="/book/{book.id}/portrait"' not in body  # nichts Neues zu fragen


@needs_vocabulary
def test_an_unknown_answer_without_text_is_not_asked_again_while_there_is_still_no_text(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = db.books()[0]
    _give_blurb(db, book.id, "")
    asker = StubAsker('{"bekannt": false}')
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(asker))

    wait_for_portrait(client, f"/book/{book.id}")
    wait_for_portrait(client, f"/book/{book.id}")

    assert len(asker.asked) == 1


@needs_vocabulary
def test_without_a_model_nothing_changes_and_the_page_says_why(
    client: TestClient, db: Store
) -> None:
    """Das Tor scheitert nie zu (ADR 7) — und der Steckbrief auch nicht."""
    book = db.books()[0]

    body = wait_for_portrait(client, f"/book/{book.id}")

    assert "Kein Weg zum Modell" in body


@needs_vocabulary
def test_a_failed_call_stores_nothing(db: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    from ebook_watchlist.portrait import fingerprint, load_vocabulary

    book = db.books()[0]
    monkeypatch.setattr(
        view, "build_portrayer", portrayer_via(StubAsker(PortrayalUnavailable("Zeit abgelaufen")))
    )

    reason = view.portray(db, load_settings(), book.id, now=NOW)

    assert reason == "Zeit abgelaufen"
    assert db.portrait(view.portrait_subject(book), fingerprint(load_vocabulary())) is None


@needs_vocabulary
def test_a_book_with_an_isbn_keeps_its_portrait_at_the_isbn(
    db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wie ein Urteil des Tors: so findet der Lauf denselben Steckbrief wieder."""
    book = db.find_or_create_book(isbn="9783548289441", title="Leopard",
                                  author="Jo Nesbø", now=NOW)
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(StubAsker(_leopard())))

    view.portray(db, load_settings(), book.id, now=NOW)

    from ebook_watchlist.portrait import fingerprint, load_vocabulary

    assert db.portrait("isbn:9783548289441", fingerprint(load_vocabulary())).known


@needs_vocabulary
def test_a_portrait_survives_the_book_getting_an_isbn(
    db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein Watchlist-Titel bekommt seine ISBN oft erst, wenn ein Lauf ihn
    auflöst. Der Steckbrief von vorher gilt weiter und kostet keinen zweiten
    Aufruf."""
    from sqlalchemy import update

    from ebook_watchlist.store import BookRow

    book = db.find_or_create_book(isbn=None, title="Leopard", author="Jo Nesbø", now=NOW)
    asker = StubAsker(_leopard())
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(asker))
    view.portray(db, load_settings(), book.id, now=NOW)
    with db.session() as session:
        session.execute(update(BookRow).where(BookRow.id == book.id).values(isbn="9783548289441"))
        session.commit()

    view.portray(db, load_settings(), book.id, now=NOW)

    assert len(asker.asked) == 1
    assert view.build(db, load_settings(), book.id).portrait.known


# --- die Übereinstimmung aus dem Code (#46) ---------------------------------


def _profile():
    from ebook_watchlist.facets import Counterweight, Facet, ReadingProfile

    return ReadingProfile(
        facets=(Facet(("harsh", "brooding"), ("Leichenblässe", "Kruzifix Killer")),),
        counterweights=(Counterweight(("leisurely",)),),
    )


@needs_vocabulary
def test_with_profile_and_portrait_the_page_shows_the_fit(
    db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leopard trägt "hart" und "gezeichnete Figur" und trifft die Facette ganz."""
    book = db.books()[0]
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(StubAsker(_leopard())))
    view.portray(db, load_settings(), book.id, now=NOW)
    db.put_reading_profile(load_settings().slug, _profile(), cause="Test", now=NOW)

    fit = view.build(db, load_settings(), book.id).fit

    assert (fit.stars, fit.percent, fit.version) == (4, 56, 1)
    assert fit.reasons[0].text == "hart · gezeichnete Figur"


@needs_vocabulary
def test_the_fit_stands_under_the_judgement(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = db.books()[0]
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(StubAsker(_leopard())))
    view.portray(db, load_settings(), book.id, now=NOW)
    db.put_reading_profile(load_settings().slug, _profile(), cause="Test", now=NOW)

    body = client.get(f"/book/{book.id}").text

    assert "Übereinstimmung mit deinem Leseprofil" in body
    assert "hart · gezeichnete Figur" in body
    assert "Harry Hole wird zurückgeholt." in body
    # Das Buch über der Geschmacksform (#79).
    assert 'data-spider="Merkmale"' in body and "dieses Buch" in body


def test_without_a_profile_there_is_no_fit(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ohne Profil kein Urteil (ADR 33, Punkt 8) — auch nicht "passt nicht"."""
    book = db.books()[0]
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(StubAsker(_leopard())))
    view.portray(db, load_settings(), book.id, now=NOW)

    assert view.build(db, load_settings(), book.id).fit is None
    assert "data-fit" not in client.get(f"/book/{book.id}").text


def test_without_a_portrait_there_is_no_fit(db: Store) -> None:
    book = db.books()[0]
    db.put_reading_profile(load_settings().slug, _profile(), cause="Test", now=NOW)

    assert view.build(db, load_settings(), book.id).fit is None


@needs_vocabulary
def test_story_patterns_stand_apart_from_the_terms(
    db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Merkmale sagen, wie es sich liest; Muster, was es erzählt (#49)."""
    book = db.books()[0]
    monkeypatch.setattr(view, "build_portrayer", portrayer_via(StubAsker(_leopard())))
    view.portray(db, load_settings(), book.id, now=NOW)

    portrait = view.build(db, load_settings(), book.id).portrait

    assert [f.name for f in portrait.patterns] == ["Katz und Maus"]
    assert "Katz und Maus" not in [f.name for f in portrait.families]
