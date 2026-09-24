"""Das Nachschärfen auf der Buchseite (#51, ADR 33 Punkt 7, umgebaut am 24.09.2026)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import needs_vocabulary, portrayer_via
from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.facets import Counterweight, Facet, Liked, ReadingProfile
from ebook_watchlist.portrait import load_vocabulary, parse_answer
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web.app import create_app

pytestmark = needs_vocabulary

NOW = datetime(2026, 9, 24, 4, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def slug() -> str:
    return load_settings().slug


def buch(db: Store, titel: str, merkmale: list[str], kind: str | None = "liked",
         untergenre: str | None = None) -> int:
    """Ein Buch mit Steckbrief und, wenn gewünscht, als Mag ich oder Doof."""
    b = db.find_or_create_book(isbn=None, title=titel, author="A", now=NOW)
    bild = parse_answer(json.dumps({
        "bekannt": True, "titel": titel, "autor": "A", "genre": "Roman",
        "untergenre": untergenre, "pitch": "x",
        "merkmale": [{"id": m, "satz": f"{m} bei {titel}.", "beleg": "wissen"} for m in merkmale],
        "erzaehlmuster": [{"id": "quest", "satz": "x", "beleg": "wissen"}],
    }), load_vocabulary())
    db.put_portrait(f"book:{b.id}", bild, now=NOW)
    if kind:
        db.put_relation(slug(), b.id, kind, active=True, now=NOW)
    return b.id


@pytest.fixture
def profil(db: Store) -> ReadingProfile:
    p = ReadingProfile(
        facets=(Facet(("harsh", "brooding"), ("Leichenblässe",)),),
        counterweights=(Counterweight(("leisurely",), books=("Herr der Ringe",)),),
        liked=(Liked("harsh"), Liked("brooding")),
    )
    db.put_reading_profile(slug(), p, cause="Erstaufnahme", now=NOW)
    return p


def seite(client: TestClient, book_id: int) -> str:
    return client.get(f"/book/{book_id}").text


# --- wann geschärft wird ------------------------------------------------------------


def test_without_a_profile_nothing_is_sharpened(client, db) -> None:
    b = buch(db, "Leopard", ["violent", "brooding", "flawed", "intricate"])

    assert "data-nachschaerfen" not in seite(client, b)


def test_dismissing_or_own_stars_do_not_sharpen(client, db, profil) -> None:
    ausgeschlossen = buch(db, "Ausgeschlossen", ["violent", "brooding"], kind="dismissed")
    nur_sterne = buch(db, "Nur Sterne", ["violent", "brooding"], kind=None)
    client.post(f"/book/{nur_sterne}/stars", data={"stars": "5"})

    assert "data-nachschaerfen" not in seite(client, ausgeschlossen)
    assert "data-nachschaerfen" not in seite(client, nur_sterne)


def test_mag_ich_draws_the_portrait_it_needs(client, db, profil, monkeypatch) -> None:
    from ebook_watchlist.web import book as view

    class Stub:
        def ask(self, text, max_tokens=300):
            return json.dumps({"bekannt": True, "titel": "Neu", "autor": "A", "pitch": "x",
                               "merkmale": [{"id": "funny", "satz": "x", "beleg": "wissen"}]})

    monkeypatch.setattr(view, "build_portrayer", portrayer_via(Stub()))
    b = db.find_or_create_book(isbn=None, title="Neu", author="A", now=NOW).id

    client.post(f"/book/{b}/relation", data={"kind": "liked", "active": "1"})

    from test_web_book import steckbrief_abwarten
    body = steckbrief_abwarten(client, f"/book/{b}")
    assert "data-nachschaerfen" in body


# --- gemocht ---------------------------------------------------------------------------


def test_a_liked_book_shows_its_own_families_as_cards(client, db, profil) -> None:
    b = buch(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    body = seite(client, b)

    karten = body.split("data-nachschaerfen", 1)[1]
    for familie in ("harsh", "brooding", "fast", "antihero"):
        assert f'data-karte="{familie}"' in karten
    # Schon gemocht: harsh und brooding stehen als angetippt (♥ ohne opacity-30).
    assert 'aria-pressed="true"' in karten.split('data-karte="harsh"', 1)[1].split("</li>", 1)[0]


def test_tapping_a_new_family_adds_it_and_rederives_facets(client, db, profil) -> None:
    b = buch(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    client.post(f"/book/{b}/sharpen/liked", data={"family": "fast", "on": "1"})

    neu = db.reading_profile(slug())
    assert neu.version == 2
    assert Liked("fast", False) in neu.liked
    # "fast" kommt nur bei diesem einen gemochten Buch vor — keine Facette.
    assert not any(f.families == ("fast",) for f in neu.facets)


def test_a_second_book_widens_a_shared_family_into_a_facet(client, db, profil) -> None:
    """Leichenblässe (aus dem Profil) und dieses Buch teilen jetzt „menacing"."""
    buch(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"], kind="liked")
    b = buch(db, "Kruzifix Killer", ["violent", "brooding", "menacing", "flawed"])

    client.post(f"/book/{b}/sharpen/liked", data={"family": "menacing", "on": "1"})

    neu = db.reading_profile(slug())
    assert Facet(("harsh", "brooding", "menacing"), ("Leichenblässe", "Kruzifix Killer")) \
        in neu.facets


def test_untapping_a_family_removes_it_and_its_boost(client, db, profil) -> None:
    b = buch(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"])
    client.post(f"/book/{b}/sharpen/boost", data={"family": "harsh", "on": "1"})

    client.post(f"/book/{b}/sharpen/liked", data={"family": "harsh", "on": ""})

    neu = db.reading_profile(slug())
    assert not any(g.family == "harsh" for g in neu.liked)
    assert not any(f.families == ("harsh", "brooding") for f in neu.facets)


def test_boosting_needs_a_tap_first(client, db, profil) -> None:
    b = buch(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"])

    antwort = client.post(f"/book/{b}/sharpen/boost", data={"family": "atmospheric", "on": "1"})

    assert antwort.status_code == 400
    assert db.reading_profile(slug()).version == 1


def test_at_most_three_are_boosted(client, db, profil) -> None:
    b = buch(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"])
    for familie in ("harsh", "brooding", "menacing", "atmospheric"):
        client.post(f"/book/{b}/sharpen/liked", data={"family": familie, "on": "1"})
    for familie in ("harsh", "brooding", "menacing"):
        client.post(f"/book/{b}/sharpen/boost", data={"family": familie, "on": "1"})

    vierte = client.post(f"/book/{b}/sharpen/boost", data={"family": "atmospheric", "on": "1"})

    assert vierte.status_code == 400


def test_a_family_this_book_does_not_carry_is_rejected(client, db, profil) -> None:
    b = buch(db, "Rosie", ["quirky", "funny", "likeable", "romantic"])

    antwort = client.post(f"/book/{b}/sharpen/liked", data={"family": "harsh", "on": "1"})

    assert antwort.status_code == 400


def test_the_code_judges_again_after_a_change(client, db, profil) -> None:
    b = buch(db, "Rosie", ["quirky", "funny", "likeable", "romantic"])
    vorher = seite(client, b).split('data-passung', 1)[1].split("</div>", 1)[0]

    client.post(f"/book/{b}/sharpen/liked", data={"family": "funny", "on": "1"})
    client.post(f"/book/{b}/sharpen/liked", data={"family": "likeable", "on": "1"})

    nachher = seite(client, b)
    assert nachher != vorher


# --- doof ------------------------------------------------------------------------------


def test_a_disliked_book_offers_counterweights(client, db, profil) -> None:
    buch(db, "Otherland", ["world_building", "intricate", "ensemble", "leisurely"])
    b = buch(db, "Herr der Ringe", ["world_building", "sweeping", "bittersweet", "descriptive"],
             kind="disliked", untergenre="High Fantasy / Heroische Fantasy")

    body = seite(client, b)

    assert "Was hat dich an diesem Buch verloren?" in body
    # Was auch ein gemochtes Buch trägt, wird nachgefragt.
    assert 'name="scope-big_world"' in body and "nur bei High Fantasy" in body
    assert 'name="umfang-sad"' not in body


def test_counterweights_take_their_scope(client, db, profil) -> None:
    buch(db, "Otherland", ["world_building", "intricate", "ensemble", "leisurely"])
    b = buch(db, "Herr der Ringe", ["world_building", "sweeping", "bittersweet", "descriptive"],
             kind="disliked", untergenre="High Fantasy / Heroische Fantasy")

    client.post(f"/book/{b}/sharpen/counterweight",
                data={"family": ["big_world", "sad"], "scope-big_world": "genre"})

    neu = db.reading_profile(slug())
    assert neu.version == 2
    assert Counterweight(("big_world",), "High Fantasy", ("Herr der Ringe",)) in neu.counterweights
    assert Counterweight(("sad",), None, ("Herr der Ringe",)) in neu.counterweights
    # Das Gemochte bleibt unberührt (#64).
    assert neu.liked == profil.liked


def test_only_here_changes_nothing(client, db, profil) -> None:
    buch(db, "Otherland", ["world_building", "intricate", "ensemble", "leisurely"])
    b = buch(db, "Herr der Ringe", ["world_building", "sweeping", "bittersweet", "descriptive"],
             kind="disliked")

    client.post(f"/book/{b}/sharpen/counterweight",
                data={"family": ["big_world"], "scope-big_world": "here"})

    assert db.reading_profile(slug()).version == 1


def test_a_disliked_book_on_a_facet_leaves_the_facet(client, db, profil) -> None:
    """Die Leserin hat das Verfeinern der Facette ausdrücklich verworfen (#44)."""
    b = buch(db, "Cupido", ["violent", "brooding", "sensuous", "fast_paced"], kind="disliked")
    assert "die bleibt, wie sie ist" in seite(client, b)

    client.post(f"/book/{b}/sharpen/counterweight", data={"family": ["sensuous"]})

    neu = db.reading_profile(slug())
    assert neu.facets == profil.facets
    assert neu.counterweights[-1].families == ("sensuous",)


def test_a_counterweight_the_profile_already_has_is_not_offered(client, db, profil) -> None:
    b = buch(db, "Zäh", ["leisurely", "bittersweet", "descriptive", "lyrical"], kind="disliked")

    body = seite(client, b)

    assert 'value="leisurely"' not in body.split("data-nachschaerfen", 1)[1]


def test_the_cause_names_the_book(client, db, profil) -> None:
    from ebook_watchlist.store import ReadingProfileRow

    b = buch(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])
    client.post(f"/book/{b}/sharpen/liked", data={"family": "fast", "on": "1"})

    with db.session() as session:
        anlass = session.query(ReadingProfileRow).order_by(ReadingProfileRow.id.desc()).first()
        assert anlass.cause == "Nachschärfen: Kruzifix Killer"


def test_liked_books_come_from_the_shelf_not_only_the_intake(db, profil, data_dir) -> None:
    from ebook_watchlist.web import sharpening

    a = buch(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"])
    buch(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    regal = sharpening.liked_shelf(db, load_settings(), load_vocabulary())

    assert {b.title for b in regal} == {"Leichenblässe", "Kruzifix Killer"}
    assert RelationKind.LIKED in {r.kind for r in db.relations_of(slug(), a)}


def test_the_profile_page_derives_the_strength_from_the_shelf(client, db, profil) -> None:
    """Gespeichert ist die Facette aus einem Buch; zwei gemochte tragen sie."""
    buch(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"])
    buch(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    body = client.get("/profile").text.split("data-leseprofil", 1)[1]

    assert "mittel" in body and "Kruzifix Killer" in body


# --- Review: keine leere Vertröstung ---------------------------------------------


def test_a_book_the_model_does_not_know_says_so_instead_of_waiting(client, db, profil) -> None:
    b = db.find_or_create_book(isbn=None, title="Unbekannt", author="A", now=NOW).id
    db.put_portrait(f"book:{b}", parse_answer('{"bekannt": false}', load_vocabulary()), now=NOW)
    db.put_relation(slug(), b, "liked", active=True, now=NOW)

    body = seite(client, b).split("data-nachschaerfen", 1)[1]

    assert "kennt dieses Buch nicht" in body and "Sobald der Steckbrief" not in body


def test_a_failed_portrait_says_why_sharpening_waits(client, db, profil) -> None:
    """Ohne Bewerter scheitert der Steckbrief; das Nachschärfen sagt das."""
    b = db.find_or_create_book(isbn=None, title="Ohne Modell", author="A", now=NOW).id

    client.post(f"/book/{b}/relation", data={"kind": "liked", "active": "1"})
    from test_web_book import steckbrief_abwarten
    body = steckbrief_abwarten(client, f"/book/{b}").split("data-nachschaerfen", 1)[1]

    assert "Kein Weg zum Modell" in body and "Sobald der Steckbrief" not in body


def test_after_a_change_the_page_jumps_back_to_the_section(client, db, profil) -> None:
    b = buch(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    antwort = TestClient(create_app(), follow_redirects=False).post(
        f"/book/{b}/sharpen/liked", data={"family": "fast", "on": "1"})

    anker = antwort.headers["location"].split("#", 1)[1]
    assert f'id="{anker}"' in seite(client, b)
