"""Die Seite zu einem Fund (Issue #9).

Die Buchseite ohne die Teile, die es vor einer Entscheidung nicht gibt — und
mit den zweien, die sonst nirgends stehen: die ausgeschriebene Begründung des
Übereinstimmung mit dem Leseprofil und der Preisverlauf des Funds.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import describe, give_profile, needs_vocabulary
from ebook_watchlist import paths
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.ratings import subject_of
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app

NOW = datetime(2026, 9, 4, 21, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=False)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def fund(
    db: Store,
    *,
    item_id: str = "7",
    title: str = "Der Kannibalenhügel",
    author: str = "Viktor Sauer",
    price: int | None = 399,
    isbn: str | None = None,
    blurb: str | None = "Ein Schiff, allein im Dunkeln.",
    series: str | None = None,
    when: datetime = NOW,
) -> Observation:
    observation = Observation(
        source="beam",
        source_item_id=item_id,
        title=title,
        author=author,
        match_reason=MatchReason.GENRE_CATEGORY,
        price_cents=price,
        isbn=isbn,
        blurb=blurb,
        series=series,
        category="belletristik/krimi-thriller/psychothriller",
        url=f"https://beam.invalid/{item_id}",
    )
    run_id = db.start_run("test", "cli", when)
    db.append(run_id, "test", [observation], when)
    db.finish_run(run_id, status="ok", delta_count=1, finished_at=when)
    return observation


# --- die Seite --------------------------------------------------------------


def test_a_find_has_a_page_of_its_own(client: TestClient, db: Store) -> None:
    fund(db)

    response = client.get("/discovery/beam/7")

    assert response.status_code == 200
    assert "Der Kannibalenhügel" in response.text
    assert "Viktor Sauer" in response.text
    assert "Ein Schiff, allein im Dunkeln." in response.text


def test_a_find_nobody_ever_saw_is_a_404(client: TestClient, db: Store) -> None:
    assert client.get("/discovery/beam/gibtsnicht").status_code == 404


def test_the_page_names_the_reason_it_turned_up(client: TestClient, db: Store) -> None:
    """Derselbe Anlass wie im Stapel und im Tagesbericht, aus einer Stelle."""
    fund(db)

    body = client.get("/discovery/beam/7").text

    assert "Psychothriller" in body


@needs_vocabulary
def test_the_reasoning_is_readable_here_and_only_here(client: TestClient, db: Store) -> None:
    """Der Stapel zeigt den Pitch, nie die Begründung — ADR 19 wollte sie
    nachprüfbar machen, und dies ist der Ort dafür. Seit #48 rechnet sie der
    Code aus dem Steckbrief."""
    observation = fund(db)
    give_profile(db)
    describe(db, subject_of(observation), 4, "Ein Metzger mit Regeln statt Gewissen.")

    body = client.get("/discovery/beam/7").text

    assert "data-passung" in body and "4 von 5" in body and "66" in body
    assert "Satz zu quest" in body
    assert "Satz zu quest" not in client.get("/suggestions").text


def test_without_a_portrait_the_page_offers_to_make_one(client: TestClient, db: Store) -> None:
    fund(db)

    body = client.get("/discovery/beam/7").text

    assert "Noch kein Steckbrief." in body
    assert "/discovery/beam/7/portrait" in body
    assert "data-passung" not in body


def test_the_price_stands_in_the_tile_of_its_source(client: TestClient, db: Store) -> None:
    """Wie auf der Buchseite: der Preis gehört zu der Quelle, die ihn genannt
    hat, nicht in eine Ecke der Seite. Ein Fund kennt genau eine."""
    for tage, preis in ((3, 1299), (2, 1199), (1, 999)):
        fund(db, price=preis, when=NOW - timedelta(days=tage))

    body = client.get("/discovery/beam/7").text
    kachel = body[body.index("kachel-klickbar") :]
    kachel = kachel[: kachel.index("</a>")]

    assert "9,99 €" in kachel
    assert "Shop" in kachel


def test_the_table_shows_the_last_five_sightings(client: TestClient, db: Store) -> None:
    """Der Snapshot ist anhängend, also steht derselbe Fund dort einmal je Lauf
    — bei einem Titel, an dem sich nichts ändert, waren das elf Zeilen mit
    elfmal demselben Betrag. Dieselbe Grenze wie auf der Buchseite."""
    for tage in range(8):
        fund(db, price=900 + tage, when=NOW - timedelta(days=tage))

    body = client.get("/discovery/beam/7").text

    assert "Beobachtungen" in body
    assert "3 ältere" in body


def test_the_head_names_title_author_and_source_and_nothing_else(
    client: TestClient, db: Store
) -> None:
    """Dieselbe Reihenfolge wie in der Zeile: Titel, Autor, darunter Quelle und
    Anlass. Die ISBN stand zwischen Preis und Titel und gehört keiner
    Entscheidung — sie fällt weg. Und der Anlass steht einmal, als Pille: der
    Satz "neu im Thema Psychothriller" sagte dasselbe ein zweites Mal."""
    fund(db, isbn="9783104911854")

    body = client.get("/discovery/beam/7").text

    assert "9783104911854" not in body
    assert "neu im Thema" not in body
    assert body.index("Der Kannibalenhügel") < body.index("Viktor Sauer")
    assert body.index("Viktor Sauer") < body.index("Psychothriller")


def test_a_taken_back_decision_leads_to_the_find_again(
    client: TestClient, db: Store
) -> None:
    """Zuruecknehmen legt die Beziehung still, loescht sie aber nicht (ADR 18)
    — und die Verknuepfung zur Quelle bleibt ebenfalls. Der Fund steht danach
    wieder im Stapel; sein Titel muss dann auch wieder auf die Fundseite
    fuehren und nicht auf eine Buchseite, auf der nichts mehr gilt."""
    fund(db)
    client.post("/suggestions/decide", data={"kind": "watching", "keys": ["beam:7"]})
    book_id = db.book_by_source_item("beam", "7")
    client.post(
        "/suggestions/undo",
        data={"key": "beam:7", "kind": "watching", "zurueck": "/suggestions"},
    )

    antwort = client.get("/discovery/beam/7")

    assert book_id is not None
    assert antwort.status_code == 200
    assert "Der Kannibalenhügel" in antwort.text


def test_a_decision_with_an_unknown_kind_creates_nothing(
    client: TestClient, db: Store
) -> None:
    """Der Knopf schickt eine der drei Arten; ein handgeschriebenes Formular
    kann alles schicken. Frueher entstand dabei erst die Buch-Zeile und dann
    der Fehler — zurueck blieb ein Buch ohne jede Beziehung, das den Fund von
    seiner eigenen Seite wegleitete."""
    fund(db)

    antwort = client.post(
        "/suggestions/decide", data={"kind": "gefaellt", "keys": ["beam:7"]}
    )

    assert antwort.status_code == 400
    assert db.book_by_source_item("beam", "7") is None


def test_the_page_leaves_out_what_a_find_does_not_have(client: TestClient, db: Store) -> None:
    """Kein Buch heißt: keine Beziehungen, keine Notiz, kein "Prüfen bei"."""
    fund(db)

    body = client.get("/discovery/beam/7").text

    assert "Prüfen bei" not in body
    assert "Beziehungen" not in body
    assert "Notiz" not in body


def test_deciding_here_leads_to_the_new_book(client: TestClient, db: Store) -> None:
    """Mit der Entscheidung wird aus dem Fund ein Buch (ADR 18), und die
    Buchseite ist die reichere Ansicht. In den Stapel zurueckzuspringen hiesse,
    die eigene Entscheidung dort zu suchen, wo sie gerade verschwunden ist."""
    fund(db)

    antwort = client.post(
        "/suggestions/decide",
        data={"kind": "watching", "keys": ["beam:7"], "zurueck": "buch"},
    )

    book_id = db.book_by_source_item("beam", "7")
    assert book_id is not None
    assert antwort.headers["location"] == f"/book/{book_id}"


def test_a_find_that_became_a_book_leads_to_its_book_page(
    client: TestClient, db: Store
) -> None:
    """Nach einer Entscheidung gibt es eine Buchseite — die ist dann die
    reichere Ansicht, und ein alter Link soll nicht daran vorbeiführen."""
    fund(db)
    client.post("/suggestions/decide", data={"kind": "owned", "keys": ["beam:7"]})

    response = client.get("/discovery/beam/7")

    assert response.status_code == 303
    book = next(b for b in db.books() if b.title == "Der Kannibalenhügel")
    assert response.headers["location"] == f"/book/{book.id}"


def test_the_page_links_to_the_source(client: TestClient, db: Store) -> None:
    """Der Weg zur Quelle haengt am Symbol unter dem Autor, wie in der Zeile —
    der Titel bleibt Text, wie auf der Buchseite."""
    fund(db)

    body = client.get("/discovery/beam/7").text

    assert 'href="https://beam.invalid/7"' in body


# --- einen Steckbrief anlegen, wie auf der Buchseite (#15, #48) -------------


@needs_vocabulary
def test_a_find_can_be_described_from_its_page(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bei einem Fund ist ein schlechtes Urteil teurer als bei einem Buch:
    unter drei Sternen verschwindet er aus dem Stapel, und die Leserin sieht
    ihn nie wieder. Derselbe Knopf, derselbe Hintergrundjob wie auf der
    Buchseite — nichts davon nachgebaut."""
    import threading

    from ebook_watchlist.web import book as book_page
    from test_web_book import StubAsker, _leopard

    observation = fund(db, item_id="7")
    give_profile(db)
    asker = StubAsker(_leopard())
    monkeypatch.setattr(book_page, "build_rater", lambda model: asker)

    assert "Noch kein Steckbrief." in client.get("/discovery/beam/7").text

    client.post("/discovery/beam/7/portrait")
    for _ in range(250):
        if client.get("/discovery/beam/7/portrait").headers.get("HX-Refresh") == "true":
            break
        threading.Event().wait(0.02)

    assert len(asker.asked) == 1
    assert db.portrait(subject_of(observation), _stamp()) is not None
    body = client.get("/discovery/beam/7").text
    assert "Noch kein Steckbrief." not in body


@needs_vocabulary
def test_a_second_click_costs_no_second_call(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dasselbe Buch trägt immer denselben Steckbrief (ADR 33)."""
    from ebook_watchlist.web import book as book_page
    from ebook_watchlist.web import discovery
    from test_web_book import StubAsker, _leopard

    fund(db, item_id="7")
    asker = StubAsker(_leopard())
    monkeypatch.setattr(book_page, "build_rater", lambda model: asker)
    from ebook_watchlist.config import load_settings

    for _ in range(2):
        assert discovery.portray(db, load_settings(), "beam", "7", now=NOW) == ""

    assert len(asker.asked) == 1


def test_a_find_nobody_saw_cannot_be_described(db: Store) -> None:
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.web import discovery

    assert "noch niemand gesehen" in discovery.portray(
        db, load_settings(), "beam", "gibt-es-nicht", now=NOW
    )


def _stamp() -> str:
    from ebook_watchlist.portrait import fingerprint, load_vocabulary

    return fingerprint(load_vocabulary())
