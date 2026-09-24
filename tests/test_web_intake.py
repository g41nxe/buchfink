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
    client.post("/intake/entry", data={"side": seite, "title": titel, "author": autor})
    return abwarten(client)


def abwarten(client: TestClient) -> str:
    """Warten, bis kein Eintrag mehr sucht."""
    for _ in range(250):
        body = client.get("/intake").text
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
    assert f"/intake/entry/{eintrag.id}/confirm" not in body


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

    client.post(f"/intake/entry/{eintrag.id}/confirm")

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

    client.post(f"/intake/entry/{eintrag.id}/confirm")

    doof = [r.book_id for r in db.relations(load_settings().slug, kind=RelationKind.DISLIKED)]
    assert db.intake_entry(eintrag.id).book_id in doof


def test_the_books_stand_in_the_shelves_of_the_profile_page(client, db, modell) -> None:
    nennen(client, "Cry Baby")
    client.post(f"/intake/entry/{_eintrag(db, 'Cry Baby').id}/confirm")

    assert "Cry Baby" in client.get("/profile").text


def test_another_book_asks_again_with_what_was_typed(client, db, modell) -> None:
    nennen(client, "Das Buch, das es nicht gibt")
    eintrag = _eintrag(db, "Das Buch, das es nicht gibt")

    client.post(f"/intake/entry/{eintrag.id}/retype",
                data={"title": "Leopard", "author": "Jo Nesbø"})
    body = abwarten(client)

    assert "Panserhjerte" in body
    assert modell.gefragt == ["Das Buch, das es nicht gibt", "Leopard"]


def test_removing_an_entry_frees_its_place(client, db, modell) -> None:
    nennen(client, "Otherland")
    eintrag = _eintrag(db, "Otherland")

    body = client.post(f"/intake/entry/{eintrag.id}/remove").text

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
        client.post(f"/intake/entry/{_eintrag(db, titel).id}/confirm")

    body = client.get("/intake").text

    assert "3 geliebte" in body and "stehen in deinen Regalen" in body


def test_the_profile_page_leads_into_the_intake(client) -> None:
    body = client.get("/profile").text

    assert 'href="/intake"' in body and "Erstaufnahme beginnen" in body


# --- Bildschirme 3 bis 5: das Gemeinsame, das Verlorene, dein Profil (#50) ------


def _bild(genre, untergenre, merkmale, muster="quest"):
    from ebook_watchlist.portrait import load_vocabulary, parse_answer

    return parse_answer(json.dumps({
        "bekannt": True, "titel": "x", "autor": "y", "genre": genre, "untergenre": untergenre,
        "pitch": "Ein Buch.",
        "merkmale": [{"id": m, "satz": f"Satz zu {m}.", "beleg": "wissen"} for m in merkmale],
        "erzaehlmuster": [{"id": muster, "satz": "Muster.", "beleg": "wissen"}],
    }), load_vocabulary())


def bestaetigt(db: Store, seite: str, titel: str, bild) -> int:
    """Ein Buch, wie es nach Bildschirm 1 und 2 dasteht: genannt, erkannt, bestätigt."""
    from dataclasses import replace

    eintrag = intake.add(db, load_settings(), seite, titel, None, now=NOW)
    db.put_portrait(intake.intake_subject(titel, None), replace(bild, title=titel), now=NOW)
    return intake.confirm(db, load_settings(), eintrag, now=NOW)


@pytest.fixture
def buecher(db: Store) -> dict[str, int]:
    """Drei geliebte Bücher und ein enttäuschendes, nach dem Versuch vom 23.09.

    Leichenblässe und Kruzifix Killer teilen hart und gezeichnete Figur;
    Leichenblässe und Otherland den Schauplatz; Herr der Ringe trägt die große
    Welt wie Otherland, und gemächlich für sich allein.
    """
    return {
        "L": bestaetigt(db, "liked", "Leichenblässe", _bild(
            "Kriminalroman", None, ["violent", "brooding", "menacing", "atmospheric"],
            "pursuit")),
        "K": bestaetigt(db, "liked", "Kruzifix Killer", _bild(
            "Thriller", None, ["violent", "brooding", "flawed", "menacing"], "pursuit")),
        "O": bestaetigt(db, "liked", "Otherland", _bild(
            "Science-Fiction", "Cyberpunk", ["world_building", "intricate", "atmospheric",
                                             "ensemble"])),
        "H": bestaetigt(db, "disliked", "Herr der Ringe", _bild(
            "Fantasy", "High Fantasy / Heroische Fantasy",
            ["world_building", "leisurely", "bittersweet", "descriptive"])),
    }


HX = {"HX-Request": "true"}


def tippen(client, familie, seite="loved", buch=None, an=True, schritt=3) -> str:
    daten = {"side": seite, "family": familie, "on": "1" if an else "", "step": schritt}
    if buch is not None:
        daten["book"] = buch
    return client.post("/intake/choice", data=daten, headers=HX).text


def test_screen_3_groups_the_families_by_the_books_that_carry_them(client, buecher) -> None:
    body = client.get("/intake/common").text

    assert "Weil du" in body and "mochtest" in body
    assert "Nur in" in body
    # Titel in Serifen, und ein Buch nur in der Überschrift.
    assert '<span class="font-serif italic text-ink">Kruzifix Killer</span>' in body


