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

from conftest import needs_vocabulary, portrayer_via
from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.facets import Liked
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import intake
from ebook_watchlist.web.app import create_app

pytestmark = needs_vocabulary

NOW = datetime(2026, 9, 24, 3, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def _answer(title, author, original=None, genre="Science-Fiction") -> str:
    return json.dumps({
        "bekannt": True, "titel": title, "autor": author, "originaltitel": original,
        "genre": genre, "untergenre": None, "pitch": "Ein Buch.",
        "merkmale": [
            {"id": "world_building", "satz": "Eine Welt aus Welten.", "beleg": "wissen",
             "gewicht": "praegend"},
            {"id": "intricate", "satz": "Viele Stränge.", "beleg": "wissen",
             "gewicht": "deutlich"},
            {"id": "leisurely", "satz": "Nimmt sich Zeit.", "beleg": "wissen",
             "gewicht": "deutlich"},
            {"id": "ensemble", "satz": "Eine Gruppe.", "beleg": "wissen",
             "gewicht": "rand"},
        ],
        "erzaehlmuster": [{"id": "quest", "satz": "Sie ziehen los.", "beleg": "wissen"}],
    }, ensure_ascii=False)


ANSWERS = {
    "Otherland": _answer("Otherland", "Tad Williams"),
    "Cry Baby": _answer("Cry Baby", "Gillian Flynn", "Sharp Objects", "Thriller"),
    "Herr der Ringe": _answer("Der Herr der Ringe", "J. R. R. Tolkien", "The Lord of the Rings",
                               "Fantasy"),
    "Leichenblässe": _answer("Leichenblässe", "Simon Beckett", "Whispers of the Dead",
                              "Kriminalroman"),
    "Leopard": _answer("Leopard", "Jo Nesbø", "Panserhjerte", "Kriminalroman"),
    "Das Buch, das es nicht gibt": json.dumps({"bekannt": False}),
}


class Model:
    """Antwortet je nach Titel in der Anfrage und zählt mit."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def ask(self, text: str, max_tokens: int = 300) -> str:
        title = text.split("Titel: ")[1].split("\n")[0]
        self.asked.append(title)
        return ANSWERS[title]


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Model:
    m = Model()
    monkeypatch.setattr(intake, "build_portrayer", portrayer_via(m))
    return m


def name_book(client: TestClient, title: str, author: str = "", page: str = "liked") -> str:
    client.post("/intake/entry", data={"side": page, "title": title, "author": author})
    return wait_for(client)


def wait_for(client: TestClient) -> str:
    """Warten, bis kein Eintrag mehr sucht."""
    for _ in range(250):
        body = client.get("/intake").text
        if 'data-state="asking"' not in body or "Nochmal" in body:
            return body
        threading.Event().wait(0.02)
    raise AssertionError("die Erstaufnahme wurde nicht fertig")


def _entry(db: Store, title: str):
    return next(r for r in db.intake_entries(load_settings().slug) if r.typed_title == title)


# --- nennen und erkennen ---------------------------------------------------------


def test_every_entry_button_swaps_its_own_side(client, model) -> None:
    """Die Knöpfe eines Eintrags tauschen die Seite aus, auf der er steht — ein
    leeres Ziel (#65) ließe htmx den Knopf selbst ersetzen."""
    body = name_book(client, "Der Schwarm", "Frank Schätzing")

    assert 'hx-target="#side-liked"' in body
    assert 'hx-target=""' not in body


def test_a_typo_in_the_author_leads_to_a_confirmable_proposal(client, model) -> None:
    body = name_book(client, "Otherland", "Ted Williams")

    assert "Meinst du" in body and "Tad Williams" in body


def test_a_german_title_names_the_original(client, model) -> None:
    body = name_book(client, "Cry Baby")

    assert "Cry Baby" in body and "Sharp Objects" in body and "Gillian Flynn" in body


def test_it_works_without_any_history(client, db, model) -> None:
    """Kein Klappentext, kein Buch im Bestand: der Titel reicht."""
    before = len(db.books())

    name_book(client, "Otherland")

    assert len(db.books()) == before
    assert model.asked == ["Otherland"]


def test_a_book_the_model_does_not_know_says_so_and_offers_no_yes(client, db, model) -> None:
    body = name_book(client, "Das Buch, das es nicht gibt")

    assert "kennt das Modell nicht" in body and "trägt nichts" in body
    entry = _entry(db, "Das Buch, das es nicht gibt")
    assert f"/intake/entry/{entry.id}/confirm" not in body


def test_the_same_title_is_not_asked_twice(client, model) -> None:
    name_book(client, "Otherland")
    name_book(client, "Otherland", page="disliked")

    assert model.asked == ["Otherland"]


def test_without_a_model_the_entry_says_why_and_can_be_retried(client) -> None:
    body = name_book(client, "Otherland")

    assert "Kein Weg zum Modell" in body and "Nochmal" in body


# --- bestätigen --------------------------------------------------------------------


def test_yes_puts_the_book_on_the_shelf_with_its_portrait(client, db, model) -> None:
    name_book(client, "Otherland", "Ted Williams")
    entry = _entry(db, "Otherland")

    client.post(f"/intake/entry/{entry.id}/confirm")

    book_id = db.intake_entry(entry.id).book_id
    book = db.book(book_id)
    assert (book.title, book.author) == ("Otherland", "Tad Williams")
    liked = [r.book_id for r in db.relations(load_settings().slug, kind=RelationKind.LIKED)]
    assert book_id in liked
    # Der Steckbrief ist mitgezogen: die Buchseite fragt nicht noch einmal.
    assert "Eine Welt aus Welten." in client.get(f"/book/{book_id}").text
    assert model.asked == ["Otherland"]


def test_a_family_that_defines_its_only_book_is_not_called_weak(client, db, model) -> None:
    """#62: ein einziges geliebtes Buch, in dem „große Welt“ prägt, steht bei
    „mittel“; „gemächlich“, im selben Buch nur deutlich, bleibt bei „schwach“."""
    name_book(client, "Otherland")
    client.post(f"/intake/entry/{_entry(db, 'Otherland').id}/confirm")

    body = client.get("/intake/common").text

    big_world = body.split('data-card="big_world"', 1)[1].split("data-card=", 1)[0]
    leisurely = body.split('data-card="leisurely"', 1)[1].split("data-card=", 1)[0]
    assert "mittel" in big_world and "schwach" not in big_world
    assert "schwach" in leisurely


def test_a_disappointing_book_lands_on_the_other_shelf(client, db, model) -> None:
    name_book(client, "Herr der Ringe", page="disliked")
    entry = _entry(db, "Herr der Ringe")

    client.post(f"/intake/entry/{entry.id}/confirm")

    disliked = [r.book_id for r in db.relations(load_settings().slug, kind=RelationKind.DISLIKED)]
    assert db.intake_entry(entry.id).book_id in disliked


def test_the_books_stand_in_the_shelves_of_the_profile_page(client, db, model) -> None:
    name_book(client, "Cry Baby")
    client.post(f"/intake/entry/{_entry(db, 'Cry Baby').id}/confirm")

    assert "Cry Baby" in client.get("/profile").text


def test_another_book_asks_again_with_what_was_typed(client, db, model) -> None:
    name_book(client, "Das Buch, das es nicht gibt")
    entry = _entry(db, "Das Buch, das es nicht gibt")

    client.post(f"/intake/entry/{entry.id}/retype",
                data={"title": "Leopard", "author": "Jo Nesbø"})
    body = wait_for(client)

    assert "Panserhjerte" in body
    assert model.asked == ["Das Buch, das es nicht gibt", "Leopard"]


def test_removing_an_entry_frees_its_place(client, db, model) -> None:
    name_book(client, "Otherland")
    entry = _entry(db, "Otherland")

    body = client.post(f"/intake/entry/{entry.id}/remove").text

    assert "Otherland" not in body


# --- nichts geht verloren ------------------------------------------------------------


def test_an_entry_is_saved_before_the_model_answers(db, data_dir) -> None:
    entry = intake.add(db, load_settings(), "liked", "Otherland", None, now=NOW)

    assert db.intake_entry(entry).typed_title == "Otherland"


def test_an_open_entry_is_asked_again_when_the_page_opens(client, db, model) -> None:
    """Nach einem Abbruch — Server neu gestartet, Seite geschlossen — holt die
    Seite nach, was offen war."""
    intake.add(db, load_settings(), "liked", "Otherland", None, now=NOW)

    body = wait_for(client)

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


def test_three_confirmed_loved_books_open_the_way_on(client, db, model) -> None:
    for title in ("Otherland", "Cry Baby", "Leichenblässe"):
        name_book(client, title)
        client.post(f"/intake/entry/{_entry(db, title).id}/confirm")

    body = client.get("/intake").text

    assert "3 geliebte" in body and "stehen in deinen Regalen" in body


def test_the_profile_page_leads_into_the_intake(client) -> None:
    body = client.get("/profile").text

    assert 'href="/intake"' in body and "Erstaufnahme beginnen" in body


# --- Bildschirme 3 bis 5: das Gemeinsame, das Verlorene, dein Profil (#50) ------


def _portrait(genre, subgenre, terms, patterns="quest"):
    from ebook_watchlist.portrait import load_vocabulary, parse_answer

    return parse_answer(json.dumps({
        "bekannt": True, "titel": "x", "autor": "y", "genre": genre, "untergenre": subgenre,
        "pitch": "Ein Buch.",
        "merkmale": [{"id": m, "satz": f"Satz zu {m}.", "beleg": "wissen"} for m in terms],
        "erzaehlmuster": [{"id": patterns, "satz": "Muster.", "beleg": "wissen"}],
    }), load_vocabulary())


def confirmed(db: Store, page: str, title: str, portrait) -> int:
    """Ein Buch, wie es nach Bildschirm 1 und 2 dasteht: genannt, erkannt, bestätigt."""
    from dataclasses import replace

    entry = intake.add(db, load_settings(), page, title, None, now=NOW)
    db.put_portrait(intake.intake_subject(title, None), replace(portrait, title=title), now=NOW)
    return intake.confirm(db, load_settings(), entry, now=NOW)


@pytest.fixture
def books(db: Store) -> dict[str, int]:
    """Drei geliebte Bücher und ein enttäuschendes, nach dem Versuch vom 23.09.

    Leichenblässe und Kruzifix Killer teilen hart und gezeichnete Figur;
    Leichenblässe und Otherland den Schauplatz; Herr der Ringe trägt die große
    Welt wie Otherland, und gemächlich für sich allein.
    """
    return {
        "L": confirmed(db, "liked", "Leichenblässe", _portrait(
            "Kriminalroman", None, ["violent", "brooding", "menacing", "atmospheric"],
            "pursuit")),
        "K": confirmed(db, "liked", "Kruzifix Killer", _portrait(
            "Thriller", None, ["violent", "brooding", "flawed", "menacing"], "pursuit")),
        "O": confirmed(db, "liked", "Otherland", _portrait(
            "Science-Fiction", "Cyberpunk", ["world_building", "intricate", "atmospheric",
                                             "ensemble"])),
        "H": confirmed(db, "disliked", "Herr der Ringe", _portrait(
            "Fantasy", "High Fantasy / Heroische Fantasy",
            ["world_building", "leisurely", "bittersweet", "descriptive"])),
    }


HX = {"HX-Request": "true"}


def tap(client, family, page="loved", an=True, step=3) -> str:
    data = {"side": page, "family": family, "on": "1" if an else "", "step": step}
    return client.post("/intake/choice", data=data, headers=HX).text


def _questions(body: str) -> str:
    """Nur der Teil mit den Fragen, ohne das Profil daneben."""
    return body.split("data-draft", 1)[0]


def test_screen_3_lists_everything_the_loved_books_carry_as_cards(client, books) -> None:
    """Alle Merkmale und, für sich, alle Erzählmuster — nicht nach Büchern
    gruppiert (24.09.2026). Bücher stehen nur in den Belegen."""
    questions = _questions(client.get("/intake/common").text)

    terms, patterns = questions.split('data-section="Erzählmuster"', 1)
    for family in ("harsh", "brooding", "atmospheric", "intricate"):
        assert f'data-family="{family}"' in terms
    assert 'data-family="pursuit"' in patterns and 'data-family="quest"' in patterns
    assert "Weil du" not in questions
    assert "Kruzifix Killer" in questions and "Satz zu violent." in questions


def test_what_more_books_carry_ranks_higher(client, books) -> None:
    """Gerankt wird vorerst nach der Zahl der Bücher (#62 bringt die Ausprägung)."""
    questions = _questions(client.get("/intake/common").text)

    assert questions.index('data-family="harsh"') < questions.index('data-family="intricate"')


def test_a_tap_is_saved_and_the_profile_grows_below(client, db, books) -> None:
    tap(client, "harsh")
    body = tap(client, "brooding")

    assert 'data-facet="brooding,harsh"' in body
    assert {c.family_id for c in db.intake_choices(load_settings().slug)} == {"harsh", "brooding"}


def test_a_single_family_never_becomes_a_facet_on_its_own(client, books) -> None:
    """Erst ein zweites geliebtes Buch macht aus einem Merkmal eine Facette
    (#64) — allein zählt es nur als gemochtes Merkmal, nicht als Kombination."""
    body = tap(client, "atmospheric")

    draft = body.split("data-draft", 1)[1]
    assert "data-facet" not in draft


def test_boosting_needs_a_tap_first(client, books) -> None:
    response = client.post(
        "/intake/choice", data={"side": "boost", "family": "harsh", "on": "1", "step": 3})

    assert response.status_code == 400


def test_at_most_three_are_boosted(client, books) -> None:
    for family in ("harsh", "brooding", "menacing", "atmospheric"):
        tap(client, family)
    for family in ("harsh", "brooding", "menacing"):
        tap(client, family, page="boost")

    fourth = client.post(
        "/intake/choice", data={"side": "boost", "family": "atmospheric", "on": "1", "step": 3})

    assert fourth.status_code == 400


def test_unloving_a_family_also_unboosts(client, db, books) -> None:
    tap(client, "harsh")
    tap(client, "harsh", page="boost")

    tap(client, "harsh", an=False)

    choices = db.intake_choices(load_settings().slug)
    assert not any(c.side == "boost" and c.active for c in choices)


def test_a_boosted_family_shows_as_boosted(client, books) -> None:
    tap(client, "harsh")
    body = tap(client, "harsh", page="boost")

    card = body.split('data-card="harsh"', 1)[1].split("</li>", 1)[0]
    assert 'data-boost="harsh"' in card and "verstärkt" in card


def test_patterns_are_tappable_and_boostable_like_traits(client, books) -> None:
    """„Und vergiss die Erzählmuster nicht": ein Erzählmuster zählt genauso als
    eigener Grund und lässt sich genauso verstärken (24.09.2026)."""
    tap(client, "pursuit")
    body = tap(client, "pursuit", page="boost")

    card = body.split('data-card="pursuit"', 1)[1].split("</li>", 1)[0]
    assert 'data-boost="pursuit"' in card and "verstärkt" in card
    # Erzählmuster bilden nie eine Facette (#63).
    assert "data-facet" not in body.split("data-draft", 1)[1]


def test_a_lost_family_a_loved_book_also_carries_asks_how_far(client, books) -> None:
    body = tap(client, "big_world", page="lost", step=4)

    assert 'data-followup="big_world"' in body
    assert "nur bei High Fantasy" in body
    # Voreingestellt nur bei diesen Büchern: es zählt noch gegen nichts.
    assert "Nur an den Büchern selbst gestört" in body


def test_with_the_genre_it_becomes_a_bundle(client, books) -> None:
    tap(client, "big_world", page="lost", step=4)

    body = client.post("/intake/scope",
                       data={"family": "big_world", "scope": "genre"},
                       headers=HX).text

    draft = body.split("data-draft", 1)[1]
    assert "große Welt" in draft and "nur bei High Fantasy" in draft


def test_a_lost_family_no_loved_book_carries_counts_everywhere(client, books) -> None:
    body = tap(client, "leisurely", page="lost", step=4)

    assert "data-followup" not in body
    assert "gemächlich" in body.split("Zählt gegen ein Buch", 1)[1]


def test_adopting_saves_the_first_version_and_the_code_judges(client, db, books) -> None:
    tap(client, "harsh")
    tap(client, "brooding")
    tap(client, "harsh", page="boost")
    tap(client, "leisurely", page="lost", step=4)

    # Facetten wählt niemand aus — das Werkzeug hat sie aus dem Angetippten
    # gebildet. Auch die Gegengewichte werden nicht mehr ausgewählt: was auf
    # Schritt 4 angetippt ist, wird übernommen.
    response = client.post("/intake/profile", data={})

    profile = db.reading_profile(load_settings().slug)
    assert profile.version == 1
    assert profile.facets[0].families == ("brooding", "harsh")
    assert profile.counterweights[0].families == ("leisurely",)
    assert Liked("harsh", True) in profile.liked and Liked("brooding", False) in profile.liked
    assert "Dein Leseprofil" in response.text
    # Sofort geurteilt: Kruzifix Killer trifft die Facette ganz.
    assert "Übereinstimmung mit deinem Leseprofil" in client.get(f"/book/{books['K']}").text


def test_deselecting_everything_starts_over(client, db, books) -> None:
    """Nichts angetippt und kein Gegengewicht gewählt: das gibt es nur, bevor
    Bildschirm 3 überhaupt etwas angetippt wurde — geändert wird auf Schritt 3
    und 4, nie auf Schritt 5."""
    response = client.post("/intake/profile", data={})

    assert db.reading_profile(load_settings().slug) is None
    assert db.intake_entries(load_settings().slug) == []
    assert db.intake_choices(load_settings().slug) == []
    assert "Erstaufnahme" in response.text
    # Die bestätigten Bücher bleiben im Regal (ADR 5).
    liked = [r.book_id for r in db.relations(load_settings().slug, kind=RelationKind.LIKED)]
    assert books["L"] in liked


def test_frequent_families_go_last_only_with_a_neutral_stock(db, books) -> None:
    """Gemessen am neutralen Bestand, nie an den eigenen Büchern (#44)."""
    from ebook_watchlist.portrait import load_vocabulary

    vocabulary = load_vocabulary()
    assert intake.frequent_families(db, load_settings(), vocabulary) == set()

    for i in range(intake.NEUTRAL_MIN_BOOKS):
        terms = ["atmospheric", "fast_paced", "funny", "likeable"] if i % 2 else \
            ["atmospheric", "leisurely", "bittersweet", "lyrical"]
        db.put_portrait(f"item:x:{i}", _portrait("Roman", None, terms), now=NOW)

    frequent = intake.frequent_families(db, load_settings(), vocabulary)
    assert "atmospheric" in frequent and "harsh" not in frequent


def test_the_profile_page_hides_the_way_in_once_there_is_a_profile(client, db, books) -> None:
    tap(client, "harsh")
    tap(client, "brooding")
    client.post("/intake/profile", data={})

    body = client.get("/profile").text

    assert "Erstaufnahme beginnen" not in body and "data-reading-profile" in body
    # Jede Facette nennt ihre Merkmale mit dem Satz, was sie heißen — wie im Entwurf.
    from ebook_watchlist.portrait import load_vocabulary

    vocabulary = load_vocabulary()
    facet = body.split("Erkannte Kombinationen", 1)[1]
    assert "gezeichnete Figur" in facet and "hart" in facet
    assert vocabulary.family("brooding").description in facet
    assert vocabulary.family("harsh").description in facet


def test_a_confirmed_book_can_be_removed_again(client, db, books) -> None:
    """Auch ein bestätigtes Buch lässt sich wieder aus der Erstaufnahme nehmen;
    es trägt dann nichts mehr bei und steht nicht mehr als *Mag ich* im Regal."""
    entry = next(r for r in db.intake_entries(load_settings().slug)
                   if r.typed_title == "Kruzifix Killer")

    client.post(f"/intake/entry/{entry.id}/remove", headers=HX)

    assert "Kruzifix Killer" not in client.get("/intake").text
    liked = [r.book_id for r in db.relations(load_settings().slug, kind=RelationKind.LIKED)]
    assert books["K"] not in liked
    assert 'data-family="flawed"' not in client.get("/intake/common").text


# --- Review ---------------------------------------------------------------------


def test_genre_scope_needs_a_genre(client, db, books) -> None:
    """Ohne Genre wird aus „nur bei …" kein Gegengewicht, das überall gilt.

    "intricate" trägt nur Otherland (geliebt) und dieses genrelose Buch — im
    Unterschied zu "big_world", das auch "Herr der Ringe" mit Genre trägt."""
    confirmed(db, "disliked", "Ohne Genre", _portrait(None, None, ["intricate"]))
    tap(client, "intricate", page="lost", step=4)

    response = client.post("/intake/scope",
                          data={"family": "intricate", "scope": "genre"},
                          headers=HX)

    assert response.status_code == 400
    draft = client.get("/intake/lost").text.split("data-draft", 1)[1]
    assert "verschachtelt" not in draft.split("Zählt gegen ein Buch")[-1].split("Nur an")[0]


def test_adopting_takes_every_counterweight_of_the_draft(client, db, books) -> None:
    tap(client, "leisurely", page="lost", step=4)

    client.post("/intake/profile", data={})

    profile = db.reading_profile(load_settings().slug)
    assert [c.families for c in profile.counterweights] == [("leisurely",)]


def test_the_profile_screen_confirms_and_summarises_without_choices(client, books) -> None:
    tap(client, "harsh")
    tap(client, "leisurely", page="lost", step=4)

    body = client.get("/intake/profile").text

    assert 'type="checkbox"' not in body
    assert "Zählt gegen ein Buch" in body and "gemächlich" in body
    assert "hart" in body
    assert "Übernehmen" in body


def test_only_here_in_the_intake_keeps_the_family_out_of_the_form(client, db, books) -> None:
    """Dieselbe Antwort, dieselbe Wirkung wie beim Nachschärfen (#79): *nur hier*
    zählt gegen nichts — auch nicht, wenn die Geschmacksform aus dem Buch lernt."""
    import json

    tap(client, "harsh")
    tap(client, "big_world", page="lost", step=4)  # voreingestellt: nur hier

    client.post("/intake/profile", data={})

    (rel,) = [r for r in db.relations_of(load_settings().slug, books["H"])
              if r.kind == "disliked"]
    assert json.loads(rel.details)["reasons"] == {"here": ["big_world"]}


def test_frequent_families_are_not_recounted_for_every_tap(db, books, monkeypatch) -> None:
    """Gezählt wird neu, wenn ein Steckbrief oder eine Beziehung dazukommt —
    nicht bei jedem Tipp auf Bildschirm 3 und 4 (#58)."""
    from ebook_watchlist.portrait import load_vocabulary

    vocabulary = load_vocabulary()
    for i in range(intake.NEUTRAL_MIN_BOOKS):
        db.put_portrait(f"item:y:{i}", _portrait("Roman", None, ["atmospheric", "funny"]), now=NOW)
    intake.frequent_families(db, load_settings(), vocabulary)
    loaded = []
    real = db.latest_portraits
    monkeypatch.setattr(db, "latest_portraits", lambda fp: loaded.append(fp) or real(fp))

    intake.frequent_families(db, load_settings(), vocabulary)
    assert loaded == []

    db.put_portrait("item:y:neu", _portrait("Roman", None, ["harsh"]), now=NOW)
    intake.frequent_families(db, load_settings(), vocabulary)
    assert len(loaded) == 1
