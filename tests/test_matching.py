"""The matcher, driven by its labelled corpus plus unit tests for the pieces."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ebook_watchlist.matching import (
    Candidate,
    Confidence,
    Query,
    authors_contradict,
    match,
    normalize_author,
    normalize_authors,
    normalize_title,
    score,
    split_authors,
    worth_confirming,
)

CORPUS = yaml.safe_load(
    (Path(__file__).parent / "fixtures" / "matching.yaml").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CORPUS, ids=[case["name"] for case in CORPUS])
def test_corpus(case: dict) -> None:
    query = Query(**case["query"])
    candidates = [Candidate(**raw) for raw in case["candidates"]]

    resolution = match(query, candidates)

    assert resolution.confidence is Confidence(case["expect"]), resolution.reason
    if "winner" in case:
        assert resolution.best is not None
        assert resolution.best.candidate.title == case["winner"]


# --- normalisation --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Der Schwarm", "schwarm"),
        ("Die Straße", "strasse"),
        ("Schätzing", "schatzing"),
        ("The Hobbit", "hobbit"),
        ("Die sieben Schwestern - Roman", "sieben schwestern"),
        ("Atlas: Die Geschichte von Pa Salt", "atlas"),
        ("Der Schwarm (ungekürzt)", "schwarm"),
        ("Faust [Neue Auflage]", "faust"),
        ("Der Schwarm (2004)", "schwarm"),
        ("Ein Buch, zwei Bücher!", "buch zwei bucher"),
        ("1,000 Meilen", "1000 meilen"),
        ("  Der   Schwarm  ", "schwarm"),
    ],
)
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


def test_leading_articles_are_dropped_repeatedly() -> None:
    assert normalize_title("Der Die Das Buch") == "buch"


def test_a_title_that_is_only_a_subtitle_marker_is_not_gutted() -> None:
    """Cutting must never leave a single stray character behind."""
    assert normalize_title("R - Ein Roman") == "r ein roman"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Frank Schätzing", "frank schatzing"),
        ("Schätzing, Frank", "frank schatzing"),
        ("Dr. Johann Wolfgang von Goethe", "johann wolfgang goethe"),
        ("Goethe, Johann Wolfgang von", "johann wolfgang goethe"),
        ("Lucinda Riley (Übersetzerin)", "lucinda riley"),
        ("Martin Luther King Jr.", "martin luther king"),
    ],
)
def test_normalize_author(raw: str, expected: str) -> None:
    assert normalize_author(raw).full == expected


def test_initials_survive_the_main_form_but_not_the_looser_one() -> None:
    """Calibre drops every short token outright; that loses real information."""
    normalized = normalize_author("J. R. R. Tolkien")
    assert normalized.full == "j r r tolkien"
    assert normalized.substantial == "tolkien"


def test_an_imprint_is_not_reordered_like_a_person() -> None:
    assert normalize_author("Beispiel Verlag GmbH").full == "beispiel verlag gmbh"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Riley, Lucinda", ["Riley, Lucinda"]),
        ("Riley, Lucinda; Whittaker, Harry", ["Riley, Lucinda", "Whittaker, Harry"]),
        ("Anna Meier & Bernd Schulz", ["Anna Meier", "Bernd Schulz"]),
        ("Anna Meier und Bernd Schulz", ["Anna Meier", "Bernd Schulz"]),
        ("Anna Meier and Bernd Schulz", ["Anna Meier", "Bernd Schulz"]),
        ("Anna Meier, Bernd Schulz", ["Anna Meier", "Bernd Schulz"]),
    ],
)
def test_split_authors(raw: str, expected: list[str]) -> None:
    assert split_authors(raw) == expected


def test_a_lone_comma_between_single_words_stays_a_sort_order() -> None:
    """`Riley, Lucinda` is one person; splitting it would invent a second."""
    assert split_authors("Riley, Lucinda") == ["Riley, Lucinda"]


# --- ranking --------------------------------------------------------------


def test_the_sort_key_prefers_exact_title_over_a_better_author_score() -> None:
    query = Query(title="Der Schwarm", author="Frank Schätzing")
    exact_title = score(query, Candidate(title="Der Schwarm", author="F. Schätzing"))
    better_author = score(query, Candidate(title="Der Schwarm 2", author="Frank Schätzing"))
    assert exact_title.sort_key < better_author.sort_key


def test_year_breaks_a_tie_only_after_everything_else() -> None:
    query = Query(title="Faust", author="Johann Wolfgang von Goethe", year=2015)
    near = score(query, Candidate(title="Faust", author="Goethe, Johann Wolfgang", year=2015))
    far = score(query, Candidate(title="Faust", author="Goethe, Johann Wolfgang", year=1999))
    assert near.sort_key < far.sort_key
    # Alles bis zum Jahr ist gleich; das Jahr steht an Stelle 6, seit
    # 'Enthaltensein' als eigenes Kriterium dazugekommen ist (Ticket 36).
    assert near.sort_key[:6] == far.sort_key[:6]


def test_fuzzy_scores_are_bucketed_so_a_single_point_does_not_decide() -> None:
    query = Query(title="Der Schwarm", author="Frank Schätzing")
    scored = score(query, Candidate(title="Der Schwarm", author="Frank Schätzing"))
    assert scored.title_fuzzy == 100
    # Ohne feste Stelle im Schlüssel: der bekommt immer wieder ein Kriterium
    # dazu, und einen Index zu prüfen hieße, den Test bei jeder Erweiterung
    # anzufassen, ohne dass er dabei mehr belegt.
    assert -(scored.title_fuzzy // 5) in scored.sort_key


def test_source_order_is_the_last_resort_tie_break() -> None:
    query = Query(title="Faust")
    first = score(query, Candidate(title="Faust"), source_rank=0)
    second = score(query, Candidate(title="Faust"), source_rank=1)
    assert first.sort_key < second.sort_key


def test_ranking_is_returned_in_full_for_the_needs_attention_list() -> None:
    query = Query(title="Die sieben Schwestern", author="Lucinda Riley")
    resolution = match(
        query,
        [
            Candidate(title="Die Sturmschwester", author="Riley, Lucinda"),
            Candidate(title="Die sieben Schwestern", author="Riley, Lucinda"),
        ],
    )
    assert len(resolution.ranked) == 2
    assert resolution.ranked[0].candidate.title == "Die sieben Schwestern"


def test_no_match_withholds_the_best_candidate() -> None:
    resolution = match(
        Query(title="Der Schwarm", author="Frank Schätzing"),
        [Candidate(title="Kochen mit Kräutern", author="Erika Mustermann")],
    )
    assert resolution.confidence is Confidence.NO_MATCH
    assert resolution.best is None
    assert resolution.accepted is None
    assert resolution.ranked  # still available for diagnostics


def test_only_auto_accept_yields_an_accepted_candidate() -> None:
    resolution = match(
        Query(title="Der Schwarm", author="Frank Schätzing"),
        [Candidate(title="Der Schwarm", author="Erika Mustermann")],
    )
    assert resolution.confidence is Confidence.PROVISIONAL
    assert resolution.best is not None
    assert resolution.accepted is None


def test_the_matcher_touches_nothing_outside_itself() -> None:
    """A pure function: same inputs, same answer, no state carried between calls."""
    query = Query(title="Der Schwarm", author="Frank Schätzing")
    candidates = [Candidate(title="Der Schwarm", author="Schätzing, Frank")]
    first = match(query, candidates)
    second = match(query, candidates)
    assert first == second


# --- welche Kandidaten der Leserin vorgelegt werden (Ticket 41) -------------


def test_only_the_indistinguishable_candidates_are_offered() -> None:
    """Gezeigt wird, was der Matcher nicht auseinanderhalten konnte — nicht die
    ersten drei und nicht alles über einer erfundenen Punktzahl. Das ist die
    Antwort auf „warum fragst du mich?"."""
    resolution = match(
        Query(title="Der Kruzifix-Killer", author="Chris Carter"),
        [
            Candidate(title="Der Kruzifix-Killer", author="Carter, Chris"),
            Candidate(title="Der Kruzifix-Killer / Der Vollstrecker", author="Carter, Chris"),
            Candidate(title="Ein ganz anderes Buch", author="Carter, Chris"),
        ],
    )

    titel = [kandidat.title for kandidat in resolution.indistinguishable]
    assert titel == ["Der Kruzifix-Killer"]


