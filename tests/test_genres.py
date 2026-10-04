"""Die feste Genre-Liste (ADR 37, #87)."""

from __future__ import annotations

import pytest

from ebook_watchlist.genres import GenreError, load_genres, parse_genres

GENRES = load_genres()


def test_a_genre_has_a_code_a_name_and_its_bisac_heading() -> None:
    psycho = GENRES.get("FIC031080")

    assert (psycho.name, psycho.bisac, psycho.parent) == (
        "Psychothriller", "Thrillers / Psychological", "FIC031000")
    assert GENRES.name("FIC031080") == "Psychothriller"
    assert GENRES.name("FIC999999") is None


def test_a_genre_covers_the_subgenres_below_it() -> None:
    """„Liebesroman" nicht gemocht sperrt Romantasy; „Psychothriller" nur sich."""
    assert GENRES.covers("FIC027000", "FIC027030")
    assert GENRES.covers("FIC031080", "FIC031080")
    assert not GENRES.covers("FIC031080", "FIC031100")
    assert not GENRES.covers("FIC031080", "FIC031000")


def test_the_lineage_runs_from_subgenre_to_genre() -> None:
    assert GENRES.lineage("FIC031080") == ("FIC031080", "FIC031000")
    assert GENRES.lineage("FIC055000") == ("FIC055000",)
    assert GENRES.lineage("FIC999999") == ()


def test_an_extension_is_marked_and_named() -> None:
    regional = GENRES.get("DE-REGIONALKRIMI")

    assert regional.extension and regional.bisac is None
    assert regional.parent == "FIC022000"


def test_every_bisac_code_has_the_bisac_shape() -> None:
    """Neun Zeichen, drei Buchstaben, sechs Ziffern — oder eine markierte Erweiterung."""
    import re

    for genre in GENRES:
        assert genre.extension == genre.code.startswith("DE-")
        if not genre.extension:
            assert re.fullmatch(r"[A-Z]{3}\d{6}", genre.code), genre.code


@pytest.mark.parametrize("text", [
    "genres:\n  - {code: FIC1, name: A}\n  - {code: FIC1, name: B}\n",
    "genres:\n  - {code: FIC031000}\n",
    "genres:\n  - {code: DE-X, name: X}\n",
])
def test_a_broken_list_is_loud(text: str) -> None:
    """Doppelte Codes, fehlende Namen, unmarkierte Erweiterungen: laut, nicht still."""
    with pytest.raises(GenreError):
        parse_genres(text)


def test_the_source_tables_only_name_listed_genres() -> None:
    """Eine Quelle übersetzt nur, was auf der Liste steht — sonst fiele ein
    umbenannter Code erst im Lauf auf."""
    from ebook_watchlist.sources.beam import selectors as beam
    from ebook_watchlist.sources.overdrive import selectors as overdrive

    for table in (beam.GENRES, overdrive.GENRES):
        unknown = set(table) - {genre.code for genre in GENRES}
        assert not unknown, unknown
