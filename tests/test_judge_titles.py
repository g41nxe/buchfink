"""Titel und YAML-Listen gegen das Profil halten, ohne die Oberfläche (#67).

Der Code urteilt; das Modell beschreibt höchstens ein Buch, das noch keinen
Steckbrief hat. Kein Test hier ruft ein Modell.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from conftest import STAR_TERMS, describe, give_profile, needs_vocabulary
from ebook_watchlist.judge_titles import Entry, judge_titles, read_entries, update_yaml
from ebook_watchlist.judging import load_judge
from ebook_watchlist.portrait import Portrait, Trait, fingerprint, load_vocabulary
from ebook_watchlist.web.intake import intake_subject

NOW = datetime(2026, 9, 25, 12, 0)


class FakePortrayer:
    """Beschreibt jeden Fund als 4-Sterne-Buch und merkt sich, wen er fragte."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.calls = 0

    def portray_finds(self, observations):
        self.calls += 1
        self.asked.extend(o.title for o in observations)
        return {
            o.key: Portrait(
                known=True,
                fingerprint=fingerprint(load_vocabulary()),
                pitch=f"Über {o.title}.",
                traits=tuple(Trait(t, f"Satz zu {t}", "wissen") for t in STAR_TERMS[4]),
            )
            for o in observations
        }


@pytest.fixture
def judge(store):
    give_profile(store)
    return load_judge(store, "test")


# --- was schon bekannt ist ------------------------------------------------------


@needs_vocabulary
def test_a_known_title_is_judged_without_asking_the_model(store, judge) -> None:
    describe(store, intake_subject("Der Schwarm", "Frank Schätzing"), 3)
    portrayer = FakePortrayer()

    (result,) = judge_titles(
        store, [Entry("Der Schwarm", "Frank Schätzing")], judge, portrayer, now=NOW
    )

    assert result.verdict.stars == 3 and portrayer.calls == 0
    assert result.source == "vorhanden"


@needs_vocabulary
def test_a_title_is_found_under_its_book_too(store, judge) -> None:
    """Dasselbe Buch, das die Leserin schon im Regal hat: ihr Steckbrief gilt."""
    book = store.find_or_create_book(isbn=None, title="Der Schwarm", author="Frank Schätzing",
                                     now=NOW)
    describe(store, f"book:{book.id}", 4)

    (result,) = judge_titles(store, [Entry("der schwarm", None)], judge, FakePortrayer(), now=NOW)

    assert result.verdict.stars == 4 and result.source == "vorhanden"


@needs_vocabulary
def test_a_title_is_found_under_a_find_of_the_pile(store, judge) -> None:
    from ebook_watchlist.models import MatchReason, Observation

    found = Observation(source="beam", source_item_id="9", title="Abwärtsfahrt",
                        match_reason=MatchReason.GENRE_CATEGORY, isbn="9783000000009")
    run_id = store.start_run("test", "cli", NOW)
    store.append(run_id, "test", [found], NOW)
    describe(store, "isbn:9783000000009", 2)

    (result,) = judge_titles(store, [Entry("Abwärtsfahrt", None)], judge, FakePortrayer(), now=NOW)

    assert result.verdict.stars == 2 and result.source == "vorhanden"


# --- was fehlt -------------------------------------------------------------------


@needs_vocabulary
def test_a_new_title_is_described_once_and_kept(store, judge) -> None:
    portrayer = FakePortrayer()
    entry = Entry("Dark Matter", "Blake Crouch")

    (first,) = judge_titles(store, [entry], judge, portrayer, now=NOW)
    (second,) = judge_titles(store, [entry], judge, portrayer, now=NOW)

    assert first.source == "neu" and first.verdict.stars == 4
    assert second.source == "vorhanden" and portrayer.calls == 1
    assert store.portrait(intake_subject("Dark Matter", "Blake Crouch"), judge.stamp) is not None


@needs_vocabulary
def test_several_new_titles_go_in_one_call(store, judge) -> None:
    portrayer = FakePortrayer()

    results = judge_titles(
        store, [Entry("A", None), Entry("B", None), Entry("C", None)], judge, portrayer, now=NOW
    )

    assert portrayer.calls == 1 and portrayer.asked == ["A", "B", "C"]
    assert [r.source for r in results] == ["neu"] * 3


