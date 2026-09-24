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

from conftest import needs_vocabulary
from ebook_watchlist.facets import (
    Counterweight,
    Facet,
    Liked,
    ProfileError,
    ReadingProfile,
    fit,
    load_profile_file,
    load_weights,
)
from ebook_watchlist.portrait import Portrait, Trait, load_vocabulary
from ebook_watchlist.store import Store

pytestmark = needs_vocabulary

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
    # Gemocht ist, was die Leserin im Versuch angetippt hat: die Merkmale
    # der Facetten. Jedes zählt auch für sich (#64).
    liked=tuple(
        Liked(f) for f in ("harsh", "brooding", "nerve_racking", "menacing", "funny",
                           "likeable", "big_world", "intricate")
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
        # Seit #64 zählen gemochte Merkmale einzeln (0,1) statt als Teiltreffer
        # einer Facette; jedes Urteil bleibt bei seinen Sternen.
        (LEICHENBLAESSE, 97, 5),
        (LEOPARD, 87, 5),
        (CUPIDO, 85, 5),
        (OTHERLAND, 67, 4),
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


def test_without_a_profile_there_is_no_judgement(wort, gewichte) -> None:
    """Ohne Profil wird nicht geurteilt (ADR 33, Punkt 8)."""
    assert fit(LEOPARD, ReadingProfile(facets=(), counterweights=()), wort, gewichte) is None


# --- gemochte Merkmale, verstärkt, und Erzählmuster (#63, #64) ---------------------


def test_a_liked_term_counts_on_its_own(wort, gewichte) -> None:
    """Ohne jede Facette: ein gemochtes Merkmal ist ein schwacher eigener Grund."""
    profil = ReadingProfile(facets=(), counterweights=(), liked=(Liked("harsh"),))

    assert round(fit(LEOPARD, profil, wort, gewichte).share, 2) == 0.1


def test_a_boosted_term_counts_more(wort, gewichte) -> None:
    profil = ReadingProfile(facets=(), counterweights=(), liked=(Liked("harsh", True),))

    assert round(fit(LEOPARD, profil, wort, gewichte).share, 2) == 0.2


def test_a_liked_story_pattern_is_a_reason_of_its_own(wort, gewichte) -> None:
    """0,3, verstärkt 0,4 — und nie Teil einer Facette (#63)."""
    buch = steckbrief("violent", "brooding", "pursuit")
    gemocht = ReadingProfile(facets=(), counterweights=(), liked=(Liked("pursuit"),))
    verstaerkt = ReadingProfile(facets=(), counterweights=(), liked=(Liked("pursuit", True),))

    assert round(fit(buch, gemocht, wort, gewichte).share, 2) == 0.3
    assert round(fit(buch, verstaerkt, wort, gewichte).share, 2) == 0.4


def test_the_reason_names_liked_terms_and_patterns_outside_the_facets(wort, gewichte) -> None:
    buch = steckbrief("violent", "brooding", "intricate", "pursuit")
    profil = ReadingProfile(
        facets=(Facet(("harsh", "brooding")),),
        counterweights=(),
        liked=(Liked("harsh"), Liked("brooding"), Liked("intricate", True), Liked("pursuit")),
    )

    marken = [(z.kind, z.text, z.boosted) for z in fit(buch, profil, wort, gewichte).reasons
              if not z.detail]

    assert marken == [
        ("ganz", "hart · gezeichnete Figur", False),
        ("merkmal", "verschachtelt", True),
        ("muster", "Katz und Maus", False),
    ]


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


def test_the_reason_names_the_facet_and_the_sentence(wort, gewichte) -> None:
    zeilen = fit(LEOPARD, PROFIL, wort, gewichte).reasons

    assert (zeilen[0].kind, zeilen[0].text) == ("ganz", "hart · gezeichnete Figur")
    assert zeilen[1].line == "Satz zu violent."


def test_the_reason_does_not_compare_with_the_source_books(wort, gewichte) -> None:
    """„wie Leichenblässe" unter einem Nesbø las sich wie ein Buchvergleich."""
    text = "\n".join(z.line for z in fit(LEOPARD, PROFIL, wort, gewichte).reasons)

    assert "Leichenblässe" not in text and "Otherland" not in text


def test_the_reason_names_what_is_against(wort, gewichte) -> None:
    zeilen = fit(OTHERLAND, PROFIL, wort, gewichte).reasons

    assert "dagegen: gemächlich" in [z.line for z in zeilen]


# --- die Gewichte kommen aus dem Bewertungsschema ------------------------------


def test_the_weights_are_read_from_the_rating_scheme(gewichte) -> None:
    assert (gewichte.full, gewichte.single, gewichte.boost, gewichte.pattern,
            gewichte.counterweight) == (0.8, 0.1, 0.1, 0.3, 0.2)


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
    alt = ReadingProfile(
        facets=(Facet(("harsh", "gibtsnichtmehr")),),
        counterweights=(),
        liked=(Liked("harsh"), Liked("gibtsnichtmehr")),
    )

    ergebnis = fit(LEOPARD, alt, wort, gewichte)

    assert "hart" in [r.line for r in ergebnis.reasons]


def test_what_a_facet_only_partly_hits_counts_through_its_terms(wort, gewichte) -> None:
    """Leopard ist verschachtelt, hat aber keine große Welt: kein Teiltreffer
    der Facette mehr, sondern das gemochte Merkmal für sich (#64)."""
    texte = [r.text for r in fit(LEOPARD, PROFIL, wort, gewichte).reasons if not r.detail]

    assert "verschachtelt" in texte
    assert not any("große Welt" in t for t in texte)


def test_a_family_is_named_once(wort, gewichte) -> None:
    """Der Name steht in der Marke, darunter nur die Sätze."""
    zeilen = fit(LEOPARD, PROFIL, wort, gewichte).reasons
    belege = [z.line for z in zeilen if z.detail]

    assert belege and not any(":" in b.split(" ")[0] for b in belege)
    assert "Satz zu intricate." in belege


def test_a_counterweight_carries_its_sentence_like_a_facet(wort, gewichte) -> None:
    zeilen = list(fit(OTHERLAND, PROFIL, wort, gewichte).reasons)
    dagegen = next(i for i, z in enumerate(zeilen) if z.kind == "dagegen")

    assert zeilen[dagegen + 1].line == "Satz zu leisurely."


# --- Facetten aus der Erstaufnahme (#50) -----------------------------------------

#: Welche geliebten Bücher im Versuch welche Familie trugen (Prototyp E).
TRAEGER = {
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

    facetten = derive_facets(
        ["harsh", "brooding", "nerve_racking", "menacing", "funny", "likeable"], TRAEGER
    )

    # Rosies witzig und nahbar trägt nur ein Buch — keine Facette mehr; sie
    # zählen für sich (#64).
    assert [(f.families, f.books) for f in facetten] == [
        (("harsh", "brooding"), ("K", "L")),
        (("nerve_racking", "menacing"), ("C", "L")),
    ]


def test_not_only_identical_book_sets_form_a_facet() -> None:
    """Schauplatz (L, O, C) und große Ideen (O, C): beide tragen O und C."""
    from ebook_watchlist.facets import derive_facets

    facetten = derive_facets(["atmospheric", "thought_provoking"], TRAEGER)

    assert (("atmospheric", "thought_provoking"), ("C", "O")) in [
        (f.families, f.books) for f in facetten
    ]


def test_a_single_family_is_no_facet() -> None:
    """Zählt für sich (#64), aber bündelt nichts."""
    from ebook_watchlist.facets import derive_facets

    facetten = derive_facets(["harsh", "brooding", "thought_provoking"], TRAEGER)

    assert [f.families for f in facetten] == [("harsh", "brooding")]


def test_one_book_alone_makes_no_facet() -> None:
    """Eine Kombination aus einem Buch sagt mehr über das Buch als über den
    Geschmack (24.09.2026)."""
    from ebook_watchlist.facets import derive_facets

    assert derive_facets(["quirky", "funny", "likeable"], TRAEGER) == []


def test_the_strength_is_a_scale() -> None:
    from ebook_watchlist.facets import strength

    assert [strength(n) for n in (1, 2, 3, 4, 7)] == [
        "schwach", "mittel", "stark", "sehr stark", "sehr stark"
    ]


# --- Review: Genre als ganzes Wort, Fassungsnummern ohne Wettlauf -----------------


@pytest.mark.parametrize(
    ("genre", "untergenre", "trifft"),
    [("Kriminalroman", None, False), ("Liebesroman", None, False), ("Roman", None, True),
     ("Gegenwartsroman", "Roman über Familie", True)],
)
def test_a_genre_counterweight_matches_whole_words_only(wort, gewichte, genre, untergenre,
                                                         trifft) -> None:
    """„nur bei Roman" darf nicht jeden Kriminalroman treffen."""
    profil = ReadingProfile(facets=PROFIL.facets,
                            counterweights=(Counterweight(("harsh",), genre="Roman"),))
    buch = steckbrief("violent", "brooding", genre=genre, subgenre=untergenre)

    assert (fit(buch, profil, wort, gewichte).against is not None) is trifft


def test_high_fantasy_still_matches_its_long_subgenre(wort, gewichte) -> None:
    profil = ReadingProfile(facets=PROFIL.facets,
                            counterweights=(Counterweight(("big_world",), genre="High Fantasy"),))

    assert fit(HERR_DER_RINGE, profil, wort, gewichte).against is not None


def test_concurrent_saves_get_distinct_versions(store: Store) -> None:
    """Ein Doppelklick auf „Übernehmen" darf nicht an der Fassungsnummer scheitern."""
    import threading

    fehler: list[BaseException] = []

    def speichern() -> None:
        try:
            for _ in range(5):
                store.put_reading_profile("test", PROFIL, cause="parallel", now=NOW)
        except BaseException as exc:  # noqa: BLE001
            fehler.append(exc)

    faeden = [threading.Thread(target=speichern) for _ in range(4)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join()

    assert fehler == []
    assert store.reading_profile("test").version == 20


def test_a_family_of_one_book_does_not_grow_a_facet_of_that_book() -> None:
    """Erstaufnahme vom 24.09.: „Erkenntnis" trägt nur *Leichenblässe*, und
    daraus wurde eine Facette aus allem, was *Leichenblässe* trägt. Facetten
    aus einem einzigen Buch gibt es nur für ein Buch, das sonst in keiner
    steckt (Abdeckung)."""
    from ebook_watchlist.facets import derive_facets

    traeger = {**TRAEGER, "discovery": {"L"}}
    facetten = derive_facets(
        ["harsh", "brooding", "nerve_racking", "menacing", "discovery"], traeger
    )

    assert [(f.families, f.books) for f in facetten] == [
        (("harsh", "brooding"), ("K", "L")),
        (("nerve_racking", "menacing"), ("C", "L")),
    ]



# --- gemocht und verstärkt aus einer Datei und im Speicher ---------------------------


def test_liked_and_boosted_can_be_read_from_a_file(tmp_path: Path, wort) -> None:
    datei = _datei(tmp_path, "gemocht: [harsh, brooding, pursuit]\nverstaerkt: [harsh]\n")

    profil = load_profile_file(datei, wort)

    assert profil.liked == (Liked("harsh", True), Liked("brooding"), Liked("pursuit"))


def test_no_more_than_three_are_boosted(tmp_path: Path, wort) -> None:
    datei = _datei(tmp_path, (
        "gemocht: [harsh, brooding, funny, likeable]\n"
        "verstaerkt: [harsh, brooding, funny, likeable]\n"
    ))

    with pytest.raises(ProfileError, match="höchstens 3"):
        load_profile_file(datei, wort)


def test_only_what_is_liked_can_be_boosted(tmp_path: Path, wort) -> None:
    datei = _datei(tmp_path, "gemocht: [harsh]\nverstaerkt: [funny]\n")

    with pytest.raises(ProfileError, match="nicht gemocht"):
        load_profile_file(datei, wort)


def test_the_store_keeps_what_is_liked(store: Store) -> None:
    store.put_reading_profile("test", PROFIL, cause="Test", now=NOW)

    assert store.reading_profile("test").liked == PROFIL.liked
