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


def book(db: Store, title: str, terms: list[str], kind: str | None = "liked",
         subgenre: str | None = None, defining: tuple[str, ...] = ()) -> int:
    """Ein Buch mit Steckbrief und, wenn gewünscht, als Mag ich oder Doof.
    ``praegend`` nennt die Merkmale, die das Buch prägen; alle anderen sind deutlich."""
    b = db.find_or_create_book(isbn=None, title=title, author="A", now=NOW)
    portrait = parse_answer(json.dumps({
        "bekannt": True, "titel": title, "autor": "A", "genre": "Roman",
        "untergenre": subgenre, "pitch": "x",
        "merkmale": [{"id": m, "satz": f"{m} bei {title}.", "beleg": "wissen",
                      "gewicht": "praegend" if m in defining else "deutlich"}
                     for m in terms],
        "erzaehlmuster": [{"id": "quest", "satz": "x", "beleg": "wissen"}],
    }), load_vocabulary())
    db.put_portrait(f"book:{b.id}", portrait, now=NOW)
    if kind:
        db.put_relation(slug(), b.id, kind, active=True, now=NOW)
    return b.id


@pytest.fixture
def profile(db: Store) -> ReadingProfile:
    p = ReadingProfile(
        facets=(Facet(("harsh", "brooding"), ("Leichenblässe",)),),
        counterweights=(Counterweight(("leisurely",), books=("Herr der Ringe",)),),
        liked=(Liked("harsh"), Liked("brooding")),
    )
    db.put_reading_profile(slug(), p, cause="Erstaufnahme", now=NOW)
    return p


def page(client: TestClient, book_id: int) -> str:
    return client.get(f"/book/{book_id}").text


# --- wann geschärft wird ------------------------------------------------------------


def test_without_a_profile_nothing_is_sharpened(client, db) -> None:
    b = book(db, "Leopard", ["violent", "brooding", "flawed", "intricate"])

    assert "data-sharpening" not in page(client, b)


def test_dismissing_or_own_stars_do_not_sharpen(client, db, profile) -> None:
    excluded = book(db, "Ausgeschlossen", ["violent", "brooding"], kind="dismissed")
    stars_only = book(db, "Nur Sterne", ["violent", "brooding"], kind=None)
    client.post(f"/book/{stars_only}/stars", data={"stars": "5"})

    assert "data-sharpening" not in page(client, excluded)
    assert "data-sharpening" not in page(client, stars_only)


def test_liked_draws_the_portrait_it_needs(client, db, profile, monkeypatch) -> None:
    from ebook_watchlist.web import book as view

    class Stub:
        def ask(self, text, max_tokens=300):
            return json.dumps({"bekannt": True, "titel": "Neu", "autor": "A", "pitch": "x",
                               "merkmale": [{"id": "funny", "satz": "x", "beleg": "wissen"}]})

    monkeypatch.setattr(view, "build_portrayer", portrayer_via(Stub()))
    b = db.find_or_create_book(isbn=None, title="Neu", author="A", now=NOW).id

    client.post(f"/book/{b}/relation", data={"kind": "liked", "active": "1"})

    from test_web_book import wait_for_portrait
    body = wait_for_portrait(client, f"/book/{b}")
    assert "data-sharpening" in body


# --- gemocht ---------------------------------------------------------------------------