def test_a_genuine_tie_offers_both() -> None:
    resolution = match(
        Query(title="Faust", author="Goethe"),
        [
            Candidate(title="Faust", author="Goethe, Johann Wolfgang"),
            Candidate(title="Faust", author="Goethe, Johann Wolfgang"),
        ],
    )

    assert len(resolution.indistinguishable) == 2


def test_the_list_is_capped() -> None:
    """Eine Sicherung gegen den Fall, dass zwanzig Titel gleich aussehen —
    zwanzig Kandidaten wären keine Hilfe mehr."""
    resolution = match(
        Query(title="Faust", author="Goethe"),
        [Candidate(title="Faust", author="Goethe, Johann Wolfgang") for _ in range(9)],
    )

    assert len(resolution.indistinguishable) == 5


def test_nothing_found_offers_nothing() -> None:
    assert match(Query(title="Faust"), []).indistinguishable == ()


# --- Widerspruch der Person (Ticket 45) -----------------------------------


def test_a_contradicting_author_loses_against_the_right_one() -> None:
    """Der Anlass: „Dark Matter" von Blake Crouch stand auf der Watchlist, im
    Shop trafen drei fremde Bücher den Titel exakt, und das richtige war das
    einzige mit übereinstimmender Autor:in — und verlor (ADR 23, Nachtrag)."""
    query = Query(title="Dark Matter", author="Blake Crouch")
    fremd = score(query, Candidate(title="Dark Matter", author="Kim Mannix"))
    richtig = score(query, Candidate(title="Dark Matter. Der Zeitenläufer", author="Crouch, Blake"))

    assert fremd.author_conflict
    assert not richtig.author_conflict
    assert richtig.sort_key < fremd.sort_key


