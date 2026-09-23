"""Die Erstaufnahme, Bildschirme 1 und 2: Bücher nennen und bestätigen (#47).

Das Modell ist ein Stellvertreter, der je Titel eine feste Antwort gibt; die
Antworten ähneln denen aus dem Versuch vom 23.09.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import intake
from ebook_watchlist.web.app import create_app

NOW = datetime(2026, 9, 24, 3, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def _antwort(titel, autor, original=None, genre="Science-Fiction") -> str:
    return json.dumps({
        "bekannt": True, "titel": titel, "autor": autor, "originaltitel": original,
        "genre": genre, "untergenre": None, "pitch": "Ein Buch.",
        "merkmale": [
            {"id": "world_building", "satz": "Eine Welt aus Welten.", "beleg": "wissen"},
            {"id": "intricate", "satz": "Viele Stränge.", "beleg": "wissen"},
            {"id": "leisurely", "satz": "Nimmt sich Zeit.", "beleg": "wissen"},
            {"id": "ensemble", "satz": "Eine Gruppe.", "beleg": "wissen"},
        ],
        "erzaehlmuster": [{"id": "quest", "satz": "Sie ziehen los.", "beleg": "wissen"}],
    }, ensure_ascii=False)


ANTWORTEN = {
    "Otherland": _antwort("Otherland", "Tad Williams"),
    "Cry Baby": _antwort("Cry Baby", "Gillian Flynn", "Sharp Objects", "Thriller"),
    "Herr der Ringe": _antwort("Der Herr der Ringe", "J. R. R. Tolkien", "The Lord of the Rings",
                               "Fantasy"),
    "Leichenblässe": _antwort("Leichenblässe", "Simon Beckett", "Whispers of the Dead",
                              "Kriminalroman"),
    "Leopard": _antwort("Leopard", "Jo Nesbø", "Panserhjerte", "Kriminalroman"),
    "Das Buch, das es nicht gibt": json.dumps({"bekannt": False}),
}


class Modell:
    """Antwortet je nach Titel in der Anfrage und zählt mit."""

    def __init__(self) -> None:
        self.gefragt: list[str] = []

    def ask(self, text: str, max_tokens: int = 300) -> str:
        titel = text.split("Titel: ")[1].split("\n")[0]
        self.gefragt.append(titel)
        return ANTWORTEN[titel]


@pytest.fixture
def modell(monkeypatch: pytest.MonkeyPatch) -> Modell:
    m = Modell()
    monkeypatch.setattr(intake, "build_rater", lambda model: m)
    return m


def nennen(client: TestClient, titel: str, autor: str = "", seite: str = "liked") -> str:
    client.post("/erstaufnahme/buch", data={"seite": seite, "titel": titel, "autor": autor})
    return abwarten(client)


def abwarten(client: TestClient) -> str:
    """Warten, bis kein Eintrag mehr sucht."""
    for _ in range(250):
        body = client.get("/erstaufnahme").text
        if 'data-zustand="asking"' not in body or "Nochmal" in body:
            return body
        threading.Event().wait(0.02)
    raise AssertionError("die Erstaufnahme wurde nicht fertig")


def _eintrag(db: Store, titel: str):
    return next(r for r in db.intake_entries(load_settings().slug) if r.typed_title == titel)


# --- nennen und erkennen ---------------------------------------------------------


def test_a_typo_in_the_author_leads_to_a_confirmable_proposal(client, modell) -> None:
    body = nennen(client, "Otherland", "Ted Williams")

    assert "Meinst du" in body and "Tad Williams" in body


def test_a_german_title_names_the_original(client, modell) -> None:
    body = nennen(client, "Cry Baby")

    assert "Cry Baby" in body and "Sharp Objects" in body and "Gillian Flynn" in body


def test_it_works_without_any_history(client, db, modell) -> None:
    """Kein Klappentext, kein Buch im Bestand: der Titel reicht."""
    vorher = len(db.books())

    nennen(client, "Otherland")

    assert len(db.books()) == vorher
    assert modell.gefragt == ["Otherland"]


def test_a_book_the_model_does_not_know_says_so_and_offers_no_yes(client, db, modell) -> None:
    body = nennen(client, "Das Buch, das es nicht gibt")

    assert "kennt das Modell nicht" in body and "trägt nichts" in body
    eintrag = _eintrag(db, "Das Buch, das es nicht gibt")
    assert f"/erstaufnahme/buch/{eintrag.id}/ja" not in body


def test_the_same_title_is_not_asked_twice(client, modell) -> None:
    nennen(client, "Otherland")
    nennen(client, "Otherland", seite="disliked")

    assert modell.gefragt == ["Otherland"]


def test_without_a_model_the_entry_says_why_and_can_be_retried(client) -> None:
    body = nennen(client, "Otherland")

    assert "Kein Bewerter eingerichtet" in body and "Nochmal" in body


# --- bestätigen --------------------------------------------------------------------


def test_yes_puts_the_book_on_the_shelf_with_its_portrait(client, db, modell) -> None:
    nennen(client, "Otherland", "Ted Williams")
    eintrag = _eintrag(db, "Otherland")

    client.post(f"/erstaufnahme/buch/{eintrag.id}/ja")

    buch_id = db.intake_entry(eintrag.id).book_id
    buch = db.book(buch_id)
    assert (buch.title, buch.author) == ("Otherland", "Tad Williams")
    liked = [r.book_id for r in db.relations(load_settings().slug, kind=RelationKind.LIKED)]
    assert buch_id in liked
    # Der Steckbrief ist mitgezogen: die Buchseite fragt nicht noch einmal.
    assert "Eine Welt aus Welten." in client.get(f"/book/{buch_id}").text
    assert modell.gefragt == ["Otherland"]


def test_a_disappointing_book_lands_on_the_other_shelf(client, db, modell) -> None:
    nennen(client, "Herr der Ringe", seite="disliked")
    eintrag = _eintrag(db, "Herr der Ringe")

    client.post(f"/erstaufnahme/buch/{eintrag.id}/ja")

    doof = [r.book_id for r in db.relations(load_settings().slug, kind=RelationKind.DISLIKED)]
    assert db.intake_entry(eintrag.id).book_id in doof


def test_the_books_stand_in_the_shelves_of_the_profile_page(client, db, modell) -> None:
    nennen(client, "Cry Baby")
    client.post(f"/erstaufnahme/buch/{_eintrag(db, 'Cry Baby').id}/ja")

    assert "Cry Baby" in client.get("/profil").text


def test_another_book_asks_again_with_what_was_typed(client, db, modell) -> None:
    nennen(client, "Das Buch, das es nicht gibt")
    eintrag = _eintrag(db, "Das Buch, das es nicht gibt")

    client.post(f"/erstaufnahme/buch/{eintrag.id}/anders",
                data={"titel": "Leopard", "autor": "Jo Nesbø"})
    body = abwarten(client)

    assert "Panserhjerte" in body
    assert modell.gefragt == ["Das Buch, das es nicht gibt", "Leopard"]


def test_removing_an_entry_frees_its_place(client, db, modell) -> None:
    nennen(client, "Otherland")
    eintrag = _eintrag(db, "Otherland")

    body = client.post(f"/erstaufnahme/buch/{eintrag.id}/weg").text

    assert "Otherland" not in body


# --- nichts geht verloren ------------------------------------------------------------


def test_an_entry_is_saved_before_the_model_answers(db, data_dir) -> None:
    eintrag = intake.add(db, load_settings(), "liked", "Otherland", None, now=NOW)

    assert db.intake_entry(eintrag).typed_title == "Otherland"


def test_an_open_entry_is_asked_again_when_the_page_opens(client, db, modell) -> None:
    """Nach einem Abbruch — Server neu gestartet, Seite geschlossen — holt die
    Seite nach, was offen war."""
    intake.add(db, load_settings(), "liked", "Otherland", None, now=NOW)

    body = abwarten(client)

    assert "Tad Williams" in body


# --- Grenzen und Weiter ---------------------------------------------------------------


def test_no_more_than_five_per_side(db, data_dir) -> None:
    for i in range(5):
        intake.add(db, load_settings(), "disliked", f"Buch {i}", None, now=NOW)

    with pytest.raises(intake.IntakeError, match="fünf|5"):
        intake.add(db, load_settings(), "disliked", "Buch 6", None, now=NOW)


def test_a_title_is_required(db, data_dir) -> None:
    with pytest.raises(intake.IntakeError, match="Titel"):
        intake.add(db, load_settings(), "liked", "  ", None, now=NOW)


def test_three_confirmed_loved_books_open_the_way_on(client, db, modell) -> None:
    for titel in ("Otherland", "Cry Baby", "Leichenblässe"):
        nennen(client, titel)
        client.post(f"/erstaufnahme/buch/{_eintrag(db, titel).id}/ja")

    body = client.get("/erstaufnahme").text

    assert "3 geliebte" in body and "stehen in deinen Regalen" in body


def test_the_profile_page_leads_into_the_intake(client) -> None:
    body = client.get("/profil").text

    assert 'href="/erstaufnahme"' in body and "Erstaufnahme beginnen" in body