def test_a_tap_is_saved_and_the_profile_grows_below(client, db, buecher) -> None:
    tippen(client, "harsh")
    body = tippen(client, "brooding")

    assert 'data-facette="harsh,brooding"' in body
    assert {c.family_id for c in db.intake_choices(load_settings().slug)} == {"harsh", "brooding"}


def test_a_single_family_shows_as_too_broad(client, buecher) -> None:
    body = tippen(client, "atmospheric")

    assert "zu breit" in body


def test_a_loved_book_in_no_facet_is_asked_for(client, buecher) -> None:
    """Die Abdeckungsregel: Otherland steckt nach hart und gezeichneter Figur in
    keiner Facette und wird mit allem gefragt, was es trägt."""
    tippen(client, "harsh")
    body = tippen(client, "brooding")

    assert "data-abdeckung" in body
    abdeckung = body.split("data-abdeckung", 1)[1].split("</aside>")[0]
    assert "Otherland" in abdeckung and 'data-familie="intricate"' in abdeckung


def test_a_lost_family_a_loved_book_also_carries_asks_how_far(client, buecher) -> None:
    body = tippen(client, "big_world", seite="lost", buch=buecher["H"], schritt=4)

    assert 'data-nachfrage="big_world"' in body
    assert "nur bei High Fantasy" in body
    # Voreingestellt nur bei diesem Buch: es zählt noch gegen nichts.
    assert "Nur an diesem einen Buch gestört" in body


def test_with_the_genre_it_becomes_a_bundle(client, buecher) -> None:
    tippen(client, "big_world", seite="lost", buch=buecher["H"], schritt=4)

    body = client.post("/intake/scope",
                       data={"family": "big_world", "book": buecher["H"], "scope": "genre"},
                       headers=HX).text

    entwurf = body.split("data-entwurf", 1)[1]
    assert "große Welt" in entwurf and "nur bei High Fantasy" in entwurf


def test_a_lost_family_no_loved_book_carries_counts_everywhere(client, buecher) -> None:
    body = tippen(client, "leisurely", seite="lost", buch=buecher["H"], schritt=4)

    assert "data-nachfrage" not in body
    assert "gemächlich" in body.split("Zählt gegen ein Buch", 1)[1]


def test_adopting_saves_the_first_version_and_the_code_judges(client, db, buecher) -> None:
    tippen(client, "harsh")
    tippen(client, "brooding")
    tippen(client, "leisurely", seite="lost", buch=buecher["H"], schritt=4)

    antwort = client.post("/intake/profile",
                          data={"facet": ["0"], "counterweight": ["0"]})

    profil = db.reading_profile(load_settings().slug)
    assert profil.version == 1
    assert profil.facets[0].families == ("harsh", "brooding")
    assert profil.counterweights[0].families == ("leisurely",)
    assert "Dein Leseprofil" in antwort.text
    # Sofort geurteilt: Kruzifix Killer trifft die Facette ganz.
    assert "Übereinstimmung mit deinen Facetten" in client.get(f"/book/{buecher['K']}").text


def test_deselecting_everything_starts_over(client, db, buecher) -> None:
    tippen(client, "harsh")
    tippen(client, "brooding")

    antwort = client.post("/intake/profile", data={})

    assert db.reading_profile(load_settings().slug) is None
    assert db.intake_entries(load_settings().slug) == []
    assert db.intake_choices(load_settings().slug) == []
    assert "Erstaufnahme" in antwort.text
    # Die bestätigten Bücher bleiben im Regal (ADR 5).
    liked = [r.book_id for r in db.relations(load_settings().slug, kind=RelationKind.LIKED)]
    assert buecher["L"] in liked


def test_frequent_families_go_last_only_with_a_neutral_stock(db, buecher) -> None:
    """Gemessen am neutralen Bestand, nie an den eigenen Büchern (#44)."""
    from ebook_watchlist.portrait import load_vocabulary

    wort = load_vocabulary()
    assert intake.frequent_families(db, load_settings(), wort) == set()

    for i in range(intake.NEUTRAL_MIN_BOOKS):
        merkmale = ["atmospheric", "fast_paced", "funny", "likeable"] if i % 2 else \
            ["atmospheric", "leisurely", "bittersweet", "lyrical"]
        db.put_portrait(f"item:x:{i}", _bild("Roman", None, merkmale), now=NOW)

    haeufig = intake.frequent_families(db, load_settings(), wort)
    assert "atmospheric" in haeufig and "harsh" not in haeufig


def test_the_profile_page_hides_the_way_in_once_there_is_a_profile(client, db, buecher) -> None:
    tippen(client, "harsh")
    tippen(client, "brooding")
    client.post("/intake/profile", data={"facet": ["0"]})

    body = client.get("/profile").text

    assert "Erstaufnahme beginnen" not in body and "data-leseprofil" in body
    assert "hart · gezeichnete Figur" in body


def test_only_a_book_that_shares_nothing_is_there_for_other_reasons(client, db, buecher) -> None:
    bestaetigt(db, "liked", "Das Rosie-Projekt", _bild(
        "Roman", None, ["quirky", "funny", "likeable", "romantic"], "opposites_attract"))

    body = client.get("/intake/common").text

    assert "Rosie-Projekt</span>, aus ganz anderen Gründen" in body
    assert "Kruzifix Killer</span>, aus ganz anderen Gründen" not in body