def test_the_wrong_author_is_not_offered_as_an_equal_choice() -> None:
    """Der eigentliche Schaden lag in `_is_tied`: der Leserin wäre genau eine
    Karte vorgelegt worden — die falsche."""
    query = Query(title="Dark Matter", author="Blake Crouch")
    resolution = match(
        query,
        [
            Candidate(title="Dark Matter", author="Kim Mannix"),
            Candidate(title="A Dark Matter", author="Doug Johnstone"),
            Candidate(title="Dark Matter. Der Zeitenläufer", author="Crouch, Blake"),
        ],
    )

    assert [c.title for c in resolution.indistinguishable] == ["Dark Matter. Der Zeitenläufer"]


def test_an_abbreviated_given_name_is_not_a_contradiction() -> None:
    """„F. Schätzing" ist Frank Schätzing, nur mit weniger Information.
    `author_matches` sagt dazu Nein — als Widerspruch zu lesen wäre falsch."""
    assert not authors_contradict("Frank Schätzing", "F. Schätzing")


def test_a_shared_surname_leaves_it_undecided() -> None:
    """Bewusst vorsichtig: ein negatives Signal, das zu oft ausschlägt, wäre
    schlimmer als eines, das manchmal schweigt."""
    assert not authors_contradict("S.A. Barnes", "J.S. Barnes")


def test_a_missing_author_field_is_not_a_contradiction() -> None:
    """Nichtwissen widerspricht nicht."""
    assert not authors_contradict("Blake Crouch", None)
    assert not authors_contradict(None, "Doug Johnstone")


def test_a_surname_with_spaced_initials_stays_one_person() -> None:
    """`split_authors` las das Komma als Trenner zwischen Personen, weil
    „S. A." zwei durch Leerzeichen getrennte Wörter hat. Ohne die Korrektur
    hätte der Autor-Widerspruch eine richtige Zuordnung verschlechtert."""
    assert split_authors("Barnes, S. A.") == ["Barnes, S. A."]
    assert normalize_authors("Barnes, S. A.")[0].full == "s a barnes"


# --- eine Frage, die jemand beantworten kann (Ticket 53) -------------------


def test_a_contained_title_without_any_author_is_no_question() -> None:
    """Der Anlass: „Autorität" von VanderMeer bekam „Neue Autorität – Das
    Handbuch" vorgelegt, ein Sachbuch, das der Shop ohne jeden Verfasser
    führt. Enthalten ist der Titel — zu entscheiden gibt es nichts."""
    resolution = match(
        Query(title="Autorität", author="VanderMeer"),
        [Candidate(title="Neue Autorität – Das Handbuch", author=None)],
    )

    assert resolution.confidence is Confidence.NO_MATCH


