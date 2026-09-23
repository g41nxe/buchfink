"""Das Urteil kommt aus dem Code (#46, ADR 33).

Die Steckbriefe tragen die Merkmale, die das Modell im Versuch vom 23.09.2026
vergeben hat; das Profil ist das aus demselben Versuch, ergänzt um die Facette,
die die Abdeckungsregel für *Otherland* erfragt hätte (#44). Die erwarteten
Werte sind die dort gerechneten.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ebook_watchlist.facets import (
    Counterweight,
    Facet,
    ProfileError,
    ReadingProfile,
    fit,
    load_profile_file,
    load_weights,
)
from ebook_watchlist.portrait import Portrait, Trait, load_vocabulary
from ebook_watchlist.store import Store

NOW = datetime(2026, 9, 24, 1, 0)


def steckbrief(*terms: str, genre: str | None = None, subgenre: str | None = None) -> Portrait:
    return Portrait(
        known=True,
        fingerprint="versuch",
        genre=genre,
        subgenre=subgenre,
        traits=tuple(Trait(t, f"Satz zu {t}.", "wissen") for t in terms),
    )


LEICHENBLAESSE = steckbrief("richly_detailed", "gritty", "brooding", "introspective",
                            "atmospheric", "menacing", "intensifying", genre="Kriminalroman")
LEOPARD = steckbrief("violent", "atmospheric", "disturbing", "brooding", "flawed", "intricate",
                     "intensifying", genre="Kriminalroman")
CUPIDO = steckbrief("suspenseful", "disturbing", "violent", "brooding", "flawed",
                    "issue_oriented", "richly_detailed", "gritty", genre="Kriminalroman")
OTHERLAND = steckbrief("world_building", "intricate", "leisurely", "ensemble", "atmospheric",
                       "thought_provoking", "descriptive", genre="Science-Fiction",
                       subgenre="Cyberpunk / Virtuelle-Realität-Epos")
DER_SCHWARM = steckbrief("intensifying", "intricate", "issue_oriented", "thought_provoking",
                         "dramatic", "ensemble", "richly_detailed", genre="Thriller")
HERR_DER_RINGE = steckbrief("world_building", "leisurely", "sweeping", "atmospheric",
                            "bittersweet", "descriptive", "ensemble", genre="Fantasy",
                            subgenre="High Fantasy / Heroische Fantasy")
#: Erfunden: von allem ein bisschen — der Fehler, an dem das alte Profil scheiterte.
VON_ALLEM_EIN_BISSCHEN = steckbrief("gritty", "intensifying", "funny", "world_building")

PROFIL = ReadingProfile(
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
)


@pytest.fixture(scope="module")
def wort():
    return load_vocabulary()


@pytest.fixture(scope="module")
def gewichte():
    return load_weights()


# --- die Zahlen aus dem Versuch ----------------------------------------------


@pytest.mark.parametrize(
    ("buch", "prozent", "sterne"),
    [
        (LEICHENBLAESSE, 96, 5),
        (LEOPARD, 84, 5),
        (CUPIDO, 82, 5),
        (OTHERLAND, 64, 4),
        (DER_SCHWARM, 19, 1),
        (VON_ALLEM_EIN_BISSCHEN, 34, 2),
        (HERR_DER_RINGE, 8, 1),
    ],
    ids=["Leichenblässe", "Leopard", "Cupido", "Otherland", "Der Schwarm",
         "von allem ein bisschen", "Herr der Ringe"],
)
def test_the_numbers_from_the_experiment(buch, prozent, sterne, wort, gewichte) -> None:
    ergebnis = fit(buch, PROFIL, wort, gewichte)

    assert round(ergebnis.share * 100) == prozent
    assert ergebnis.stars == sterne


def test_two_full_facets_outrank_one(wort, gewichte) -> None:
    """Mehrere Facetten zählen (Noisy-OR), und Leichenblässe trifft zwei ganz."""
    assert fit(LEICHENBLAESSE, PROFIL, wort, gewichte).share > \
        fit(LEOPARD, PROFIL, wort, gewichte).share


def test_a_bit_of_everything_stays_below_one_full_facet(wort, gewichte) -> None:
    ein_ganzer = fit(LEOPARD, PROFIL, wort, gewichte).share
    bisschen = fit(VON_ALLEM_EIN_BISSCHEN, PROFIL, wort, gewichte).share

    assert bisschen < 0.4 < ein_ganzer


# --- null, eins, und kein Urteil -------------------------------------------------


def test_nothing_touched_is_one_star(wort, gewichte) -> None:
    ergebnis = fit(steckbrief("lyrical", "romantic", "feel_good", "quirky"), PROFIL, wort, gewichte)

    assert (ergebnis.share, ergebnis.stars) == (0, 1)


def test_zero_stars_only_when_nothing_fits_and_something_is_against(wort, gewichte) -> None:
    ergebnis = fit(steckbrief("leisurely", "lyrical", "romantic", "feel_good"), PROFIL, wort,
                   gewichte)

    assert ergebnis.stars == 0


def test_a_book_the_model_does_not_know_gets_no_judgement(wort, gewichte) -> None:
    assert fit(Portrait(known=False, fingerprint="x"), PROFIL, wort, gewichte) is None


def test_without_facets_there_is_no_judgement(wort, gewichte) -> None:
    """Ohne Profil wird nicht geurteilt (ADR 33, Punkt 8)."""
    assert fit(LEOPARD, ReadingProfile(facets=(), counterweights=()), wort, gewichte) is None


# --- Gegengewichte als Bündel ---------------------------------------------------


def test_only_the_strongest_counterweight_counts(wort, gewichte) -> None:
    """Herr der Ringe trägt gemächlich und traurig — abgezogen wird einmal."""
    ergebnis = fit(HERR_DER_RINGE, PROFIL, wort, gewichte)

    assert round(ergebnis.share, 2) == 0.08
    assert ergebnis.against is not None


def test_a_counterweight_counts_only_with_all_its_parts(wort, gewichte) -> None:
    """„klassische Fantasy · Heldenreise": Otherland ist eine Heldenreise in der
    Science Fiction und bleibt unberührt, Herr der Ringe nicht (Nachtrag zu ADR 33).
    Die Heldenreise kommt erst mit den Erzählmustern (#49); die große Welt steht
    hier für sie."""
    profil = ReadingProfile(
        facets=PROFIL.facets,
        counterweights=(Counterweight(("big_world",), genre="High Fantasy"),),
    )

    assert fit(HERR_DER_RINGE, profil, wort, gewichte).against is not None
    assert fit(OTHERLAND, profil, wort, gewichte).against is None


# --- die Begründung ---------------------------------------------------------------


def test_the_reason_names_facet_books_and_the_sentence(wort, gewichte) -> None:
    text = "\n".join(r.text for r in fit(LEOPARD, PROFIL, wort, gewichte).reasons)

    assert "hart · gezeichnete Figur" in text
    assert "Leichenblässe" in text and "Kruzifix Killer" in text
    assert "Satz zu brooding." in text


def test_the_reason_names_what_is_against(wort, gewichte) -> None:
    text = "\n".join(r.text for r in fit(OTHERLAND, PROFIL, wort, gewichte).reasons)

    assert "gemächlich" in text


# --- die Gewichte kommen aus dem Bewertungsschema ------------------------------


def test_the_weights_are_read_from_the_rating_scheme(gewichte) -> None:
    assert (gewichte.full, gewichte.partial, gewichte.counterweight) == (0.8, 0.1, 0.2)


# --- ein Profil aus einer Datei -------------------------------------------------


def _datei(tmp_path: Path, text: str) -> Path:
    datei = tmp_path / "profil.yaml"
    datei.write_text(text, encoding="utf-8")
    return datei


def test_a_profile_can_be_read_from_a_file(tmp_path: Path, wort) -> None:
    datei = _datei(tmp_path, (
        "facetten:\n"
        "  - familien: [harsh, brooding]\n"
        "    buecher: [Leichenblässe, Kruzifix Killer]\n"
        "gegengewichte:\n"
        "  - familien: [big_world]\n"
        "    genre: High Fantasy\n"
        "    buecher: [Herr der Ringe]\n"
    ))

    profil = load_profile_file(datei, wort)

    assert profil.facets == (Facet(("harsh", "brooding"), ("Leichenblässe", "Kruzifix Killer")),)
    assert profil.counterweights == (
        Counterweight(("big_world",), genre="High Fantasy", books=("Herr der Ringe",)),
    )


def test_a_facet_needs_two_families(tmp_path: Path, wort) -> None:
    """Eine einzelne Familie ist zu breit für eine Facette (#44)."""
    datei = _datei(tmp_path, "facetten:\n  - familien: [thought_provoking]\n")

    with pytest.raises(ProfileError, match="zwei"):
        load_profile_file(datei, wort)


def test_an_unknown_family_is_refused(tmp_path: Path, wort) -> None:
    datei = _datei(tmp_path, "facetten:\n  - familien: [harsh, gibtsnicht]\n")

    with pytest.raises(ProfileError, match="gibtsnicht"):
        load_profile_file(datei, wort)


# --- gespeichert, append-only ------------------------------------------------------


def test_each_profile_is_a_new_version(store: Store) -> None:
    erste = store.put_reading_profile("test", PROFIL, cause="aus Datei", now=NOW)
    zweite = store.put_reading_profile(
        "test", ReadingProfile(facets=PROFIL.facets[:1], counterweights=()),
        cause="eine Facette abgewählt", now=NOW.replace(hour=2),
    )

    assert (erste, zweite) == (1, 2)
    gelesen = store.reading_profile("test")
    assert gelesen.version == 2
    assert gelesen.facets == PROFIL.facets[:1]


def test_a_reader_without_a_profile_has_none(store: Store) -> None:
    assert store.reading_profile("niemand") is None


# --- der Aufruf von der Kommandozeile -------------------------------------------


def test_the_command_stores_a_new_version(data_dir: Path, tmp_path: Path) -> None:
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.facets import main

    datei = _datei(tmp_path, "facetten:\n  - familien: [harsh, brooding]\n")

    assert main([str(datei)]) == 0
    assert main([str(datei)]) == 0
    assert Store(paths.db_path()).reading_profile(load_settings().slug).version == 2


def test_the_command_refuses_a_broken_profile(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.facets import main

    datei = _datei(tmp_path, "facetten:\n  - familien: [harsh]\n")

    assert main([str(datei)]) == 1
    assert "nicht übernommen" in capsys.readouterr().err
    assert Store(paths.db_path()).reading_profile(load_settings().slug) is None


def test_a_family_named_twice_counts_once(tmp_path: Path, wort) -> None:
    datei = _datei(tmp_path, "facetten:\n  - familien: [harsh, harsh]\n")

    with pytest.raises(ProfileError, match="zwei"):
        load_profile_file(datei, wort)


def test_an_empty_counterweight_is_refused(tmp_path: Path, wort) -> None:
    """Es träfe jedes Buch."""
    datei = _datei(tmp_path, "gegengewichte:\n  - genre: Fantasy\n")

    with pytest.raises(ProfileError, match="Gegengewicht"):
        load_profile_file(datei, wort)


def test_a_malformed_entry_is_a_profile_error(tmp_path: Path, wort) -> None:
    datei = _datei(tmp_path, "facetten:\n  - harsh\n")

    with pytest.raises(ProfileError):
        load_profile_file(datei, wort)


def test_a_family_the_vocabulary_forgot_does_not_break_the_reason(wort, gewichte) -> None:
    """Die Familien sind ein Arbeitsstand; ein altes Profil bleibt lesbar."""
    alt = ReadingProfile(facets=(Facet(("harsh", "gibtsnichtmehr")),), counterweights=())

    ergebnis = fit(LEOPARD, alt, wort, gewichte)

    assert "Zum Teil deine Facette: hart." in [r.text for r in ergebnis.reasons]


def test_a_partial_hit_names_only_what_the_book_carries(wort, gewichte) -> None:
    """Leopard ist verschachtelt, hat aber keine große Welt — die Zeile darf
    das nicht behaupten."""
    texte = [r.text for r in fit(LEOPARD, PROFIL, wort, gewichte).reasons if not r.detail]

    assert "Zum Teil wie Otherland: verschachtelt." in texte
    assert not any("große Welt" in t for t in texte)