@needs_vocabulary
def test_known_only_never_asks_and_names_what_is_missing(store, judge) -> None:
    portrayer = FakePortrayer()

    (result,) = judge_titles(store, [Entry("Unbekannt", None)], judge, portrayer, now=NOW,
                             ask=False)

    assert result.verdict is None and result.source == "fehlt" and portrayer.calls == 0


@needs_vocabulary
def test_without_a_way_to_the_model_the_title_stays_undescribed(store, judge) -> None:
    (result,) = judge_titles(store, [Entry("Unbekannt", None)], judge, None, now=NOW)

    assert result.verdict is None and result.source == "fehlt"


@needs_vocabulary
def test_a_book_the_model_does_not_know_is_named_not_invented(store, judge) -> None:
    class Unknowing(FakePortrayer):
        def portray_finds(self, observations):
            return {o.key: Portrait(known=False, fingerprint=fingerprint(load_vocabulary()))
                    for o in observations}

    (result,) = judge_titles(store, [Entry("Erfunden", None)], judge, Unknowing(), now=NOW)

    assert result.verdict is None and result.source == "unbekannt"


# --- die YAML-Datei ---------------------------------------------------------------

FILE = """\
# Bücher, die ich bewerten lassen will.
#
# Kommentare bleiben stehen.

- title: Der Schwarm
  author: Frank Schätzing

# ein Kommentar zwischen den Einträgen
- title: Dark Matter
  author: Blake Crouch
  hinweis: Bitte gegenprüfen.
  stars: 1
  why: alt

- title: Ohne Autor
"""


def test_the_entries_are_read_from_the_file() -> None:
    assert read_entries(FILE) == [
        Entry("Der Schwarm", "Frank Schätzing"),
        Entry("Dark Matter", "Blake Crouch"),
        Entry("Ohne Autor", None),
    ]


def test_stars_and_reason_are_written_back_and_comments_stay() -> None:
    from ebook_watchlist.judge_titles import Result
    from ebook_watchlist.judging import Verdict

    results = [
        Result(Entry("Der Schwarm", "Frank Schätzing"), Verdict(4, 63), "vorhanden", "63 % — hart"),
        Result(Entry("Dark Matter", "Blake Crouch"), Verdict(2, 30), "neu", "30 % — dagegen: x"),
        Result(Entry("Ohne Autor", None), None, "fehlt", None),
    ]

    text = update_yaml(FILE, results)

    head = "# Bücher, die ich bewerten lassen will.\n#\n# Kommentare bleiben stehen."
    assert text.startswith(head)
    assert "# ein Kommentar zwischen den Einträgen" in text
    first = '- title: Der Schwarm\n  author: Frank Schätzing\n  stars: 4\n  why: "63 % — hart"\n'
    assert first in text
    # ein vorhandener Wert wird ersetzt, ein fremdes Feld bleibt, die Reihenfolge auch
    assert "  hinweis: Bitte gegenprüfen.\n  stars: 2\n  why: \"30 % — dagegen: x\"\n" in text
    assert text.count("alt") == 0
    # ohne Urteil bleibt der Eintrag, wie er war
    assert text.rstrip().endswith("- title: Ohne Autor")


def test_a_blank_line_inside_an_entry_does_not_split_it() -> None:
    """``stars`` steht nach dem letzten Feld des Eintrags, nicht vor der Lücke —
    sonst stünde es zweimal, und YAML nähme still das letzte."""
    from ebook_watchlist.judge_titles import Result
    from ebook_watchlist.judging import Verdict

    text = "- title: Der Schwarm\n\n  stars: 1\n  why: alt\n\n- title: Anderes\n"
    results = [Result(Entry("Der Schwarm", None), Verdict(4, 63), "vorhanden", "63 %")]

    written = update_yaml(text, results)

    assert written == '- title: Der Schwarm\n\n  stars: 4\n  why: "63 %"\n\n- title: Anderes\n'


def test_the_written_file_reads_back_the_same_way() -> None:
    import yaml

    from ebook_watchlist.judge_titles import Result
    from ebook_watchlist.judging import Verdict

    results = [Result(Entry("Der Schwarm", "Frank Schätzing"), Verdict(4, 63), "vorhanden",
                      'Anführungszeichen " und: Doppelpunkt')]

    data = yaml.safe_load(update_yaml(FILE, results))

    assert data[0]["stars"] == 4 and data[0]["why"] == 'Anführungszeichen " und: Doppelpunkt'
    assert len(data) == 3