def test_a_contained_title_with_the_right_author_stays_a_question() -> None:
    """Der Fall, für den `title_is_contained` gebaut wurde (Ticket 36)."""
    resolution = match(
        Query(title="Dark Matter", author="Blake Crouch"),
        [Candidate(title="Dark Matter. Der Zeitenläufer", author="Crouch, Blake")],
    )

    assert resolution.confidence is Confidence.PROVISIONAL


def test_an_entry_without_an_author_still_gets_asked() -> None:
    """Wer keine Autor:in angibt, kann auch keine bestätigt bekommen — die
    Regel darf ihm die Rückfrage nicht nehmen."""
    resolution = match(
        Query(title="Judas", author=None),
        [Candidate(title="Kinder des Judas", author=None)],
    )

    assert resolution.confidence is Confidence.PROVISIONAL


def test_a_shortened_own_spelling_does_not_lose_the_question() -> None:
    """Gemessen an den gespeicherten Zuordnungen liegt jede Eingabe, die nur
    einen Nachnamen trägt, zwischen „bestätigt" und „widerspricht". Eine
    Bestätigung zu verlangen hätte solche Einträge dauerhaft von jeder
    Rückfrage ausgeschlossen."""
    assert worth_confirming(
        score(Query(title="Autorität", author="VanderMeer"),
              Candidate(title="Autorität – Der Roman", author="VanderMeer, Jeff")),
        Query(title="Autorität", author="VanderMeer"),
    )


def test_a_contradicting_author_ends_the_question() -> None:
    resolution = match(
        Query(title="Dark Matter", author="Blake Crouch"),
        [Candidate(title="Dark Matter and Dark Energy", author="Brian Clegg")],
    )

    assert resolution.confidence is Confidence.NO_MATCH


def test_a_nameless_candidate_does_not_mask_a_named_one() -> None:
    """Der Befund aus dem Review: `worth_confirming` wurde nur an `best`
    geprüft, und die Rangfolge wusste nichts davon. Ein autorloser Kandidat mit
    ähnlicherem Titel verdeckte damit einen tiefer stehenden, der die richtige
    Autor:in nennt — Ergebnis `no_match`, obwohl es etwas zu fragen gab."""
    resolution = match(
        Query(title="Autorität", author="Jeff VanderMeer"),
        [
            Candidate(title="Autorität heute", author=None),
            Candidate(title="Autorität und die Grenzen der Macht", author="VanderMeer, Jeff"),
        ],
    )

    assert resolution.best.candidate.author == "VanderMeer, Jeff"
    assert resolution.confidence is Confidence.PROVISIONAL


def test_an_exact_title_without_an_author_still_beats_a_contained_one() -> None:
    """Die Stelle im Sortierschlüssel ist heikel: weiter vorne hätte das
    fehlende Autorfeld einen exakten Titel hinter einen bloß enthaltenen
    sortiert."""
    query = Query(title="Kugelblitz", author="Cixin Liu")
    exakt = score(query, Candidate(title="Kugelblitz", author=None))
    enthalten = score(query, Candidate(title="Kugelblitz und Donner", author="Liu, Cixin"))

    assert exakt.sort_key < enthalten.sort_key


def test_the_reason_says_which_of_the_two_it_was() -> None:
    """„Nennt niemanden" und „nennt jemand anderen" sind zwei verschiedene
    Auskünfte."""
    ohne = match(
        Query(title="Autorität", author="VanderMeer"),
        [Candidate(title="Neue Autorität – Das Handbuch", author=None)],
    )
    falsch = match(
        Query(title="Dark Matter", author="Blake Crouch"),
        [Candidate(title="Dark Matter and Dark Energy", author="Brian Clegg")],
    )

    assert "keine Autor:in" in ohne.reason
    assert "andere Autor:in" in falsch.reason


