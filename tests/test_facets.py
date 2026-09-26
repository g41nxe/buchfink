"""Das Leseprofil: aus einer Datei, gespeichert, Facetten aus Büchern (#46, #50).

Die Rechnung selbst prüft ``test_taste_form.py`` (#79).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from conftest import needs_vocabulary
from ebook_watchlist.facets import (
    Counterweight,
    Facet,
    Liked,
    ProfileError,
    ReadingProfile,
    genre_matches,
    load_profile_file,
)
from ebook_watchlist.portrait import Portrait, Trait, load_vocabulary
from ebook_watchlist.store import Store

pytestmark = needs_vocabulary

NOW = datetime(2026, 9, 24, 1, 0)


def portrait(*terms: str, genre: str | None = None, subgenre: str | None = None) -> Portrait:
    return Portrait(
        known=True,
        fingerprint="versuch",
        genre=genre,
        subgenre=subgenre,
        traits=tuple(Trait(t, f"Satz zu {t}.", "wissen") for t in terms),
    )


LORD_OF_THE_RINGS = portrait("world_building", "leisurely", "sweeping", "atmospheric",
                            "bittersweet", "descriptive", "ensemble", genre="Fantasy",
                            subgenre="High Fantasy / Heroische Fantasy")
#: Das Profil aus dem Versuch vom 23.09.2026 (#44).
PROFILE = ReadingProfile(
    facets=(
        Facet(("harsh", "brooding"), ("Leichenblässe", "Kruzifix Killer")),
        Facet(("nerve_racking", "menacing"), ("Leichenblässe", "The Circle")),
        Facet(("funny", "likeable"), ("Das Rosie-Projekt",)),
        Facet(("big_world", "intricate"), ("Otherland",)),
    ),
    counterweights=(
        Counterweight(("leisurely",), books=("Herr der Ringe",)),
        Counterweight(("sad",), books=("Herr der Ringe",)),
    ),
    liked=tuple(
        Liked(f) for f in ("harsh", "brooding", "nerve_racking", "menacing", "funny",
                           "likeable", "big_world", "intricate")
    ),
)


@pytest.fixture(scope="module")
def vocabulary():
    return load_vocabulary()


# --- ein Profil aus einer Datei -------------------------------------------------


def _file(tmp_path: Path, text: str) -> Path:
    file = tmp_path / "profil.yaml"
    file.write_text(text, encoding="utf-8")
    return file


def test_a_profile_can_be_read_from_a_file(tmp_path: Path, vocabulary) -> None:
    file = _file(tmp_path, (
        "facetten:\n"
        "  - familien: [harsh, brooding]\n"
        "    buecher: [Leichenblässe, Kruzifix Killer]\n"
        "gegengewichte:\n"
        "  - familien: [big_world]\n"
        "    genre: High Fantasy\n"
        "    buecher: [Herr der Ringe]\n"
    ))

    profile = load_profile_file(file, vocabulary)

    assert profile.facets == (Facet(("harsh", "brooding"), ("Leichenblässe", "Kruzifix Killer")),)
    assert profile.counterweights == (
        Counterweight(("big_world",), genre="High Fantasy", books=("Herr der Ringe",)),
    )


def test_a_facet_needs_two_families(tmp_path: Path, vocabulary) -> None:
    """Eine einzelne Familie ist zu breit für eine Facette (#44)."""
    file = _file(tmp_path, "facetten:\n  - familien: [thought_provoking]\n")

    with pytest.raises(ProfileError, match="zwei"):
        load_profile_file(file, vocabulary)


def test_an_unknown_family_is_refused(tmp_path: Path, vocabulary) -> None:
    file = _file(tmp_path, "facetten:\n  - familien: [harsh, gibtsnicht]\n")

    with pytest.raises(ProfileError, match="gibtsnicht"):
        load_profile_file(file, vocabulary)


# --- gespeichert, append-only ------------------------------------------------------


def test_each_profile_is_a_new_version(store: Store) -> None:
    first = store.put_reading_profile("test", PROFILE, cause="aus Datei", now=NOW)
    second = store.put_reading_profile(
        "test", ReadingProfile(facets=PROFILE.facets[:1], counterweights=()),
        cause="eine Facette abgewählt", now=NOW.replace(hour=2),
    )

    assert (first, second) == (1, 2)
    read_book = store.reading_profile("test")
    assert read_book.version == 2
    assert read_book.facets == PROFILE.facets[:1]


def test_a_reader_without_a_profile_has_none(store: Store) -> None:
    assert store.reading_profile("niemand") is None


# --- der Aufruf von der Kommandozeile -------------------------------------------


def test_the_command_stores_a_new_version(data_dir: Path, tmp_path: Path) -> None:
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.facets import main

    file = _file(tmp_path, "facetten:\n  - familien: [harsh, brooding]\n")

    assert main([str(file)]) == 0
    assert main([str(file)]) == 0
    assert Store(paths.db_path()).reading_profile(load_settings().slug).version == 2


def test_the_command_refuses_a_broken_profile(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.facets import main

    file = _file(tmp_path, "facetten:\n  - familien: [harsh]\n")

    assert main([str(file)]) == 1
    assert "nicht übernommen" in capsys.readouterr().err
    assert Store(paths.db_path()).reading_profile(load_settings().slug) is None


def test_a_family_named_twice_counts_once(tmp_path: Path, vocabulary) -> None:
    file = _file(tmp_path, "facetten:\n  - familien: [harsh, harsh]\n")

    with pytest.raises(ProfileError, match="zwei"):
        load_profile_file(file, vocabulary)


def test_an_empty_counterweight_is_refused(tmp_path: Path, vocabulary) -> None:
    """Es träfe jedes Buch."""
    file = _file(tmp_path, "gegengewichte:\n  - genre: Fantasy\n")

    with pytest.raises(ProfileError, match="Gegengewicht"):
        load_profile_file(file, vocabulary)


def test_a_malformed_entry_is_a_profile_error(tmp_path: Path, vocabulary) -> None:
    file = _file(tmp_path, "facetten:\n  - harsh\n")

    with pytest.raises(ProfileError):
        load_profile_file(file, vocabulary)


# --- Facetten aus der Erstaufnahme (#50) -----------------------------------------

#: Welche geliebten Bücher im Versuch welche Familie trugen (Prototyp E).
CARRIERS = {
    "atmospheric": {"L", "O", "C"},
    "harsh": {"L", "K"},
    "brooding": {"L", "K"},
    "expert": {"L", "K"},
    "nerve_racking": {"L", "C"},
    "menacing": {"L", "C"},
    "thought_provoking": {"O", "C"},
    "quirky": {"R"},
    "funny": {"R"},
    "likeable": {"R"},
}


def test_facets_come_from_families_the_same_books_carry() -> None:
    from ebook_watchlist.facets import derive_facets

    facets = derive_facets(
        ["harsh", "brooding", "nerve_racking", "menacing", "funny", "likeable"], CARRIERS
    )

    # Rosies witzig und nahbar trägt nur ein Buch — keine Facette mehr; sie
    # zählen für sich (#64).
    assert [(f.families, f.books) for f in facets] == [
        (("harsh", "brooding"), ("K", "L")),
        (("nerve_racking", "menacing"), ("C", "L")),
    ]


def test_not_only_identical_book_sets_form_a_facet() -> None:
    """Schauplatz (L, O, C) und große Ideen (O, C): beide tragen O und C."""
    from ebook_watchlist.facets import derive_facets

    facets = derive_facets(["atmospheric", "thought_provoking"], CARRIERS)

    assert (("atmospheric", "thought_provoking"), ("C", "O")) in [
        (f.families, f.books) for f in facets
    ]


def test_a_single_family_is_no_facet() -> None:
    """Zählt für sich (#64), aber bündelt nichts."""
    from ebook_watchlist.facets import derive_facets

    facets = derive_facets(["harsh", "brooding", "thought_provoking"], CARRIERS)

    assert [f.families for f in facets] == [("harsh", "brooding")]


def test_one_book_alone_makes_no_facet() -> None:
    """Eine Kombination aus einem Buch sagt mehr über das Buch als über den
    Geschmack (24.09.2026)."""
    from ebook_watchlist.facets import derive_facets

    assert derive_facets(["quirky", "funny", "likeable"], CARRIERS) == []


def test_the_strength_is_a_scale() -> None:
    from ebook_watchlist.facets import strength

    assert [strength(n) for n in (1, 2, 3, 4, 7)] == [
        "schwach", "mittel", "stark", "sehr stark", "sehr stark"
    ]


def test_a_defining_book_lifts_the_strength_by_one_step_up_to_the_top() -> None:
    """#62: ein Buch, in dem die Facette prägt, soll nicht als „schwach“ dastehen."""
    from ebook_watchlist.facets import strength

    assert [strength(n, defining=True) for n in (1, 2, 3, 4, 7)] == [
        "mittel", "stark", "sehr stark", "sehr stark", "sehr stark"
    ]


# --- Review: Genre als ganzes Wort, Fassungsnummern ohne Wettlauf -----------------


@pytest.mark.parametrize(
    ("genre", "subgenre", "matches"),
    [("Kriminalroman", None, False), ("Liebesroman", None, False), ("Roman", None, True),
     ("Gegenwartsroman", "Roman über Familie", True)],
)
def test_a_genre_counterweight_matches_whole_words_only(genre, subgenre, matches) -> None:
    """„nur bei Roman" darf nicht jeden Kriminalroman treffen."""
    book = portrait("violent", "brooding", genre=genre, subgenre=subgenre)

    assert genre_matches(Counterweight(("harsh",), genre="Roman"), book) is matches


def test_high_fantasy_still_matches_its_long_subgenre() -> None:
    assert genre_matches(Counterweight(("big_world",), genre="High Fantasy"), LORD_OF_THE_RINGS)


def test_concurrent_saves_get_distinct_versions(store: Store) -> None:
    """Ein Doppelklick auf „Übernehmen" darf nicht an der Fassungsnummer scheitern."""
    import threading

    failure: list[BaseException] = []

    def save() -> None:
        try:
            for _ in range(5):
                store.put_reading_profile("test", PROFILE, cause="parallel", now=NOW)
        except BaseException as exc:  # noqa: BLE001
            failure.append(exc)

    threads = [threading.Thread(target=save) for _ in range(4)]
    for f in threads:
        f.start()
    for f in threads:
        f.join()

    assert failure == []
    assert store.reading_profile("test").version == 20


def test_a_family_of_one_book_does_not_grow_a_facet_of_that_book() -> None:
    """Erstaufnahme vom 24.09.: „Erkenntnis" trägt nur *Leichenblässe*, und
    daraus wurde eine Facette aus allem, was *Leichenblässe* trägt. Facetten
    aus einem einzigen Buch gibt es nur für ein Buch, das sonst in keiner
    steckt (Abdeckung)."""
    from ebook_watchlist.facets import derive_facets

    carriers = {**CARRIERS, "discovery": {"L"}}
    facets = derive_facets(
        ["harsh", "brooding", "nerve_racking", "menacing", "discovery"], carriers
    )

    assert [(f.families, f.books) for f in facets] == [
        (("harsh", "brooding"), ("K", "L")),
        (("nerve_racking", "menacing"), ("C", "L")),
    ]



# --- gemocht und verstärkt aus einer Datei und im Speicher ---------------------------


def test_liked_and_boosted_can_be_read_from_a_file(tmp_path: Path, vocabulary) -> None:
    file = _file(tmp_path, "gemocht: [harsh, brooding, pursuit]\nverstaerkt: [harsh]\n")

    profile = load_profile_file(file, vocabulary)

    assert profile.liked == (Liked("harsh", True), Liked("brooding"), Liked("pursuit"))


def test_no_more_than_three_are_boosted(tmp_path: Path, vocabulary) -> None:
    file = _file(tmp_path, (
        "gemocht: [harsh, brooding, funny, likeable]\n"
        "verstaerkt: [harsh, brooding, funny, likeable]\n"
    ))

    with pytest.raises(ProfileError, match="höchstens 3"):
        load_profile_file(file, vocabulary)


def test_only_what_is_liked_can_be_boosted(tmp_path: Path, vocabulary) -> None:
    file = _file(tmp_path, "gemocht: [harsh]\nverstaerkt: [funny]\n")

    with pytest.raises(ProfileError, match="nicht gemocht"):
        load_profile_file(file, vocabulary)


def test_the_store_keeps_what_is_liked(store: Store) -> None:
    store.put_reading_profile("test", PROFILE, cause="Test", now=NOW)

    assert store.reading_profile("test").liked == PROFILE.liked
