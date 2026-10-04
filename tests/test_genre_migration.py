"""Freies Genre → Code der Liste, einmalig (ADR 37, #89).

Die Fälle sind echte Schreibweisen aus dem Bestand vom 04.10.2026.
"""

from __future__ import annotations

import pytest

from ebook_watchlist.genre_migration import RULES, genre_code
from ebook_watchlist.genres import load_genres


@pytest.mark.parametrize(("genre", "subgenre", "code"), [
    ("Thriller", "Psychothriller", "FIC031080"),
    ("Psychologischer Thriller", "Domestic Thriller", "FIC031100"),
    ("Horror", "Psychologischer Horror", "FIC015050"),
    ("Kriminalroman", "Polizeikrimi", "FIC022020"),
    ("Kriminalroman", "Heimatkrimi mit Satire", "DE-REGIONALKRIMI"),
    ("Kriminalroman", "Schwarzhumoristischer Thriller", "FIC060000"),
    ("Kriminalroman", "Komödie, Satire", "FIC060000"),
    ("Science Fiction", "Satire, Gesellschaftskritik", "FIC028000"),
    ("Satire", "Politische Satire", "FIC016000"),
    ("Science-Fiction", "Space Opera, Abenteuer", "FIC028030"),
    ("Science-Fiction", "Abenteuer", "FIC028000"),
    ("Fantasy", "Abenteuer", "FIC009000"),
    ("Fantasy", "High Fantasy, Epos", "FIC009020"),
    ("Fantasy", "Urban Fantasy, Paranormal", "FIC009060"),
    ("Horror", "Paranormaler Horror, Slow-Burn Thriller", "FIC015040"),
    ("Dystopie", "Post-Apokalypse", "FIC028070"),
    ("Liebesroman", "Contemporary Romance", "FIC027020"),
    ("Literarischer Roman", "Familiensaga", "FIC019000"),
    ("Abenteuer", "Kinderabenteuer, Sportgeschichte", "FIC002000"),
    ("Historischer Krimi", "Wohlfühlkrimi", "FIC022070"),
    ("Kriminalroman", "Historischer Krimi", "FIC022000"),
    ("Drama", "Historisches Kriegsdrama", "FIC014000"),
])
def test_a_free_genre_becomes_a_code(genre: str, subgenre: str, code: str) -> None:
    assert genre_code(genre, subgenre) == code


def test_what_no_rule_knows_has_no_genre() -> None:
    assert genre_code("Sachbuch", "Kulturgeschichte, Essayistik") is None


def test_every_rule_names_a_listed_genre() -> None:
    listed = {genre.code for genre in load_genres()}
    assert {code for code, _ in RULES} <= listed