def test_every_signal_that_decides_also_sorts() -> None:
    """Die Invariante, die an einem Tag dreimal verletzt wurde.

    Ticket 45 (`author_conflict`), Ticket 53 (`author_missing`) und der Review
    dazu (`id_conflict`) waren derselbe Fehler: ein Kriterium wurde in
    `_confidence` geprüft, aber nicht in `sort_key` — und damit entschied bei
    zwei sonst gleichen Kandidaten die Reihenfolge der Shop-Treffer, welcher
    gewinnt. Jedes Mal war die Reparatur, das Signal in den Schlüssel zu
    heben.

    Dieser Test prüft die Regel statt der Fälle: **was auf `Scored` steht,
    sortiert mit.** Ein neues Feld, das nur an der Entscheidungsstelle gelesen
    wird, lässt ihn umfallen — genau dann, wenn der Fehler entsteht, und nicht
    erst wenn jemand einen falschen Kandidaten auf der Watchlist sieht.
    """
    import dataclasses
    import inspect
    import re

    from ebook_watchlist.matching import matcher

    quelle = inspect.getsource(matcher)
    schluessel = re.search(r"def sort_key\(self\).*?\n        \)\n", quelle, re.S)
    assert schluessel is not None, "sort_key nicht gefunden — der Test misst nichts"

    ohne_wirkung = [
        feld.name
        for feld in dataclasses.fields(matcher.Scored)
        if feld.name != "candidate" and f"self.{feld.name}" not in schluessel.group(0)
    ]

    assert not ohne_wirkung, (
        f"Diese Signale entscheiden mit, sortieren aber nicht: {ohne_wirkung}. "
        "Bei zwei sonst gleichen Kandidaten entscheidet damit die Reihenfolge "
        "der Quelle — siehe Ticket 45, 53 und den Review zu 54."
    )


def test_a_contradicting_identifier_loses_the_place_not_only_the_confidence() -> None:
    """Gefunden durch die Invariante oben: `id_conflict` hob seit Ticket 36 nur
    die Sicherheitsstufe. Ein Kandidat mit *falscher* ISBN gewann deshalb gegen
    einen ohne Widerspruch, wenn er im Shop zufällig zuerst stand."""
    query = Query(title="Der Schwarm", author="Frank Schätzing", identifier="9783462033748")
    widerspricht = Candidate(
        title="Der Schwarm", author="Frank Schätzing", identifier="9780000000001"
    )
    unauffaellig = Candidate(title="Der Schwarm - Roman", author="Frank Schätzing")

    resolution = match(query, [widerspricht, unauffaellig])

    assert resolution.ranked[0].candidate is unauffaellig


# --- ein fehlendes Autorfeld ist kein Widerspruch (#20) ---------------------


def test_a_find_without_an_author_is_taken_on_an_exact_title() -> None:
    """*Wayward Pines-Trilogie* von Blake Crouch musste bestaetigt werden,
    obwohl der Titel exakt stimmte: das Paket nennt im Shop keine Autorin, und
    "nennt niemanden" zaehlte wie "nennt jemand anderen". Haette der Eintrag
    keine Autorin gehabt, waere es angenommen worden."""
    ergebnis = match(
        Query(title="Wayward Pines-Trilogie", author="Blake Crouch"),
        [Candidate(title="Wayward Pines-Trilogie", author=None),
         Candidate(title="Wayward Pines", author="Blake Crouch")],
    )

    assert ergebnis.confidence is Confidence.AUTO_ACCEPT


def test_a_different_author_is_still_a_contradiction() -> None:
    ergebnis = match(
        Query(title="Wayward Pines-Trilogie", author="Blake Crouch"),
        [Candidate(title="Wayward Pines-Trilogie", author="Jemand Anderes")],
    )

    assert ergebnis.confidence is not Confidence.AUTO_ACCEPT


@pytest.mark.parametrize("autorin", ["Richard K. Morgan", None])
def test_a_one_word_title_is_asked_about(autorin: str | None) -> None:
    """Einwortige Titel sind genau die, bei denen eine zufaellige
    Namensgleichheit plausibel ist — ohne Autorin am Treffer wird dort
    weiter gefragt. Das gilt auch fuer einen Eintrag ohne Autorin, der das
    Risiko vorher ungeschuetzt trug. Gezaehlt wird nach der Normalisierung:
    "Der Morgen" ist ein Wort, "Der" macht nichts unverwechselbar."""
    for titel in ("Profit", "Der Morgen"):
        ergebnis = match(Query(title=titel, author=autorin),
                         [Candidate(title=titel, author=None)])

        assert ergebnis.confidence is Confidence.PROVISIONAL, titel


def test_an_entry_without_an_author_still_takes_a_distinct_title() -> None:
    ergebnis = match(Query(title="Dark Matter"),
                     [Candidate(title="Dark Matter", author=None)])

    assert ergebnis.confidence is Confidence.AUTO_ACCEPT
