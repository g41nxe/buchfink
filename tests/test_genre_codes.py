"""Steckbriefe und Gegengewichte tragen Genre-Codes (ADR 37, #89)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ebook_watchlist.facets import Counterweight, ReadingProfile, genre_matches
from ebook_watchlist.genres import genre_label
from ebook_watchlist.portrait import Portrait
from ebook_watchlist.store import Store

NOW = datetime(2026, 10, 4, 12, 0)


def portrait(genre: str | None, subgenre: str | None, code: str | None = None) -> Portrait:
    return Portrait(known=True, fingerprint="fp", genre=genre, subgenre=subgenre,
                    genre_code=code)


def test_a_code_reads_as_its_name_and_free_text_as_itself() -> None:
    assert genre_label("FIC009020") == "High Fantasy"
    assert genre_label("Cosy") == "Cosy"
    assert genre_label(None) is None


def test_a_counterweight_with_a_code_covers_the_subgenres_below() -> None:
    """„nur bei Fantasy" gilt auch für High Fantasy; „nur bei High Fantasy"
    nicht für jede Fantasy — und Schreibweisen spielen keine Rolle mehr."""
    fantasy = Counterweight(("big_world",), "FIC009000")
    epic = Counterweight(("duo",), "FIC009020")

    assert genre_matches(fantasy, portrait("Fantasy", "Epische Fantasy", "FIC009020"))
    assert genre_matches(epic, portrait("Fantasy", "High Fantasy, Epos", "FIC009020"))
    assert not genre_matches(epic, portrait("Fantasy", "Urban Fantasy", "FIC009060"))
    assert not genre_matches(epic, portrait("Fantasy", None, "FIC009000"))


def test_an_old_counterweight_without_a_code_still_compares_text() -> None:
    old = Counterweight(("duo",), "High Fantasy")

    assert genre_matches(old, portrait("Fantasy", "High Fantasy / Heroische Fantasy"))


def test_a_new_portrait_gets_its_code_from_the_rules_until_the_model_chooses(
    store: Store,
) -> None:
    """Zwischen #89 und #90 entsteht kein Steckbrief ohne Code."""
    store.put_portrait("isbn:9783000000501", portrait("Thriller", "Psycho-Thriller"), now=NOW)

    stored = store.portrait("isbn:9783000000501", "fp")
    assert stored.genre_code == "FIC031080"
    assert stored.genre == "Thriller" and stored.subgenre == "Psycho-Thriller"


def test_the_migration_codes_portraits_and_counterweights(tmp_path: Path) -> None:
    """Freitext bleibt, Code und Name kommen dazu; „Cosy" und „Cozy" aus dem
    alten Leseprofil werden ein Gegengewicht."""
    from sqlalchemy import create_engine

    from ebook_watchlist.migrations import _genres_become_codes

    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    body = {"facets": [], "liked": [], "counterweights": [
        {"families": ["duo"], "genre": "Epische Fantasy", "books": ["Herr der Ringe"]},
        {"families": ["funny"], "genre": "Cosy", "books": ["alt"]},
        {"families": ["funny"], "genre": "Cozy", "books": ["alt"]},
        {"families": ["explicit"], "genre": None, "books": ["alt"]},
    ]}
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE portrait (id INTEGER PRIMARY KEY, genre TEXT, subgenre TEXT)")
        connection.exec_driver_sql(
            "INSERT INTO portrait (genre, subgenre) VALUES ('Fantasy', 'High Fantasy, Epos'), "
            "('Sachbuch', 'Kulturgeschichte')")
        connection.exec_driver_sql(
            "CREATE TABLE reading_profile (id INTEGER PRIMARY KEY, body TEXT)")
        connection.exec_driver_sql("INSERT INTO reading_profile (body) VALUES (?)",
                                   (json.dumps(body),))
        _genres_become_codes(connection)
        portraits = connection.exec_driver_sql(
            "SELECT genre, genre_code, genre_name FROM portrait ORDER BY id").all()
        weights = json.loads(connection.exec_driver_sql(
            "SELECT body FROM reading_profile").scalar_one())["counterweights"]

    assert portraits == [("Fantasy", "FIC009020", "High Fantasy"), ("Sachbuch", None, None)]
    assert [(w["families"], w["genre"]) for w in weights] == [
        (["duo"], "FIC009020"), (["funny"], "FIC022070"), (["explicit"], None)]


def test_the_profile_page_names_the_genre_of_a_counterweight(data_dir: Path) -> None:
    from fastapi.testclient import TestClient

    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.web import create_app

    store = Store(paths.db_path())
    store.put_reading_profile(load_settings().slug, ReadingProfile(
        (), (Counterweight(("duo",), "FIC009020", ("Herr der Ringe",)),), ()),
        cause="test", now=NOW)

    body = TestClient(create_app()).get("/profile").text

    assert "nur bei High Fantasy" in body
    # Der Code steht höchstens als Wert in der Genre-Auswahl, nie als Text.
    assert "nur bei FIC009020" not in body
    assert ">FIC009020<" not in body


# --- aus dem Review (04.10.2026) ----------------------------------------------


def test_a_fresh_portrait_carries_its_code_before_it_is_stored() -> None:
    """Das Tor beurteilt den frischen Steckbrief, nicht den gespeicherten —
    ohne Code griff ein Gegengewicht „nur bei High Fantasy" dort nicht."""
    from ebook_watchlist.portrait import load_vocabulary, parse_answer

    text = json.dumps({"bekannt": True, "titel": "T", "autor": "A", "genre": "Fantasy",
                       "untergenre": "High Fantasy, Epos", "pitch": "Ein Buch.",
                       "merkmale": [], "erzaehlmuster": []})

    assert parse_answer(text, load_vocabulary()).genre_code == "FIC009020"


def test_a_counterweight_with_a_code_reads_a_portrait_without_one() -> None:
    """Ein Steckbrief, der nie gespeichert wurde, trägt keinen Code; das
    Gegengewicht leitet ihn dann selbst ab."""
    epic = Counterweight(("duo",), "FIC009020")

    assert genre_matches(epic, portrait("Fantasy", "High Fantasy, Epos"))


def test_merging_two_counterweights_keeps_the_books_of_both(tmp_path: Path) -> None:
    from sqlalchemy import create_engine

    from ebook_watchlist.migrations import _genres_become_codes

    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    body = {"counterweights": [{"families": ["funny"], "genre": "Cosy", "books": ["A"]},
                               {"families": ["funny"], "genre": "Cozy", "books": ["B"]}]}
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE reading_profile (id INTEGER PRIMARY KEY, body TEXT)")
        connection.exec_driver_sql("INSERT INTO reading_profile (body) VALUES (?)",
                                   (json.dumps(body),))
        _genres_become_codes(connection)
        weights = json.loads(connection.exec_driver_sql(
            "SELECT body FROM reading_profile").scalar_one())["counterweights"]

    assert weights == [{"families": ["funny"], "genre": "FIC022070", "books": ["A", "B"]}]


def test_two_genres_of_one_counterweight_read_as_names() -> None:
    from ebook_watchlist.web.profile_page import FacetLine, merge_genres

    lines = (FacetLine(name="witzig", genre="FIC022070", books=("A",)),
             FacetLine(name="witzig", genre="FIC009020", books=("B",)))

    (merged,) = merge_genres(lines)

    assert merged.genre == "Cosy Crime / High Fantasy"
