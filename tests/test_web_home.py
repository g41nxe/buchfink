"""Die Startseite unter ``/`` und der Umzug der Übersicht nach ``/uebersicht`` (Issue #5)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_profile
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.run import main as run_main
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app, home, watchlist
from test_web_triage import found


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def seen(db: Store, book_id: int, *, price: int | None, available: bool) -> None:
    """Eine Beobachtung *an einem Buch*, wie ein echter Lauf sie schreibt.

    Die Attrappe ``fake`` verknüpft ihre Funde nicht mit Büchern (kein
    ``book_id``, keine Quelle) — über sie bekäme die Watchlist nie einen Preis
    zu sehen. Hier steht deshalb, was der Matcher sonst tut.
    """
    from ebook_watchlist.models import Availability

    now = datetime.now()
    run_id = db.start_run("test", "cron", now)
    db.append(
        run_id,
        "test",
        [
            Observation(
                source="fake",
                source_item_id=f"buch-{book_id}",
                title="",
                match_reason=MatchReason.WATCHLIST,
                book_id=book_id,
                price_cents=price,
                availability=Availability.AVAILABLE if available else Availability.UNAVAILABLE,
            )
        ],
        now,
    )
    db.finish_run(run_id, status="ok", delta_count=1, finished_at=now)


def finished_run(
    db: Store, *, finished_at: datetime, deltas: int = 0, error: str | None = None
) -> None:
    run_id = db.start_run("test", "cron", finished_at - timedelta(minutes=5))
    db.finish_run(
        run_id,
        status="error" if error else "ok",
        delta_count=deltas,
        finished_at=finished_at,
        error=error,
    )


# --- vor dem ersten Lauf ----------------------------------------------------


def test_the_root_is_the_start_page_not_the_dashboard(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Tagesberichte" not in response.text
    assert "Läufe" not in response.text


def test_before_the_first_run_the_page_explains_and_points_to_the_watchlist(
    client: TestClient,
) -> None:
    """Drei Aufgaben eines Leerzustands: Zustand, nächster Schritt, Erklärung."""
    body = client.get("/").text

    assert "Noch kein Lauf" in body
    assert 'href="/watchlist"' in body
    assert "Jeder Stern hat einen Grund" in body
    assert "zuletzt geprüft" not in body


def test_the_empty_state_greets_with_the_hero(client: TestClient) -> None:
    """Das einzige Bild der Startseite, und nur hier: ein Willkommensgruss vor
    dem ersten Lauf, keine Ablenkung, sobald echte Daten da sind."""
    body = client.get("/").text

    assert "hero-lesezimmer.jpg" in body


def test_a_broken_configuration_is_reported_on_the_start_page_too(
    client: TestClient, data_dir: Path
) -> None:
    (data_dir / "profile.yaml").unlink()

    response = client.get("/")

    assert response.status_code == 500
    assert "Traceback" not in response.text


# --- die Statuszeile --------------------------------------------------------


def test_after_a_run_the_status_line_says_when_and_how_much(client: TestClient) -> None:
    run_main([])

    body = client.get("/").text

    assert "zuletzt geprüft" in body
    assert f"{datetime.now():%d.%m.}" in body
    assert "Änderung" in body
    assert "Noch kein Lauf" not in body
    # Die Vorstellung gehoert dem Erstbesuch — wer laeuft, kennt sie.
    assert "Jeder Stern hat einen Grund" not in body


def test_a_run_older_than_a_day_says_so_in_words(client: TestClient, db: Store) -> None:
    """Eine Farbe allein wäre für jemanden mit Farbsehschwäche keine Information."""
    finished_run(db, finished_at=datetime.now() - timedelta(days=2, hours=1))

    body = client.get("/").text

    assert "vor 2 Tagen" in body


def test_a_failed_last_run_is_named_not_counted(client: TestClient, db: Store) -> None:
    finished_run(db, finished_at=datetime.now(), error="beam: kaputt")

    body = client.get("/").text

    assert "letzter Lauf fehlgeschlagen" in body
    assert "0 Änderungen" not in body


def test_the_change_count_leads_to_the_latest_report(client: TestClient, db: Store) -> None:
    """Die Statuszeile ist nicht nur Auskunft: "3 Änderungen" ist der Weg zu
    dem, was der Lauf gefunden hat."""
    finished_run(db, finished_at=datetime.now(), deltas=3)
    digests = paths.digests_dir()
    digests.mkdir(parents=True, exist_ok=True)
    (digests / "digest-2026-09-06.html").write_text("<p>alt</p>", encoding="utf-8")
    (digests / "digest-2026-09-07.html").write_text("<p>neu</p>", encoding="utf-8")

    body = client.get("/").text

    marker = body.index("3 Änderungen")
    assert 'href="/digest/digest-2026-09-07.html"' in body[marker - 200 : marker]
    assert "digest-2026-09-06" not in body


def test_without_a_report_the_change_count_is_plain_text(client: TestClient, db: Store) -> None:
    finished_run(db, finished_at=datetime.now(), deltas=0)

    body = client.get("/").text

    assert "0 Änderungen" in body
    assert "/digest/" not in body


def test_the_start_page_offers_to_run_now(client: TestClient, db: Store) -> None:
    """Wo "vor 1 Tag" in Bernstein steht, gehört die Handbewegung daneben —
    derselbe Lauf-Knopf wie auf der Übersicht, nicht ein Link dorthin."""
    finished_run(db, finished_at=datetime.now() - timedelta(days=1, hours=2))

    body = client.get("/").text

    assert "Jetzt prüfen" in body
    assert 'hx-post="/run"' in body


def test_while_a_run_is_going_the_start_page_shows_it_instead_of_the_button(
    client: TestClient, db: Store
) -> None:
    """Kein zweiter Lauf: der Knopf ist weg, solange einer läuft — dieselbe
    Regel wie auf der Übersicht, dasselbe Panel."""
    import os

    finished_run(db, finished_at=datetime.now() - timedelta(days=1))
    db.start_run("test", "cron", datetime.now(), pid=os.getpid())

    body = client.get("/").text

    assert 'id="run-panel"' in body
    assert "läuft" in body.lower()
    assert 'hx-post="/run"' not in body


# --- jetzt zu haben ---------------------------------------------------------


def test_a_cheap_and_borrowable_watchlist_title_is_offered(
    client: TestClient, db: Store
) -> None:
    schwestern = next(b for b in db.books() if b.title == "Die sieben Schwestern")
    seen(db, schwestern.id, price=399, available=True)

    body = client.get("/").text

    assert "1 jetzt zu haben" in body
    assert "Die sieben Schwestern" in body
    assert "3,99 €" in body
    assert "ausleihbar" in body


def test_an_offer_carries_the_same_actions_as_on_the_watchlist(
    client: TestClient, db: Store
) -> None:
    """Dieselbe Zeile soll ueberall dasselbe anbieten (#22): die Zeilen hier
    trugen gar nichts, waehrend die Vorschlaege darunter drei Zeichen hatten."""
    schwestern = next(b for b in db.books() if b.title == "Die sieben Schwestern")
    seen(db, schwestern.id, price=399, available=True)

    body = client.get("/").text

    for label in ("Ausschließen", "Hab ich", "jetzt nachsehen", "pausieren"):
        assert f'aria-label="{label}"' in body


def test_finishing_an_offer_stays_on_the_start_page(client: TestClient, db: Store) -> None:
    """Wer hier entscheidet, will hier bleiben — und den Weg zurueck hier haben."""
    schwestern = next(b for b in db.books() if b.title == "Die sieben Schwestern")
    seen(db, schwestern.id, price=399, available=True)

    antwort = client.post(
        f"/watchlist/{schwestern.id}/abschliessen",
        data={"kind": "owned", "zurueck": "/"},
    )

    assert antwort.url.path == "/"
    assert "Rückgängig" in antwort.text


def test_a_title_that_is_neither_cheap_nor_borrowable_stays_off_the_front(
    client: TestClient,
) -> None:
    run_main([])

    body = client.get("/").text

    assert "0 jetzt zu haben" in body
    assert "Die sieben Schwestern" not in body


def test_at_most_five_offers_are_shown_cheapest_first(db: Store) -> None:
    now = datetime.now()
    for number in range(6):
        book_id = watchlist.add(db, "test", title=f"Billig {number}", author=None, now=now)
        run_id = db.start_run("test", "cli", now)
        db.append(
            run_id, "test",
            [Observation(source="fake", source_item_id=f"b{number}", title=f"Billig {number}",
                         match_reason=MatchReason.WATCHLIST, book_id=book_id,
                         price_cents=100 + number * 50)],
            now,
        )

    view = home.build(db, load_profile(), now=now)

    assert [entry.title for entry in view.offers] == [f"Billig {n}" for n in range(5)]
    assert view.offers_total == 6


# --- zu entscheiden ---------------------------------------------------------


def test_open_suggestions_are_offered_with_the_three_decisions(
    client: TestClient, db: Store
) -> None:
    # ``found`` beendet seinen Lauf nicht — ohne einen abgeschlossenen sähe die
    # Seite zu Recht "noch kein Lauf".
    finished_run(db, finished_at=datetime.now())
    found(db, item_id="7", title="Der Kannibalenhügel", author="Viktor Sauer")

    body = client.get("/").text

    assert "1 von 1 zu entscheiden" in body
    assert "Der Kannibalenhügel" in body
    assert 'action="/vorschlaege/entscheiden"' in body
    for kind in ("dismissed", "owned", "watching"):
        assert f'value="{kind}"' in body


def test_each_decision_has_its_own_distinct_icon(client: TestClient, db: Store) -> None:
    """Drei verschiedene Handlungen brauchen drei verschiedene Zeichen —
    ic-play und ic-user waren beide schon anderswo besetzt (Watchlist-Zeile,
    Autor:innen-Liste des Profils) und passten inhaltlich nicht."""
    finished_run(db, finished_at=datetime.now())
    found(db, item_id="7", title="Der Kannibalenhügel")

    body = client.get("/").text
    form = body[body.index('action="/vorschlaege/entscheiden"') :]
    form = form[: form.index("</form>")]

    def icon_of(kind: str) -> str:
        rest = form[form.index(f'value="{kind}"') :]
        return re.search(r'use href="#(ic-\w+)"', rest).group(1)

    zeichen = {icon_of(kind) for kind in ("dismissed", "owned", "watching")}
    assert len(zeichen) == 3, f"nicht drei verschiedene Zeichen: {zeichen}"
    # Fernglas, nicht Lupe: die Lupe heisst ueberall "suchen", und gesucht
    # wird hier gerade nicht — beobachtet wird von weitem.
    assert icon_of("watching") == "ic-binoculars"
    # Ein Verweis auf ein Zeichen, das es im Sprite nicht gibt, bleibt leer
    # und faellt niemandem auf ausser der Leserin.
    for zeichen_name in zeichen:
        assert f'<symbol id="{zeichen_name}"' in body


def test_the_owned_button_is_coloured_like_a_purchase_not_like_the_library(
    client: TestClient, db: Store
) -> None:
    """"Hab ich" heißt meist: gekauft — dieselbe Farbe wie Schnäppchen und
    Shop im ganzen Theme, nicht das Bibliotheksgrün von "Beobachten"."""
    finished_run(db, finished_at=datetime.now())
    found(db, item_id="7", title="Der Kannibalenhügel")

    body = client.get("/").text
    form = body[body.index('action="/vorschlaege/entscheiden"') :]
    start = form.index('value="owned"')
    knopf = form[start : form.index("</button>", start)]

    assert "hover:text-amber" in knopf
    assert "hover:text-accent" not in knopf


def test_a_decision_is_a_verb_on_the_button_and_the_same_verb_on_the_pile(
    client: TestClient, db: Store
) -> None:
    """Der Knopf sagt, was du *tust*; der Zustandsname ("im Besitz") bleibt der
    Buchseite. Und ein Wort ist ein Wort: Startseite und Stapel sagen dasselbe
    (ADR 22) — genau die Drift, die 7cc1931 schon einmal eingefangen hat."""
    finished_run(db, finished_at=datetime.now())
    found(db, item_id="7", title="Der Kannibalenhügel")

    start = client.get("/").text
    stapel = client.get("/vorschlaege").text

    for wort in ("Ausschließen", "Hab ich", "Beobachten"):
        assert wort in start, wort
        assert wort in stapel, wort
    assert "Ausgeschlossen" not in start


def test_deciding_from_the_start_page_returns_to_the_start_page(
    data_dir: Path, db: Store
) -> None:
    """Wer auf der Startseite entscheidet, will die Startseite wiedersehen —
    nicht den Stapel, auf dem er nie war."""
    finished_run(db, finished_at=datetime.now())
    found(db, item_id="7", title="Der Kannibalenhügel")
    client = TestClient(create_app(), raise_server_exceptions=False, follow_redirects=False)

    response = client.post(
        "/vorschlaege/entscheiden",
        data={"kind": "owned", "keys": ["beam:7"], "zurueck": "/"},
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/")
    assert not response.headers["location"].startswith("/vorschlaege")


def test_a_foreign_return_address_leads_back_to_the_pile(data_dir: Path, db: Store) -> None:
    """Ein Formularfeld ist kein Ziel — sonst leitet ein untergeschobenes Feld
    auf eine fremde Adresse (dasselbe Muster wie `_zurueck` der Watchlist)."""
    found(db, item_id="7")
    client = TestClient(create_app(), raise_server_exceptions=False, follow_redirects=False)

    response = client.post(
        "/vorschlaege/entscheiden",
        data={"kind": "dismissed", "keys": ["beam:7"], "zurueck": "https://boese.invalid/"},
    )

    assert response.headers["location"] == "/vorschlaege"


# --- rueckgaengig -----------------------------------------------------------


def test_after_a_decision_the_start_page_offers_to_take_it_back(
    data_dir: Path, db: Store
) -> None:
    """Ein Klick, keine Nachfrage — dafür ein Weg zurück an Ort und Stelle.
    ADR 18 löscht nichts, also ist jede der drei Handlungen umkehrbar."""
    finished_run(db, finished_at=datetime.now())
    found(db, item_id="7", title="Der Kannibalenhügel")
    client = TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)

    body = client.post(
        "/vorschlaege/entscheiden",
        data={"kind": "dismissed", "keys": ["beam:7"], "zurueck": "/"},
    ).text

    assert "Rückgängig" in body
    assert "Der Kannibalenhügel" in body
    assert 'action="/vorschlaege/zuruecknehmen"' in body
    assert "0 von 0 zu entscheiden" in body


def test_taking_a_decision_back_puts_the_find_back_on_the_pile(
    data_dir: Path, db: Store
) -> None:
    finished_run(db, finished_at=datetime.now())
    found(db, item_id="7", title="Der Kannibalenhügel")
    client = TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)
    client.post(
        "/vorschlaege/entscheiden", data={"kind": "owned", "keys": ["beam:7"], "zurueck": "/"}
    )

    body = client.post(
        "/vorschlaege/zuruecknehmen", data={"key": "beam:7", "kind": "owned", "zurueck": "/"}
    ).text

    assert "1 von 1 zu entscheiden" in body
    assert "Der Kannibalenhügel" in body
    assert "Rückgängig" not in body
    book = next(b for b in db.books() if b.title == "Der Kannibalenhügel")
    assert not any(
        row.active for row in db.relations_of("test", book.id) if row.kind == "owned"
    )


def test_the_columns_show_what_the_profile_says_and_count_the_rest(
    client: TestClient, db: Store
) -> None:
    """Wie viele Zeilen je Spalte stehen, haengt am Bildschirm der Leserin und
    nicht am Werkzeug — drei Vorschlaege sind die Voreinstellung, nicht das
    Gesetz. Was nicht gezeigt wird, ist gezaehlt: der Verweis darunter traegt
    die Zahl."""
    # Der abgeschlossene Lauf zuletzt: jeder Fund legt selbst einen an, und
    # ``recent_runs`` sieht nur fuenf zurueck — davor faellt der abgeschlossene
    # aus dem Fenster, und die Seite zeigt den Leerzustand.
    for number in range(5):
        found(db, item_id=str(number), title=f"Fund {number}")
    finished_run(db, finished_at=datetime.now())

    body = client.get("/").text

    assert "3 von 5 zu entscheiden" in body
    assert body.count('action="/vorschlaege/entscheiden"') == 3


def test_another_profile_shows_another_number(data_dir: Path, db: Store) -> None:
    """Zwei Zahlen im Profil, keine Konstante im Code."""
    from dataclasses import replace

    from ebook_watchlist.config import load_profile
    from ebook_watchlist.web import home as view

    for number in range(5):
        found(db, item_id=str(number), title=f"Fund {number}")
    finished_run(db, finished_at=datetime.now())

    knapp = replace(load_profile(), home_suggestions=1)
    seite = view.build(db, knapp, now=datetime.now())

    assert len(seite.suggestions) == 1
    assert seite.suggestions_total == 5


# --- Der Umzug --------------------------------------------------------------


def test_the_dashboard_lives_at_uebersicht(client: TestClient) -> None:
    response = client.get("/uebersicht")

    assert response.status_code == 200
    assert "Noch kein Lauf verzeichnet" in response.text


def test_the_navigation_leads_home_and_the_dashboard_stays_reachable(
    client: TestClient,
) -> None:
    """Vier Punkte, und einer davon fuehrt nach Hause: die Uebersicht ist ein
    Zustand der Quellen, den man nicht taeglich aufschlaegt. Verschwinden darf
    sie deswegen nicht — der Zeitpunkt auf der Startseite fuehrt hin, denn
    dort stehen die Laeufe, aus denen er kommt."""
    body = client.get("/watchlist").text

    assert ">Home<" in body
    assert ">Übersicht<" not in body
    assert 'href="/uebersicht"' in client.get("/").text


def test_the_emblem_and_the_name_lead_home(client: TestClient) -> None:
    body = client.get("/uebersicht").text

    assert re.search(r'<a href="/"[^>]*>\s*<img', body), "das Zeichen führt nicht auf /"
    assert re.search(r'<a href="/"[^>]*>Buchfink</a>', body), "der Name führt nicht auf /"