def test_a_liked_book_shows_its_own_families_as_cards(client, db, profile) -> None:
    b = book(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    body = page(client, b)

    cards = body.split("data-sharpening", 1)[1]
    for family in ("harsh", "brooding", "fast", "antihero"):
        assert f'data-card="{family}"' in cards
    # Schon gemocht: harsh und brooding stehen als angetippt (♥ ohne opacity-30).
    assert 'aria-pressed="true"' in cards.split('data-card="harsh"', 1)[1].split("</li>", 1)[0]


def test_tapping_a_new_family_adds_it_and_rederives_facets(client, db, profile) -> None:
    b = book(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    client.post(f"/book/{b}/sharpen/liked", data={"family": "fast", "on": "1"})

    new = db.reading_profile(slug())
    assert new.version == 2
    assert Liked("fast", False) in new.liked
    # "fast" kommt nur bei diesem einen gemochten Buch vor — keine Facette.
    assert not any(f.families == ("fast",) for f in new.facets)


def test_a_second_book_widens_a_shared_family_into_a_facet(client, db, profile) -> None:
    """Leichenblässe (aus dem Profil) und dieses Buch teilen jetzt „menacing"."""
    book(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"], kind="liked")
    b = book(db, "Kruzifix Killer", ["violent", "brooding", "menacing", "flawed"])

    client.post(f"/book/{b}/sharpen/liked", data={"family": "menacing", "on": "1"})

    new = db.reading_profile(slug())
    assert Facet(("harsh", "brooding", "menacing"), ("Leichenblässe", "Kruzifix Killer")) \
        in new.facets


def test_untapping_a_family_removes_it_and_its_boost(client, db, profile) -> None:
    b = book(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"])
    client.post(f"/book/{b}/sharpen/boost", data={"family": "harsh", "on": "1"})

    client.post(f"/book/{b}/sharpen/liked", data={"family": "harsh", "on": ""})

    new = db.reading_profile(slug())
    assert not any(g.family == "harsh" for g in new.liked)
    assert not any(f.families == ("harsh", "brooding") for f in new.facets)


def test_boosting_needs_a_tap_first(client, db, profile) -> None:
    b = book(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"])

    response = client.post(f"/book/{b}/sharpen/boost", data={"family": "atmospheric", "on": "1"})

    assert response.status_code == 400
    assert db.reading_profile(slug()).version == 1


def test_at_most_three_are_boosted(client, db, profile) -> None:
    b = book(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"])
    for family in ("harsh", "brooding", "menacing", "atmospheric"):
        client.post(f"/book/{b}/sharpen/liked", data={"family": family, "on": "1"})
    for family in ("harsh", "brooding", "menacing"):
        client.post(f"/book/{b}/sharpen/boost", data={"family": family, "on": "1"})

    fourth = client.post(f"/book/{b}/sharpen/boost", data={"family": "atmospheric", "on": "1"})

    assert fourth.status_code == 400


def test_a_family_this_book_does_not_carry_is_rejected(client, db, profile) -> None:
    b = book(db, "Rosie", ["quirky", "funny", "likeable", "romantic"])

    response = client.post(f"/book/{b}/sharpen/liked", data={"family": "harsh", "on": "1"})

    assert response.status_code == 400


def test_the_code_judges_again_after_a_change(client, db, profile) -> None:
    b = book(db, "Rosie", ["quirky", "funny", "likeable", "romantic"])
    before = page(client, b).split('data-fit', 1)[1].split("</div>", 1)[0]

    client.post(f"/book/{b}/sharpen/liked", data={"family": "funny", "on": "1"})
    client.post(f"/book/{b}/sharpen/liked", data={"family": "likeable", "on": "1"})

    after = page(client, b)
    assert after != before


# --- doof ------------------------------------------------------------------------------


def test_a_disliked_book_offers_counterweights(client, db, profile) -> None:
    book(db, "Otherland", ["world_building", "intricate", "ensemble", "leisurely"])
    b = book(db, "Herr der Ringe", ["world_building", "sweeping", "bittersweet", "descriptive"],
             kind="disliked", subgenre="High Fantasy / Heroische Fantasy")

    body = page(client, b)

    assert "Was hat dich an diesem Buch verloren?" in body
    # Was auch ein gemochtes Buch trägt, wird nachgefragt.
    assert 'name="scope-big_world"' in body and "nur bei High Fantasy" in body
    assert 'name="umfang-sad"' not in body


def test_counterweights_take_their_scope(client, db, profile) -> None:
    book(db, "Otherland", ["world_building", "intricate", "ensemble", "leisurely"])
    b = book(db, "Herr der Ringe", ["world_building", "sweeping", "bittersweet", "descriptive"],
             kind="disliked", subgenre="High Fantasy / Heroische Fantasy")

    client.post(f"/book/{b}/sharpen/counterweight",
                data={"family": ["big_world", "sad"], "scope-big_world": "genre"})

    new = db.reading_profile(slug())
    assert new.version == 2
    assert Counterweight(("big_world",), "High Fantasy", ("Herr der Ringe",)) in new.counterweights
    assert Counterweight(("sad",), None, ("Herr der Ringe",)) in new.counterweights
    # Das Gemochte bleibt unberührt (#64).
    assert new.liked == profile.liked


def test_only_here_changes_nothing(client, db, profile) -> None:
    book(db, "Otherland", ["world_building", "intricate", "ensemble", "leisurely"])
    b = book(db, "Herr der Ringe", ["world_building", "sweeping", "bittersweet", "descriptive"],
             kind="disliked")

    client.post(f"/book/{b}/sharpen/counterweight",
                data={"family": ["big_world"], "scope-big_world": "here"})

    assert db.reading_profile(slug()).version == 1


def test_a_disliked_book_on_a_facet_leaves_the_facet(client, db, profile) -> None:
    """Die Leserin hat das Verfeinern der Facette ausdrücklich verworfen (#44)."""
    b = book(db, "Cupido", ["violent", "brooding", "sensuous", "fast_paced"], kind="disliked")
    assert "die bleibt, wie sie ist" in page(client, b)

    client.post(f"/book/{b}/sharpen/counterweight", data={"family": ["sensuous"]})

    new = db.reading_profile(slug())
    assert new.facets == profile.facets
    assert new.counterweights[-1].families == ("sensuous",)


def test_a_counterweight_the_profile_already_has_is_not_offered(client, db, profile) -> None:
    b = book(db, "Zäh", ["leisurely", "bittersweet", "descriptive", "lyrical"], kind="disliked")

    body = page(client, b)

    counterweights = body.split("data-sharpening", 1)[1].split("data-reasons", 1)[0]
    assert 'value="leisurely"' not in counterweights


def test_the_cause_names_the_book(client, db, profile) -> None:
    from ebook_watchlist.store import ReadingProfileRow

    b = book(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])
    client.post(f"/book/{b}/sharpen/liked", data={"family": "fast", "on": "1"})

    with db.session() as session:
        cause = session.query(ReadingProfileRow).order_by(ReadingProfileRow.id.desc()).first()
        assert cause.cause == "Nachschärfen: Kruzifix Killer"


def test_liked_books_come_from_the_shelf_not_only_the_intake(db, profile, data_dir) -> None:
    from ebook_watchlist.web import sharpening

    a = book(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"])
    book(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    shelf = sharpening.liked_shelf(db, load_settings(), load_vocabulary())

    assert {b.title for b in shelf} == {"Leichenblässe", "Kruzifix Killer"}
    assert RelationKind.LIKED in {r.kind for r in db.relations_of(slug(), a)}


def test_the_profile_page_derives_the_strength_from_the_shelf(client, db, profile) -> None:
    """Gespeichert ist die Facette aus einem Buch; zwei gemochte tragen sie."""
    book(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"])
    book(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    body = client.get("/profile").text.split("data-reading-profile", 1)[1]

    assert "mittel" in body and "Kruzifix Killer" in body


def test_a_defining_book_lifts_the_strength_on_the_profile_page(client, db, profile) -> None:
    """#62: dieselben zwei Bücher, aber in einem prägen beide Merkmale der Facette —
    die Facette steht dann bei „stark“ statt bei „mittel“."""
    book(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"],
         defining=("violent", "brooding"))
    book(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    body = client.get("/profile").text.split("data-reading-profile", 1)[1]

    assert "stark" in body.split("Erkannte Kombinationen", 1)[1].split("Zählt gegen", 1)[0]
    assert "mittel" not in body.split("Erkannte Kombinationen", 1)[1].split("Zählt gegen", 1)[0]


def test_a_facet_is_not_lifted_when_only_one_of_its_terms_is_defining(client, db, profile) -> None:
    """Prägend muss die ganze Kombination sein, nicht eines ihrer Merkmale."""
    book(db, "Leichenblässe", ["violent", "brooding", "menacing", "atmospheric"],
         defining=("violent",))
    book(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    body = client.get("/profile").text.split("data-reading-profile", 1)[1]

    assert "mittel" in body.split("Erkannte Kombinationen", 1)[1].split("Zählt gegen", 1)[0]


# --- Review: keine leere Vertröstung ---------------------------------------------


def test_a_book_the_model_does_not_know_says_so_instead_of_waiting(client, db, profile) -> None:
    b = db.find_or_create_book(isbn=None, title="Unbekannt", author="A", now=NOW).id
    db.put_portrait(f"book:{b}", parse_answer('{"bekannt": false}', load_vocabulary()), now=NOW)
    db.put_relation(slug(), b, "liked", active=True, now=NOW)

    body = page(client, b).split("data-sharpening", 1)[1]

    assert "kennt dieses Buch nicht" in body and "Sobald der Steckbrief" not in body


def test_a_failed_portrait_says_why_sharpening_waits(client, db, profile) -> None:
    """Ohne Bewerter scheitert der Steckbrief; das Nachschärfen sagt das."""
    b = db.find_or_create_book(isbn=None, title="Ohne Modell", author="A", now=NOW).id

    client.post(f"/book/{b}/relation", data={"kind": "liked", "active": "1"})
    from test_web_book import wait_for_portrait
    body = wait_for_portrait(client, f"/book/{b}").split("data-sharpening", 1)[1]

    assert "Kein Weg zum Modell" in body and "Sobald der Steckbrief" not in body


def test_after_a_change_the_page_jumps_back_to_the_section(client, db, profile) -> None:
    b = book(db, "Kruzifix Killer", ["violent", "brooding", "fast_paced", "flawed"])

    response = TestClient(create_app(), follow_redirects=False).post(
        f"/book/{b}/sharpen/liked", data={"family": "fast", "on": "1"})

    anchor = response.headers["location"].split("#", 1)[1]
    assert f'id="{anchor}"' in page(client, b)


# --- deine Sicht: was nicht stimmt, was fehlt (#79) ----------------------------------------


def _reasons(db: Store, book_id: int, kind: str) -> dict:
    (rel,) = [r for r in db.relations_of(slug(), book_id) if r.kind == kind]
    return json.loads(rel.details or "{}").get("reasons", {})


def test_a_rated_book_asks_whether_the_portrait_fits_her(client, db, profile) -> None:
    b = book(db, "Der Schwarm", ["intensifying", "world_building"], kind="disliked")

    body = page(client, b)

    assert "data-reasons" in body
    assert 'name="drop" value="nerve_racking"' in body
    # Was der Steckbrief nicht nennt, lässt sich ergänzen; was er nennt, nicht noch einmal.
    assert '<option value="leisurely">' in body
    assert '<option value="nerve_racking">' not in body


def test_her_reasons_are_kept_at_her_rating(client, db, profile) -> None:
    b = book(db, "Der Schwarm", ["intensifying", "world_building"], kind="disliked")

    client.post(f"/book/{b}/sharpen/reasons",
                data={"drop": ["nerve_racking"], "add": ["leisurely", "ensemble"]})

    assert _reasons(db, b, "disliked") == {
        "drop": ["nerve_racking"], "add": ["leisurely", "ensemble"],
    }
    # Das Profil bleibt, wie es ist: die Gründe gehören zum Buch.
    assert db.reading_profile(slug()).version == 1
    body = " ".join(page(client, b).split())
    assert 'name="add" value="leisurely" class="sr-only" checked' in body
    assert 'name="drop" value="nerve_racking" class="sr-only" checked' in body


def test_a_reason_must_belong_to_the_book_or_the_vocabulary(client, db, profile) -> None:
    b = book(db, "Der Schwarm", ["intensifying", "world_building"], kind="disliked")

    stranger = client.post(f"/book/{b}/sharpen/reasons", data={"drop": ["leisurely"]})
    invented = client.post(f"/book/{b}/sharpen/reasons", data={"add": ["gibtsnicht"]})

    assert stranger.status_code == 400 and invented.status_code == 400
    assert _reasons(db, b, "disliked") == {}


def test_only_here_keeps_the_family_out_of_the_form(client, db, profile) -> None:
    """„Nur bei diesem Buch" heißt: zählt nicht gegen andere — auch nicht beim Lernen."""
    book(db, "Otherland", ["world_building", "intricate", "ensemble", "leisurely"])
    b = book(db, "Herr der Ringe", ["world_building", "sweeping", "bittersweet", "descriptive"],
             kind="disliked")

    client.post(f"/book/{b}/sharpen/counterweight",
                data={"family": ["big_world"], "scope-big_world": "here"})

    assert _reasons(db, b, "disliked") == {"here": ["big_world"]}


def test_each_family_can_be_added_once() -> None:
    """Eine Familie mit Merkmalen aus zwei Dimensionen steht nur einmal zur Wahl."""
    from ebook_watchlist.web.sharpening import family_choices

    ids = [f for _, families in family_choices(load_vocabulary()) for f, _ in families]

    assert len(ids) == len(set(ids))


def test_what_counts_only_here_shows_as_not_counted_and_can_be_taken_back(
    client, db, profile
) -> None:
    book(db, "Otherland", ["world_building", "intricate", "ensemble", "leisurely"])
    b = book(db, "Herr der Ringe", ["world_building", "sweeping", "bittersweet", "descriptive"],
             kind="disliked")
    client.post(f"/book/{b}/sharpen/counterweight",
                data={"family": ["big_world"], "scope-big_world": "here"})

    body = " ".join(page(client, b).split())
    assert 'name="drop" value="big_world" class="sr-only" checked' in body

    client.post(f"/book/{b}/sharpen/reasons", data={})

    assert _reasons(db, b, "disliked") == {}


def test_a_counterweight_counts_the_family_again(client, db, profile) -> None:
    book(db, "Otherland", ["world_building", "intricate", "ensemble", "leisurely"])
    b = book(db, "Herr der Ringe", ["world_building", "sweeping", "bittersweet", "descriptive"],
             kind="disliked")
    client.post(f"/book/{b}/sharpen/counterweight",
                data={"family": ["big_world"], "scope-big_world": "here"})

    client.post(f"/book/{b}/sharpen/counterweight",
                data={"family": ["big_world"], "scope-big_world": "general"})

    assert _reasons(db, b, "disliked") == {}


def test_a_stale_added_family_does_not_block_saving(client, db, profile) -> None:
    """Steht eine ergänzte Familie inzwischen im Steckbrief, fällt sie still weg."""
    b = book(db, "Der Schwarm", ["intensifying", "world_building"], kind="disliked")
    client.post(f"/book/{b}/sharpen/reasons", data={"add": ["leisurely"]})
    book(db, "Der Schwarm", ["intensifying", "world_building", "leisurely"], kind=None)

    response = client.post(f"/book/{b}/sharpen/reasons", data={"add": ["leisurely"]})

    assert response.status_code == 200
    assert _reasons(db, b, "disliked") == {}


def test_a_broken_bag_does_not_break_sharpening(db, profile) -> None:
    b = book(db, "Der Schwarm", ["intensifying", "world_building"], kind="disliked")
    from sqlalchemy import update

    from ebook_watchlist.store import BookRelationRow

    with db.session() as s:
        s.execute(update(BookRelationRow).where(BookRelationRow.book_id == b)
                  .values(details="[]"))
        s.commit()

    from ebook_watchlist.web import sharpening

    assert sharpening.build(db, load_settings(), b).dropped == frozenset()


# --- abwählen, was schon dagegen zählt (#51) ------------------------------------------------


def test_a_disliked_book_shows_what_already_counts_against_and_takes_it_back(
    client, db, profile
) -> None:
    b = book(db, "Herr der Ringe", ["world_building", "leisurely", "bittersweet", "descriptive"],
             kind="disliked")

    body = page(client, b)
    assert 'data-counted="leisurely"' in body

    client.post(f"/book/{b}/sharpen/counterweight/remove", data={"family": "leisurely"})

    new = db.reading_profile(slug())
    assert new.version == 2 and new.counterweights == ()


def test_taking_a_counterweight_back_names_the_book(client, db, profile) -> None:
    from ebook_watchlist.store import ReadingProfileRow

    b = book(db, "Herr der Ringe", ["world_building", "leisurely", "bittersweet", "descriptive"],
             kind="disliked")

    client.post(f"/book/{b}/sharpen/counterweight/remove", data={"family": "leisurely"})

    with db.session() as session:
        cause = session.query(ReadingProfileRow).order_by(ReadingProfileRow.id.desc()).first()
        assert cause.cause == "Nachschärfen: Herr der Ringe"


def test_a_counterweight_of_another_book_stays(client, db, profile) -> None:
    """Das Gegengewicht verliert nur dieses Buch; trägt es ein anderes, bleibt es."""
    from ebook_watchlist.facets import Counterweight, ReadingProfile

    db.put_reading_profile(slug(), ReadingProfile(
        profile.facets,
        (Counterweight(("leisurely",), books=("Herr der Ringe", "Der Schwarm")),),
        profile.liked,
    ), cause="Test", now=NOW)
    b = book(db, "Herr der Ringe", ["world_building", "leisurely", "bittersweet", "descriptive"],
             kind="disliked")

    client.post(f"/book/{b}/sharpen/counterweight/remove", data={"family": "leisurely"})

    assert db.reading_profile(slug()).counterweights == (
        Counterweight(("leisurely",), books=("Der Schwarm",)),)


def test_the_profile_page_leads_to_where_things_are_changed(client, db, profile) -> None:
    """Die Profilseite bleibt zum Lesen; jede Marke führt zum Buch, an dem sie
    sich ändern lässt (#51)."""
    liked = book(db, "Leichenblässe", ["violent", "brooding", "menacing"])
    disliked = book(db, "Herr der Ringe", ["world_building", "leisurely", "bittersweet",
                                       "descriptive"], kind="disliked")

    body = client.get("/profile").text

    assert f'href="/book/{liked}#sharpening"' in body
    assert f'href="/book/{disliked}#sharpening"' in body



def test_taking_back_a_genre_counterweight_leaves_the_general_one(client, db, profile) -> None:
    """„X (nur bei Fantasy)" und „X" sind zwei Gegengewichte (Review)."""
    from ebook_watchlist.facets import Counterweight, ReadingProfile

    b = book(db, "Herr der Ringe", ["world_building", "leisurely", "bittersweet",
                                    "descriptive"], kind="disliked")
    db.put_reading_profile(slug(), ReadingProfile(profile.facets, (
        Counterweight(("big_world",), None, ("Herr der Ringe",)),
        Counterweight(("big_world",), "Fantasy", ("Herr der Ringe",)),
    ), profile.liked), cause="Test", now=NOW)

    client.post(f"/book/{b}/sharpen/counterweight/remove",
                data={"family": "big_world|Fantasy"})

    assert db.reading_profile(slug()).counterweights == (
        Counterweight(("big_world",), None, ("Herr der Ringe",)),)
