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

from ebook_watchlist import paths
from ebook_watchlist.config import Settings, load_settings
from ebook_watchlist.models import Availability, LinkOutcome, MatchReason, Observation
from ebook_watchlist.rating import Rating, RatingUnavailable
from ebook_watchlist.ratings import BY_CONVERSATION, BY_MODEL, BY_READER, book_subject
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

    client.post(f"/book/{book.id}/sterne", data={"stars": "4"})

    row = db.rating(book_subject(book.id), 1, origin=BY_READER)
    assert row.stars == 4
    assert "zurücknehmen" in client.get(f"/book/{book.id}").text


def test_taking_them_back_writes_no_zero(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    client.post(f"/book/{book.id}/sterne", data={"stars": "4"})

    client.post(f"/book/{book.id}/sterne", data={"stars": ""})

    assert db.rating(book_subject(book.id), 1, origin=BY_READER) is None
    assert "Noch nicht bewertet" in client.get(f"/book/{book.id}").text


def test_a_judgement_from_the_conversation_is_a_machine_judgement(
    client: TestClient, db: Store
) -> None:
    """Eine 4 von ihr und eine 4 vom Modell dürfen nicht gleich aussehen
    (ADR 17). Die dreizehn Urteile aus ``owned.yaml`` sind im Gespräch
    entstanden, aber vom Modell gefällt — sie hießen trotzdem "deine
    Bewertung", genau wie die Sterne, die sie selbst vergibt (#13)."""
    book = db.books()[0]
    db.put_rating(book_subject(book.id), stars=4, confidence="teils", reason="Reihe und Stimme.",
                  profile_version=1, now=NOW, origin=BY_CONVERSATION)

    body = client.get(f"/book/{book.id}").text

    assert "deine Bewertung" not in body
    assert "Leseprofil" in body
    assert "Reihe und Stimme." in body
    assert "Noch nicht bewertet" in body  # ihre eigenen stehen weiterhin aus


def test_the_gates_judgement_is_found_through_the_isbn(client: TestClient, db: Store) -> None:
    """Das Tor schlüsselt am Fund, nicht am Buch — sonst stünde sein Urteil
    hier nicht."""
    book = db.find_or_create_book(isbn="9783104911854", title="Ein Fund", now=NOW)
    db.put_rating("isbn:9783104911854", stars=2, confidence="vermutet", reason="Zu weich.",
                  profile_version=1, now=NOW, origin=BY_MODEL)

    body = client.get(f"/book/{book.id}").text

    assert "Leseprofil" in body
    assert "Zu weich." in body


def test_a_judgement_against_an_older_leseprofil_says_so(client: TestClient, db: Store) -> None:
    book = db.books()[0]
    db.put_rating(book_subject(book.id), stars=4, confidence="teils", reason="Alt.",
                  profile_version=0, now=NOW, origin=BY_MODEL)

    body = client.get(f"/book/{book.id}").text

    # Sichtbar steht ein Wort; die Versionen stehen im Hinweis daneben.
    assert ">veraltet<" in body
    assert "beurteilt gegen Profil 0" in body


def test_a_nonsense_star_count_is_refused(client: TestClient, db: Store) -> None:
    book = db.books()[0]

    assert client.post(f"/book/{book.id}/sterne", data={"stars": "9"}).status_code == 400
    assert client.post(f"/book/{book.id}/sterne", data={"stars": "vier"}).status_code == 400


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


def test_the_gates_verdict_on_a_discovery_without_an_isbn_is_found_too(
    client: TestClient, db: Store
) -> None:
    """Buendel und Einzelfolgen tragen keine ISBN — dort haengt das Urteil an
    der Produktnummer, unter der dieses Buch gesichtet wurde."""
    book = db.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    discovery(db, book.id, reason=MatchReason.GENRE_CATEGORY, category="horror-mystery-allgemein")
    db.put_rating("item:beam:7", stars=4, confidence="teils", reason="Achse D: isoliert.",
                  profile_version=1, now=NOW, origin=BY_MODEL)

    body = client.get(f"/book/{book.id}").text

    assert "Leseprofil" in body
    assert "Achse D: isoliert." in body
    assert "Noch nicht bewertet" in body  # ihre eigenen Sterne bleiben getrennt


def test_foreign_voices_do_not_look_like_the_tools_verdict(client, db) -> None:
    """Eine 4 vom Modell ist ein Vorschlag, eine 4 aus 1641 fremden Stimmen ist
    etwas ganz anderes. Sie dürfen nicht im selben Kasten stehen (ADR 19,
    Ticket 54)."""
    from ebook_watchlist.ratings import BY_MODEL, BY_ONLEIHE_READERS

    buch = db.find_or_create_book(
        isbn="9783641117009", title="Die sieben Schwestern", author="Riley", now=NOW
    )
    db.put_rating(f"book:{buch.id}", stars=4, confidence="belegt", reason="Modell",
                  profile_version=2, now=NOW, origin=BY_MODEL)
    db.put_rating(f"book:{buch.id}", stars=4, confidence="belegt",
                  reason="Durchschnitt der Leser:innen aus 1641 Stimmen",
                  profile_version=0, now=NOW, origin=BY_ONLEIHE_READERS, votes=1641)

    body = client.get(f"/book/{buch.id}").text

    assert "Was andere Leser:innen sagen" in body
    assert "1641 Stimmen" in body
    # Und ausdrücklich *nicht* als veraltetes Modellurteil gebrandmarkt: die
    # Profilversion 0 heißt "nicht gegen das Profil gefällt", nicht "veraltet".
    # Die Marke am Modellurteil daneben (Profil 2) gehoert dorthin — geprueft
    # wird deshalb die Version, nicht das blosse Wort.
    assert "beurteilt gegen Profil 0" not in body


def test_a_foreign_voice_never_goes_stale(db) -> None:
    """Sie ist kein Urteil gegen das Leseprofil und verfällt deshalb nicht,
    wenn die Leserin ihr Profil schärft."""
    from ebook_watchlist.ratings import BY_ONLEIHE_READERS
    from ebook_watchlist.web.book import Judgement

    stimme = Judgement(origin=BY_ONLEIHE_READERS, label="Leser:innen", stars=4.0,
                       reason="", confidence="belegt", profile_version=0,
                       when=None, votes=1641)

    assert stimme.is_foreign
    assert not stimme.stale(2)


# --- der Kopf, der die Frage beantwortet (Ticket 52) ------------------------


def test_the_head_carries_price_and_availability(client: TestClient, db: Store) -> None:
    """Preis und Verfügbarkeit standen in der **letzten** Tabelle der Seite —
    700 Pixel unter dem Titel. Wer die Seite öffnet, will genau das wissen."""
    from ebook_watchlist.models import MatchReason, Observation

    settings = load_settings()
    buch = db.find_or_create_book(isbn=None, title="Das Knochenband", author="MacBride", now=NOW)
    db.put_relation(settings.slug, buch.id, str(RelationKind.WATCHING), now=NOW)
    # Ohne Zuordnung keine Kachel: die Kachel *ist* die Quelle, nicht die
    # Beobachtung.
    db.put_book_source(buch.id, "beam", outcome="linked", url="https://beam.invalid/1",
                       resolved_at=NOW, reason="")
    run_id = db.start_run(settings.slug, "cli", NOW)
    db.append(run_id, settings.slug, [
        Observation(source="beam", source_item_id="1", title="Das Knochenband",
                    author="MacBride", match_reason=MatchReason.WATCHLIST,
                    price_cents=299, book_id=buch.id, blurb="Ein abgründiger Fall."),
    ], NOW)

    body = client.get(f"/book/{buch.id}").text

    kopf = body[: body.find("Bewertung")]
    assert "2,99" in kopf
    assert "kachelbild" in kopf


def test_the_blurb_lives_on_the_book_not_in_every_observation(db: Store) -> None:
    """Er ist ein Stammdatum und kein Messwert: in jeder Beobachtung stünde er
    täglich neu, rund zehn Megabyte im Jahr für denselben Text (Ticket 52)."""
    from ebook_watchlist.models import MatchReason, Observation

    settings = load_settings()
    buch = db.find_or_create_book(isbn=None, title="Egal", author="Wer", now=NOW)
    db.put_relation(settings.slug, buch.id, str(RelationKind.WATCHING), now=NOW)
    run_id = db.start_run(settings.slug, "cli", NOW)
    db.append(run_id, settings.slug, [
        Observation(source="beam", source_item_id="1", title="Egal", author="Wer",
                    match_reason=MatchReason.WATCHLIST, price_cents=299,
                    book_id=buch.id, blurb="Ein langer Text."),
    ], NOW)

    assert db.book(buch.id).blurb == "Ein langer Text."
    beobachtet = db.observations_for_book(settings.slug, buch.id)
    assert [o.blurb for o in beobachtet] == [None]


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

    fund = db.latest_discoveries(settings.slug)[0]
    assert fund.blurb == "Ein Schiff, allein im Dunkeln."


def test_the_longer_blurb_wins(db: Store) -> None:
    """Die Kachel einer Suchseite trägt einen Anriss, die Detailseite den
    ganzen Text — welche zuerst kommt, entscheidet der Zufall des Laufs."""
    from ebook_watchlist.models import MatchReason, Observation

    settings = load_settings()
    buch = db.find_or_create_book(isbn=None, title="Egal", author="Wer", now=NOW)
    run_id = db.start_run(settings.slug, "cli", NOW)

    def schreibe(text: str) -> None:
        db.append(run_id, settings.slug, [
            Observation(source="beam", source_item_id="1", title="Egal", author="Wer",
                        match_reason=MatchReason.WATCHLIST, book_id=buch.id, blurb=text),
        ], NOW)

    schreibe("Der ganze Text, viel laenger als der Anriss.")
    schreibe("Kurz …")

    assert db.book(buch.id).blurb == "Der ganze Text, viel laenger als der Anriss."


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
    buch = db.find_or_create_book(isbn=None, title="Egal", author="Wer", now=NOW)
    run_id = db.start_run(settings.slug, "cli", NOW)
    db.append(run_id, settings.slug, [
        Observation(source="beam", source_item_id="1", title="Egal", author="Wer",
                    match_reason=MatchReason.WATCHLIST, book_id=buch.id,
                    blurb="Der Text des Shops."),
        Observation(source="onleihe", source_item_id="2", title="Egal", author="Wer",
                    match_reason=MatchReason.WATCHLIST, book_id=buch.id,
                    blurb="Der Text der Bibliothek, mit Pressestimmen davor."),
    ], NOW)

    assert db.book(buch.id).blurb == "Der Text der Bibliothek, mit Pressestimmen davor."


def test_the_title_can_be_corrected_from_the_book_page(client: TestClient, db: Store) -> None:
    """Bis hierher gab es das Umbenennen nur auf der Watchlist, und dort nur,
    wenn keine Quelle den Titel fand (ADR 27). Es ist aber eine Eigenschaft
    dieses Buchs."""
    settings = load_settings()
    buch = db.find_or_create_book(isbn=None, title="Dunkle Gefilde", author="Morgan", now=NOW)
    db.put_relation(settings.slug, buch.id, str(RelationKind.WATCHING), now=NOW)
    db.put_book_source(buch.id, "beam", outcome="not_found", url=None, resolved_at=NOW, reason="")

    client.post(f"/book/{buch.id}/bearbeiten",
                data={"title": "Profit", "author": "Richard K. Morgan", "note": "Konzernduelle."})

    assert db.book(buch.id).title == "Profit"
    # Die Zuordnung faellt weg — sie galt fuer den alten Titel.
    assert db.get_book_source(buch.id, "beam") is None


def test_editing_the_title_leaves_the_note_alone(client: TestClient, db: Store) -> None:
    """Die Notiz geht in keine Entscheidung ein und kommt aus `notes:` in der
    Watchlist-Datei — das Formular fasst sie deshalb nicht an. Fasste es sie
    doch an, loeschte jedes Berichtigen sie still mit."""
    settings = load_settings()
    buch = db.find_or_create_book(isbn=None, title="Egal", author="Wer", now=NOW)
    db.put_relation(settings.slug, buch.id, str(RelationKind.WATCHING), now=NOW)
    db.set_relation_details(settings.slug, buch.id, str(RelationKind.WATCHING),
                            {"note": 'Band 1, Originaltitel "Market Forces".'}, now=NOW)

    client.post(f"/book/{buch.id}/bearbeiten", data={"title": "Anders", "author": "Wer"})

    assert view.build(db, settings, buch.id).note == 'Band 1, Originaltitel "Market Forces".'


# --- ein Urteil nachholen (Ticket 55) ---------------------------------------


class StubRater:
    """Ein Bewerter, der nichts fragt. Merkt sich, worueber er urteilen sollte."""

    def __init__(self, rating: Rating | Exception) -> None:
        self.rating = rating
        self.asked: list[Observation] = []

    def rate(self, observation: Observation) -> Rating:
        self.asked.append(observation)
        if isinstance(self.rating, Exception):
            raise self.rating
        return self.rating


def urteil_abwarten(client: TestClient, pfad: str) -> str:
    """Den Knopf druecken und warten, bis der Hintergrundjob fertig ist (#15).

    Die Seite fragt nach, solange er laeuft, und laesst sich neu laden, sobald
    er fertig ist — genau das tut der Test auch. Zurueck kommt die Seite.
    """
    client.post(f"{pfad}/bewerten")
    for _ in range(250):
        stand = client.get(f"{pfad}/bewerten")
        if stand.headers.get("HX-Refresh") == "true":
            break
        threading.Event().wait(0.02)
    else:
        raise AssertionError("das Urteil wurde nicht fertig")
    return client.get(pfad).text


def test_the_button_fetches_a_judgement_for_this_one_book(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Das Tor sieht im Lauf nur, was in den Stapel kaeme; ein Watchlist-Titel
    ist gewollt und wird nie gefragt. Von seiner Seite aus schon."""
    buch = db.books()[0]
    sighting(db, buch.id, when=NOW, price=999)
    rater = StubRater(Rating(stars=4, reason="Passt.", confidence="teils",
                             profile_version=1, pitch="Eine Flucht."))
    monkeypatch.setattr(view, "build_rater", lambda model: rater)

    body = urteil_abwarten(client, f"/book/{buch.id}")

    assert [o.source_item_id for o in rater.asked] == ["1"]
    # Am Fund geschluesselt, nicht am Buch (ADR 18) — und trotzdem auf der
    # Seite zu sehen.
    assert db.ratings_for(["item:beam:1"])[("item:beam:1", BY_MODEL)].stars == 4
    assert "Passt." in body
    # Der Weg steht am Urteil (#10): von der Buchseite, nicht im Lauf.
    from ebook_watchlist.ratings import VIA_BOOK_PAGE

    assert db.ratings_for(["item:beam:1"])[("item:beam:1", BY_MODEL)].via == VIA_BOOK_PAGE


def test_the_button_gathers_the_same_evidence_as_the_run(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sonst urteilte die Buchseite ohne Leseprobe und käme nie über "teils"
    hinaus, während der Lauf dasselbe Buch belegt (#17). Dieselbe Funktion
    wie im Lauf, im Hintergrundjob — die Seite wartet darauf nicht."""
    from ebook_watchlist.sources.base import Item

    buch = db.books()[0]
    sighting(db, buch.id, when=NOW)
    rater = StubRater(Rating(stars=4, reason="Passt.", confidence="teils", profile_version=1))
    monkeypatch.setattr(view, "build_rater", lambda model: rater)

    class Quelle:
        name = "beam"

        def item(self, source_item_id: str) -> Item:
            return Item(source_item_id=source_item_id, title="Ein Buch",
                        keywords=("Space Opera",))

    monkeypatch.setattr(view, "evidence_sources", lambda settings, store: [Quelle()])

    urteil_abwarten(client, f"/book/{buch.id}")

    assert rater.asked[0].keywords == ("Space Opera",)


def test_the_page_does_not_wait_for_the_model(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein Aufruf dauert rund 43 Sekunden, und bisher wartete der Browser so
    lange auf die Antwort. Jetzt kommt sofort der Stand zurueck, und die Seite
    fragt nach, bis das Urteil steht (#15)."""
    buch = db.books()[0]
    sighting(db, buch.id, when=NOW)
    losgelassen = threading.Event()

    class Langsam(StubRater):
        def rate(self, observation: Observation) -> Rating:
            losgelassen.wait(5)
            return super().rate(observation)

    monkeypatch.setattr(view, "build_rater", lambda model: Langsam(
        Rating(stars=4, reason="Passt.", confidence="teils", profile_version=1)))
    try:
        stand = client.post(f"/book/{buch.id}/bewerten").text

        assert "beurteilt" in stand
        assert "every 2s" in stand
        # Die Seite zeigt denselben Stand, solange er laeuft.
        assert "beurteilt" in client.get(f"/book/{buch.id}").text
    finally:
        losgelassen.set()


def test_the_old_judgement_stays_while_the_new_one_is_made(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ersetzt wird erst beim Speichern — eine Minute lang steht die Seite
    nicht leer (#15)."""
    buch = db.books()[0]
    sighting(db, buch.id, when=NOW)
    db.put_rating("item:beam:1", stars=3, confidence="teils", reason="Das alte Urteil.",
                  profile_version=1, now=NOW, origin=BY_MODEL)
    losgelassen = threading.Event()

    class Langsam(StubRater):
        def rate(self, observation: Observation) -> Rating:
            losgelassen.wait(5)
            return super().rate(observation)

    monkeypatch.setattr(view, "build_rater", lambda model: Langsam(
        Rating(stars=4, reason="Das neue.", confidence="teils", profile_version=1)))
    try:
        client.post(f"/book/{buch.id}/bewerten")

        assert "Das alte Urteil." in client.get(f"/book/{buch.id}").text
    finally:
        losgelassen.set()


def test_without_a_rater_the_page_says_why(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Das Tor scheitert nie zu (ADR 7): kein Schluessel ist kein Fehler,
    sondern eine Auskunft."""
    buch = db.books()[0]
    sighting(db, buch.id, when=NOW)
    monkeypatch.setattr(view, "build_rater", lambda model: None)

    assert "Kein Bewerter eingerichtet" in urteil_abwarten(client, f"/book/{buch.id}")


def test_a_refusal_from_the_model_is_named_not_swallowed(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Und das alte Urteil bleibt ganz, wenn der Aufruf scheitert (#15)."""
    buch = db.books()[0]
    sighting(db, buch.id, when=NOW)
    db.put_rating("item:beam:1", stars=3, confidence="teils", reason="Das alte Urteil.",
                  profile_version=1, now=NOW, origin=BY_MODEL)
    monkeypatch.setattr(
        view, "build_rater", lambda model: StubRater(RatingUnavailable("Modell antwortete 429"))
    )

    body = urteil_abwarten(client, f"/book/{buch.id}")

    assert "Modell antwortete 429" in body
    assert "Das alte Urteil." in body


def test_a_book_nobody_has_seen_yet_is_judged_on_its_bare_title(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bis #38 hiess es hier "Noch kein Fund — es gibt nichts zu beurteilen".
    Doch etwas gibt es: Titel und Autor:in. Das Urteil darauf ist duenn, und
    es haengt am Buch statt an einem Fund, den es nicht gibt."""
    from ebook_watchlist.ratings import book_subject

    buch = db.find_or_create_book(isbn=None, title="Nie gesehen", now=NOW)
    rater = StubRater(Rating(stars=5, reason="Klingt gut.", confidence="duenn",
                             profile_version=1))
    monkeypatch.setattr(view, "build_rater", lambda model: rater)

    body = urteil_abwarten(client, f"/book/{buch.id}")

    assert [o.title for o in rater.asked] == ["Nie gesehen"]
    schluessel = book_subject(buch.id)
    assert db.ratings_for([schluessel])[(schluessel, BY_MODEL)].stars == 5
    assert "Klingt gut." in body


def test_the_button_stays_once_a_judgement_stands(client: TestClient, db: Store) -> None:
    """Das Modell urteilt nicht deterministisch — gemessen 3, 2, 2, 2 Sterne am
    selben Buch —, und nach einer Berichtigung will man neu urteilen. Bisher
    verschwand der Knopf, sobald ein Urteil dastand (#15)."""
    buch = db.books()[0]
    sighting(db, buch.id, when=NOW)
    db.put_rating("item:beam:1", stars=3, confidence="teils", reason="Steht.",
                  profile_version=1, now=NOW, origin=BY_MODEL)

    body = client.get(f"/book/{buch.id}").text

    assert f"/book/{buch.id}/bewerten" in body
    # Nur noch das Zeichen: das Wort steht im Hinweis, der Dauerhinweis ist
    # ganz weg — er sagte etwas ueber die Technik, nicht ueber das Buch.
    assert 'aria-label="neu beurteilen"' in body
    assert "etwa eine Minute" not in body


def test_a_running_run_is_named_in_the_head(client: TestClient, db: Store) -> None:
    """Der grosse Lauf fasst jedes Buch an; bisher sah man auf der Buchseite
    nicht, dass sich die Angaben gleich aendern koennen (#15)."""
    import os

    buch = db.books()[0]
    assert "Ein Lauf ist gerade unterwegs" not in client.get(f"/book/{buch.id}").text

    # Jetzt und mit lebendem Prozess: ein Lauf von vor Tagen gilt zu Recht als
    # abgebrochen, nicht als unterwegs.
    db.start_run(load_settings().slug, "cli", datetime.now(), pid=os.getpid())

    assert "Ein Lauf ist gerade unterwegs" in client.get(f"/book/{buch.id}").text


# --- zwei Bibliotheken, zwei Kacheln ----------------------------------------


def sichtung(name: str, *, label: str, availability: str, when: datetime) -> view.Sighting:
    return view.Sighting(
        when=when, name=name, source=label, price=None,
        availability=availability, other_title=None, deal=False,
    )


def test_two_libraries_do_not_share_one_tile() -> None:
    """Die Kachel suchte ihre Sichtung ueber die *Beschriftung*. Mit einer
    Bibliothek ging das gut; mit zweien fand die Onleihe-Kachel die Sichtung
    von OverDrive und behauptete "verliehen" fuer einen Titel, den die Onleihe
    gar nicht fuehrt."""
    frueher, spaeter = datetime(2026, 9, 11, 12), datetime(2026, 9, 11, 21)
    verlauf = (
        sichtung("overdrive", label="Bibliothek", availability="verliehen", when=spaeter),
        sichtung("onleihe", label="Bibliothek", availability="unklar", when=frueher),
    )

    neueste = view._latest_per_source(verlauf)

    # Zwei Quellen, zwei Eintraege — nicht einer, der den anderen verdeckt.
    assert {s.name for s in neueste} == {"onleihe", "overdrive"}


def test_a_tile_asks_for_its_own_source_not_for_its_label() -> None:
    frueher, spaeter = datetime(2026, 9, 11, 12), datetime(2026, 9, 11, 21)
    seite = view.Page(
        book_id=1, title="Dark Matter", author=None, series=None, isbn=None,
        cover_file=None, relations=(), sources=(), judgements=(), profile_version=None,
        origin=None,
        history=(
            sichtung("overdrive", label="Bibliothek", availability="verliehen", when=spaeter),
            sichtung("onleihe", label="Bibliothek", availability="unklar", when=frueher),
        ),
        latest=(
            sichtung("overdrive", label="Bibliothek", availability="verliehen", when=spaeter),
            sichtung("onleihe", label="Bibliothek", availability="unklar", when=frueher),
        ),
    )

    assert seite.latest_at("overdrive").availability == "verliehen"
    assert seite.latest_at("onleihe").availability == "unklar"


def test_the_book_page_names_series_and_volume(client: TestClient, db: Store) -> None:
    """Reihe und Band stehen im Kopf neben der Autor:in (#10)."""
    from ebook_watchlist.dnb import Record

    buch = db.find_or_create_book(isbn="9783426306406", title="Autorität",
                                  author="Jeff VanderMeer", now=NOW)
    db.save_dnb("9783426306406", Record(series="Southern Reach", series_index="2"), NOW)
    db.series_from_dnb()

    assert "Southern Reach, Band 2" in client.get(f"/book/{buch.id}").text


def test_the_axes_stand_as_marks_above_the_reason(client: TestClient, db: Store) -> None:
    """Die Marke traegt den Namen, der Satz den Beleg — nicht dasselbe zweimal
    (#12). Getroffen und verfehlt sehen verschieden aus."""
    buch = db.books()[0]
    sighting(db, buch.id, when=NOW)
    db.put_rating("item:beam:1", stars=4, confidence="teils", reason="Beide Seiten handeln.",
                  profile_version=1, now=NOW, origin=BY_MODEL,
                  hits=("Katz und Maus",), misses=("Die Figur trägt alles",))

    body = client.get(f"/book/{buch.id}").text

    trifft = body.index('data-achse="trifft"')
    fehlt = body.index('data-achse="fehlt"')
    assert "Katz und Maus" in body[trifft:fehlt]
    assert "Die Figur trägt alles" in body[fehlt:]
    assert body.index("Katz und Maus") < body.index("Beide Seiten handeln.")


# --- je Quellenart eine Kachel (#33) ----------------------------------------


def drei_quellen() -> Settings:
    """Zwei Bibliotheken und ein Shop — der Fall, fuer den der Kopf gebaut wird."""
    return Settings(slug="test", name="Testprofil",
                   sources={"onleihe": {}, "overdrive": {}, "beam": {}})


def verknuepft(db: Store, book_id: int, *namen: str, ohne: str = "") -> None:
    """Die Quellen ans Buch haengen — ohne Verknuepfung kennt der Kopf sie nicht.

    ``ohne`` nennt die Quelle, die nachgesehen und nichts gefunden hat.
    """
    for name in namen:
        db.put_book_source(
            book_id,
            name,
            outcome=str(LinkOutcome.NOT_FOUND if name == ohne else LinkOutcome.LINKED),
            resolved_at=NOW,
        )


def test_each_category_becomes_one_tile(db: Store) -> None:
    """Drei Quellen, zwei Kacheln: die Seite beantwortet zwei Fragen — kann ich
    es leihen, was kostet es —, und beide haben genau eine Antwort."""
    book = db.books()[0]
    verknuepft(db, book.id, "overdrive", "onleihe", "beam")
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE, source="overdrive")
    sighting(db, book.id, when=NOW, source="onleihe")
    sighting(db, book.id, when=NOW, price=999, source="beam")

    arten = view.build(db, drei_quellen(), book.id).categories

    assert [art.category for art in arten] == ["library", "shop"]


def test_the_library_tile_names_the_source_that_has_it(db: Store) -> None:
    """Zwei Bibliotheken, eine hat es: die Kachel nennt sie, statt zweimal
    "nicht im Katalog" nebeneinanderzustellen."""
    book = db.books()[0]
    verknuepft(db, book.id, "onleihe", "overdrive")
    sighting(db, book.id, when=NOW, source="onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE, source="overdrive")

    bibliothek = view.build(db, drei_quellen(), book.id).categories[0]

    assert bibliothek.best is not None
    assert bibliothek.best.name == "overdrive"
    assert bibliothek.sighting is not None
    assert bibliothek.sighting.availability == "ausleihbar"


def test_the_shop_tile_names_the_cheapest(db: Store) -> None:
    """Der zweitguenstigste Preis aendert keine Entscheidung."""
    book = db.books()[0]
    verknuepft(db, book.id, "beam", "fake")
    sighting(db, book.id, when=NOW, price=1299, source="beam")
    sighting(db, book.id, when=NOW, price=499, source="fake")

    laden = view.build(
        db,
        Settings(slug="test", name="Testprofil", sources={"beam": {}, "fake": {}}),
        book.id,
    ).categories[0]

    assert laden.category == "shop"
    assert laden.best is not None and laden.best.name == "fake"
    assert laden.sighting is not None and laden.sighting.price == "4,99 €"


def test_every_source_of_a_category_is_listed(db: Store) -> None:
    """Die Uebersicht bleibt: je Quelle eine Blase unter ihrer Kachel."""
    book = db.books()[0]
    verknuepft(db, book.id, "onleihe", "overdrive", "beam")
    sighting(db, book.id, when=NOW, source="onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE, source="overdrive")
    sighting(db, book.id, when=NOW, price=999, source="beam")

    arten = view.build(db, drei_quellen(), book.id).categories

    assert [len(art.sources) for art in arten] == [2, 1]
    # Die beste zuerst, damit die Blasenreihe liest wie die Kachel darueber.
    assert arten[0].sources[0].name == "overdrive"


def test_a_category_without_a_find_has_no_best(db: Store) -> None:
    """Kennt keine Bibliothek das Buch, steht in der Kachel "nicht im Katalog"
    — und kein Name, denn es gibt keinen zu nennen."""
    book = db.books()[0]
    verknuepft(db, book.id, "onleihe", "overdrive", "beam",
               ohne="onleihe")
    db.put_book_source(book.id, "overdrive", outcome=str(LinkOutcome.NOT_FOUND),
                       resolved_at=NOW)
    sighting(db, book.id, when=NOW, price=999, source="beam")

    bibliothek = view.build(db, drei_quellen(), book.id).categories[0]

    assert bibliothek.best is None
    assert len(bibliothek.sources) == 2


# --- die Quellen, eine Zeile je Quelle (#34) --------------------------------


def test_the_section_is_called_sources(client: TestClient, db: Store) -> None:
    """Sie zeigte, welche Quelle welchen Titel meint — das zieht in den roten
    Kasten um. Was bleibt, ist die Uebersicht ueber alle Quellen."""
    book = db.books()[0]
    verknuepft(db, book.id, "beam")

    body = client.get(f"/book/{book.id}").text

    kopf = body[body.index("#ic-plug") :][:200]
    assert "Quellen" in kopf
    assert "Zuordnung" not in kopf


def test_a_library_row_says_how_long_the_wait_is(db: Store) -> None:
    """Statt eines Strichs die Auskunft, die man braucht: wie viele vor mir."""
    book = db.books()[0]
    verknuepft(db, book.id, "onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.UNAVAILABLE,
             source="onleihe", reservations=3)

    sichtung = view.build(db, drei_quellen(), book.id).latest_at("onleihe")

    assert sichtung is not None
    assert sichtung.hold == "3 Vormerkungen"


def test_a_returning_copy_names_the_date(db: Store) -> None:
    book = db.books()[0]
    verknuepft(db, book.id, "onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.UNAVAILABLE,
             source="onleihe", available_from="12.10.2026")

    sichtung = view.build(db, drei_quellen(), book.id).latest_at("onleihe")

    assert sichtung is not None and sichtung.hold == "frei ab 12.10.2026"


def test_a_borrowable_copy_has_nothing_to_wait_for(db: Store) -> None:
    book = db.books()[0]
    verknuepft(db, book.id, "onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE,
             source="onleihe", reservations=0)

    sichtung = view.build(db, drei_quellen(), book.id).latest_at("onleihe")

    assert sichtung is not None and sichtung.hold is None


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
    verknuepft(db, book.id, "onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.UNAVAILABLE,
             source="onleihe", reservations=3)

    bibliothek = view.build(db, drei_quellen(), book.id).categories[0]

    assert bibliothek.best is not None and bibliothek.best.name == "onleihe"
    assert bibliothek.sighting is not None
    assert bibliothek.sighting.availability == "verliehen"


def test_a_borrowable_library_beats_a_lent_out_one(db: Store) -> None:
    book = db.books()[0]
    verknuepft(db, book.id, "onleihe", "overdrive")
    sighting(db, book.id, when=NOW, availability=Availability.UNAVAILABLE, source="onleihe")
    sighting(db, book.id, when=NOW, availability=Availability.AVAILABLE, source="overdrive")

    bibliothek = view.build(db, drei_quellen(), book.id).categories[0]

    assert bibliothek.best is not None and bibliothek.best.name == "overdrive"


# --- ein Titel ohne Fund (#38) ----------------------------------------------


def test_the_judgement_of_a_title_without_a_find_hangs_on_the_book(
    db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ebook_watchlist.ratings import book_subject

    buch = db.books()[0]
    rater = StubRater(Rating(stars=3, reason="Klingt passend.", confidence="duenn",
                             profile_version=1, pitch="Sieben Schwestern."))
    monkeypatch.setattr(view, "build_rater", lambda model: rater)

    grund = view.rate(db, load_settings(), buch.id, now=NOW)

    assert grund == ""
    schluessel = book_subject(buch.id)
    assert db.ratings_for([schluessel])[(schluessel, BY_MODEL)].stars == 3
    # Gefragt wurde ueber Titel und Autor:in — mehr gibt es nicht.
    assert rater.asked[0].title == buch.title


def test_a_find_is_preferred_over_the_bare_title(
    db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sobald es einen Fund gibt, urteilt das Werkzeug ueber den — er traegt
    Preis, Verfuegbarkeit und Klappentext."""
    buch = db.books()[0]
    sighting(db, buch.id, when=NOW, price=999)
    rater = StubRater(Rating(stars=4, reason="Passt.", confidence="teils", profile_version=1))
    monkeypatch.setattr(view, "build_rater", lambda model: rater)

    view.rate(db, load_settings(), buch.id, now=NOW)

    assert db.ratings_for(["item:beam:1"])[("item:beam:1", BY_MODEL)].stars == 4


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


def steckbrief_abwarten(client: TestClient, pfad: str) -> str:
    """Den Knopf druecken und warten, bis der Hintergrundjob fertig ist."""
    client.post(f"{pfad}/steckbrief")
    for _ in range(250):
        stand = client.get(f"{pfad}/steckbrief")
        if stand.headers.get("HX-Refresh") == "true":
            break
        threading.Event().wait(0.02)
    else:
        raise AssertionError("der Steckbrief wurde nicht fertig")
    return client.get(pfad).text


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
    }, ensure_ascii=False)


def test_the_button_draws_a_portrait_once(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dasselbe Buch trägt immer denselben Steckbrief: ein zweiter Klick
    kostet keinen Aufruf (ADR 33)."""
    buch = db.books()[0]
    fragt = StubAsker(_leopard())
    monkeypatch.setattr(view, "build_rater", lambda model: fragt)

    body = steckbrief_abwarten(client, f"/book/{buch.id}")
    steckbrief_abwarten(client, f"/book/{buch.id}")

    assert len(fragt.asked) == 1
    assert f"Titel: {buch.title}" in fragt.asked[0]
    # Nach Familien gruppiert: "brutal" steht unter "hart".
    assert "hart" in body and "gezeichnete Figur" in body
    assert "Der Leopoldsapfel wird genau ausgemalt." in body
    assert "Nordic Noir" in body


def test_a_book_the_model_does_not_know_says_so(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    buch = db.books()[0]
    monkeypatch.setattr(view, "build_rater", lambda model: StubAsker('{"bekannt": false}'))

    body = steckbrief_abwarten(client, f"/book/{buch.id}")

    assert "kennt dieses Buch nicht" in body


def test_without_a_model_nothing_changes_and_the_page_says_why(
    client: TestClient, db: Store
) -> None:
    """Das Tor scheitert nie zu (ADR 7) — und der Steckbrief auch nicht."""
    buch = db.books()[0]

    body = steckbrief_abwarten(client, f"/book/{buch.id}")

    assert "Kein Bewerter eingerichtet" in body


def test_a_failed_call_stores_nothing(db: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    from ebook_watchlist.portrait import fingerprint, load_vocabulary

    buch = db.books()[0]
    monkeypatch.setattr(
        view, "build_rater", lambda model: StubAsker(RatingUnavailable("Zeit abgelaufen"))
    )

    grund = view.portray(db, load_settings(), buch.id, now=NOW)

    assert grund == "Zeit abgelaufen"
    assert db.portrait(view.portrait_subject(buch), fingerprint(load_vocabulary())) is None


def test_a_book_with_an_isbn_keeps_its_portrait_at_the_isbn(
    db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wie ein Urteil des Tors: so findet der Lauf denselben Steckbrief wieder."""
    buch = db.find_or_create_book(isbn="9783548289441", title="Leopard",
                                  author="Jo Nesbø", now=NOW)
    monkeypatch.setattr(view, "build_rater", lambda model: StubAsker(_leopard()))

    view.portray(db, load_settings(), buch.id, now=NOW)

    from ebook_watchlist.portrait import fingerprint, load_vocabulary

    assert db.portrait("isbn:9783548289441", fingerprint(load_vocabulary())).known


def test_a_portrait_survives_the_book_getting_an_isbn(
    db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein Watchlist-Titel bekommt seine ISBN oft erst, wenn ein Lauf ihn
    auflöst. Der Steckbrief von vorher gilt weiter und kostet keinen zweiten
    Aufruf."""
    from sqlalchemy import update

    from ebook_watchlist.store import BookRow

    buch = db.find_or_create_book(isbn=None, title="Leopard", author="Jo Nesbø", now=NOW)
    fragt = StubAsker(_leopard())
    monkeypatch.setattr(view, "build_rater", lambda model: fragt)
    view.portray(db, load_settings(), buch.id, now=NOW)
    with db.session() as session:
        session.execute(update(BookRow).where(BookRow.id == buch.id).values(isbn="9783548289441"))
        session.commit()

    view.portray(db, load_settings(), buch.id, now=NOW)

    assert len(fragt.asked) == 1
    assert view.build(db, load_settings(), buch.id).portrait.known
