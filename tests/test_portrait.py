"""Der Steckbrief eines Buchs: was ein Modell einmal über ein Buch sagt (#45).

Die Grundlage des neuen Urteils (ADR 33): das Modell sieht jedes Buch genau
einmal, unabhängig von jeder Leserin, und gibt ihm Merkmale aus einem festen
Vokabular. Geurteilt wird hier noch nicht.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from conftest import needs_vocabulary
from ebook_watchlist.portrait import (
    Portrait,
    PortrayalUnavailable,
    Trait,
    VocabularyError,
    fingerprint,
    load_vocabulary,
    parse_answer,
    parse_many,
    prompt,
    prompt_many,
)
from ebook_watchlist.portrayer import Portrayer
from ebook_watchlist.store import Store

pytestmark = needs_vocabulary

NOW = datetime(2026, 9, 24, 10, 0)

#: Die Antwort des Modells zu *Leopard* aus dem Versuch vom 23.09., gekürzt.
LEOPARD = {
    "bekannt": True,
    "titel": "Leopard",
    "autor": "Jo Nesbø",
    "originaltitel": "Panserhjerte",
    "genre": "Kriminalroman",
    "untergenre": "Nordic Noir",
    "pitch": "Harry Hole wird aus einer Opiumhöhle in Hongkong zurückgeholt, "
             "um einen Mörder mit einer Kugel voller Nadeln zu jagen.",
    "merkmale": [
        {"id": "brooding", "satz": "Harry Hole wird aus einer Opiumhöhle zurückgeholt.",
         "beleg": "wissen", "gewicht": "praegend"},
        {"id": "violent", "satz": "Der Leopoldsapfel wird genau ausgemalt.", "beleg": "wissen",
         "gewicht": "deutlich"},
        {"id": "flawed", "satz": "Er greift bei jedem Rückschlag zur Flasche.", "beleg": "wissen",
         "gewicht": "deutlich"},
        {"id": "intricate", "satz": "Mehrere Opfer, deren Verbindung sich spät zeigt.",
         "beleg": "wissen", "gewicht": "rand"},
        {"id": "intensifying", "satz": "Nach der Rückkehr nach Oslo zieht es an.",
         "beleg": "wissen", "gewicht": "rand"},
    ],
    "erzaehlmuster": [
        {"id": "pursuit", "satz": "Hole jagt einen Mörder, der ihm immer einen Schritt voraus ist.",
         "beleg": "wissen"},
    ],
}


def answer(**changes) -> str:
    return json.dumps({**LEOPARD, **changes}, ensure_ascii=False)


# --- das Vokabular ----------------------------------------------------------


def test_the_vocabulary_is_the_one_in_the_repository() -> None:
    vocabulary = load_vocabulary()

    terms = [t for t in vocabulary.terms if not vocabulary.is_pattern(t)]
    assert len(terms) == 72
    assert vocabulary.terms["gritty"].name == "schonungslos"
    assert vocabulary.terms["gritty"].dimension == "Stil"


def test_a_term_knows_its_family() -> None:
    """Drei Begriffe, die NoveList trennt und die Leserin nicht unterscheidet."""
    vocabulary = load_vocabulary()

    assert {vocabulary.family_of(t).name for t in ("violent", "disturbing", "gritty")} == {"hart"}


def test_a_term_outside_every_family_is_its_own() -> None:
    vocabulary = load_vocabulary()

    family = vocabulary.family_of("leisurely")

    assert family.name == "gemächlich"
    assert family.members == ("leisurely",)


def _vocabulary(tmp_path: Path, terms: str, families: str = "[]") -> Path:
    file = tmp_path / "merkmale.yaml"
    file.write_text(
        "dimensionen:\n"
        "  - id: pace\n    name: Tempo\n    frage: wie es vorangeht\n"
        f"    merkmale: {terms}\n"
        f"familien: {families}\n",
        encoding="utf-8",
    )
    return file


def test_a_duplicate_id_is_refused(tmp_path: Path) -> None:
    file = _vocabulary(
        tmp_path,
        "[{id: fast, name: rasant, beschreibung: a}, {id: fast, name: schnell, beschreibung: b}]",
    )

    with pytest.raises(VocabularyError, match="fast"):
        load_vocabulary(file)


def test_a_family_may_only_name_terms_that_exist(tmp_path: Path) -> None:
    file = _vocabulary(
        tmp_path,
        "[{id: fast, name: rasant, beschreibung: a}]",
        "[{id: quick, name: flott, merkmale: [fast, gibtsnicht]}]",
    )

    with pytest.raises(VocabularyError, match="gibtsnicht"):
        load_vocabulary(file)


def test_a_term_belongs_to_one_family_only(tmp_path: Path) -> None:
    file = _vocabulary(
        tmp_path,
        "[{id: fast, name: rasant, beschreibung: a}, {id: slow, name: langsam, beschreibung: b}]",
        "[{id: a, name: A, merkmale: [fast, slow]}, {id: b, name: B, merkmale: [fast]}]",
    )

    with pytest.raises(VocabularyError, match="fast"):
        load_vocabulary(file)


# --- die Anweisung ----------------------------------------------------------


def test_the_prompt_carries_the_book_and_every_term() -> None:
    vocabulary = load_vocabulary()

    text = prompt("Leopard", "Jo Nesbø", None, vocabulary)

    assert "Titel: Leopard" in text and "Autor: Jo Nesbø" in text
    assert "Klappentext" not in text.split("--- BUCH ---")[1]
    assert all(term_id in text for term_id in vocabulary.terms)


def test_a_blurb_goes_along_when_there_is_one() -> None:
    text = prompt("Leopard", "Jo Nesbø", "Harry Hole kehrt zurück.", load_vocabulary())

    assert "Klappentext: Harry Hole kehrt zurück." in text


def test_the_fingerprint_follows_the_terms_not_the_families(tmp_path: Path) -> None:
    """Die Familien sind ein Arbeitsstand; sie zu ändern darf kein Buch neu
    fragen lassen. Ein geänderter Begriff dagegen schon."""
    terms = (
        "[{id: fast, name: rasant, beschreibung: a}, "
        "{id: slow, name: langsam, beschreibung: b}]"
    )
    without = load_vocabulary(_vocabulary(tmp_path, terms))
    with_it = load_vocabulary(
        _vocabulary(tmp_path, terms, "[{id: t, name: Tempo, merkmale: [fast, slow]}]")
    )
    changed = terms.replace("beschreibung: a", "beschreibung: x")
    different = load_vocabulary(_vocabulary(tmp_path, changed))

    assert fingerprint(without) == fingerprint(with_it)
    assert fingerprint(without) != fingerprint(different)


# --- die Antwort ------------------------------------------------------------


def test_a_good_answer_becomes_a_portrait() -> None:
    vocabulary = load_vocabulary()

    portrait = parse_answer(answer(), vocabulary)

    assert portrait.known
    assert portrait.original_title == "Panserhjerte"
    assert (portrait.genre, portrait.subgenre) == ("Kriminalroman", "Nordic Noir")
    assert [t.term for t in portrait.traits] == ["brooding", "violent", "flawed", "intricate",
                                            "intensifying", "pursuit"]
    assert portrait.traits[0] == Trait("brooding", "Harry Hole wird aus einer Opiumhöhle "
                                               "zurückgeholt.", "wissen", "defining")
    assert portrait.violations == ()
    assert portrait.fingerprint == fingerprint(vocabulary)


def test_the_rules_are_checked_and_kept_not_hidden() -> None:
    """Ein Verstoß verwirft den Steckbrief nicht; er steht daneben."""
    vocabulary = load_vocabulary()
    too_few = LEOPARD["merkmale"][:3]

    portrait = parse_answer(answer(merkmale=too_few), vocabulary)

    assert any("drei" in v or "3" in v for v in portrait.violations)
    assert len(portrait.traits) == 4  # drei Merkmale und das Muster


def test_a_term_outside_the_vocabulary_is_dropped_and_named() -> None:
    vocabulary = load_vocabulary()
    invented = [*LEOPARD["merkmale"], {"id": "episch-wuchtig", "satz": "x", "beleg": "wissen"}]

    portrait = parse_answer(answer(merkmale=invented), vocabulary)

    assert "episch-wuchtig" not in [t.term for t in portrait.traits]
    assert any("episch-wuchtig" in v for v in portrait.violations)


def test_too_many_from_one_dimension_is_a_violation() -> None:
    vocabulary = load_vocabulary()
    mood = [{"id": t, "satz": "x", "beleg": "wissen"}
                for t in ("bleak", "moody", "menacing", "disturbing")]
    extra = [{"id": "brooding", "satz": "x", "beleg": "wissen"},
            {"id": "gritty", "satz": "x", "beleg": "wissen"}]

    portrait = parse_answer(answer(merkmale=mood + extra), vocabulary)

    assert any("Stimmung" in v for v in portrait.violations)


def test_an_unknown_evidence_is_a_violation() -> None:
    vocabulary = load_vocabulary()
    terms = [{**m, "beleg": "vermutung"} if i == 0 else m
                for i, m in enumerate(LEOPARD["merkmale"])]

    portrait = parse_answer(answer(merkmale=terms), vocabulary)

    assert any("vermutung" in v for v in portrait.violations)


def test_each_term_carries_the_weight_the_model_gave_it() -> None:
    """#62: wie stark ein Merkmal in diesem Buch ist — nicht, ob es vorkommt.
    Ein Erzählmuster trägt keines: es steht nur da, wenn es die Geschichte trägt."""
    portrait = parse_answer(answer(), load_vocabulary())

    assert [t.weight for t in portrait.traits] == [
        "defining", "clear", "clear", "marginal", "marginal", None
    ]
    assert portrait.violations == ()


def test_a_term_without_a_weight_is_a_violation_and_stays_unweighted() -> None:
    terms = [{k: v for k, v in m.items() if k != "gewicht"} if i == 0 else m
                for i, m in enumerate(LEOPARD["merkmale"])]

    portrait = parse_answer(answer(merkmale=terms), load_vocabulary())

    assert any("Gewicht" in v and "brooding" in v for v in portrait.violations)
    assert portrait.traits[0].weight is None and portrait.traits[0].term == "brooding"


def test_an_unknown_weight_is_a_violation() -> None:
    terms = [{**m, "gewicht": "riesig"} if i == 0 else m
                for i, m in enumerate(LEOPARD["merkmale"])]

    portrait = parse_answer(answer(merkmale=terms), load_vocabulary())

    assert any("riesig" in v for v in portrait.violations)
    assert portrait.traits[0].weight is None


def test_the_weight_with_an_umlaut_is_read_as_the_same_word() -> None:
    """Gemessen am 25.09.2026: bei sechs von 24 Steckbriefen schrieb das Modell
    „prägend“ statt „praegend“. Es gibt keine zweite Lesart, also wird es gelesen."""
    terms = [{**m, "gewicht": "prägend"} if i == 0 else m
                for i, m in enumerate(LEOPARD["merkmale"])]

    portrait = parse_answer(answer(merkmale=terms), load_vocabulary())

    assert portrait.traits[0].weight == "defining"
    assert portrait.violations == ()


def test_a_weight_on_a_pattern_is_ignored() -> None:
    patterns = [{**LEOPARD["erzaehlmuster"][0], "gewicht": "praegend"}]

    portrait = parse_answer(answer(erzaehlmuster=patterns), load_vocabulary())

    assert portrait.traits[-1].term == "pursuit" and portrait.traits[-1].weight is None
    assert portrait.violations == ()


def test_evidence_from_a_sample_is_no_longer_valid() -> None:
    """Seit #68 wird keine Leseprobe mehr mitgeschickt; wer sich darauf beruft,
    hat sie erfunden (#69: bei „Auslöschung“ geschah es zweimal)."""
    terms = [{**m, "beleg": "leseprobe"} if i == 0 else m
                for i, m in enumerate(LEOPARD["merkmale"])]

    portrait = parse_answer(answer(merkmale=terms), load_vocabulary())

    assert any("leseprobe" in v for v in portrait.violations)


def test_the_instruction_asks_for_a_weight_and_no_longer_names_the_sample() -> None:
    text = prompt("Leopard", "Jo Nesbø", None, load_vocabulary())

    assert '"gewicht"' in text and "praegend" in text
    assert "leseprobe" not in text.lower()


def test_the_instruction_never_lets_a_blurb_make_a_book_unknown() -> None:
    """#69: zwei von sieben Büchern kamen trotz ganzem Klappentext als „unbekannt“."""
    text = prompt("Angst sei dein Begleiter", "Carla Cassidy", "Ein Klappentext.",
                  load_vocabulary())

    assert "nie auf false" in text


def test_the_instruction_keeps_patterns_out_of_the_terms_and_trims_by_weight() -> None:
    text = prompt("Leopard", "Jo Nesbø", None, load_vocabulary())

    assert 'nie unter "merkmale"' in text
    assert "geringsten Gewicht" in text
    assert "180 Zeichen" in text


def test_a_pitch_that_is_too_long_is_a_violation() -> None:
    portrait = parse_answer(answer(pitch="x" * 400), load_vocabulary())

    assert any("Pitch" in v for v in portrait.violations)


def test_a_book_the_model_does_not_know_has_no_traits() -> None:
    """Die Probe für „nichts erfinden": ein erfundener Titel."""
    portrait = parse_answer(json.dumps({"bekannt": False}), load_vocabulary())

    assert not portrait.known
    assert portrait.traits == ()
    assert portrait.violations == ()


def test_unknown_but_with_traits_is_a_violation() -> None:
    portrait = parse_answer(answer(bekannt=False), load_vocabulary())

    assert any("unbekannt" in v for v in portrait.violations)


def test_no_json_is_no_portrait() -> None:
    with pytest.raises(PortrayalUnavailable):
        parse_answer("Dazu kann ich nichts sagen.", load_vocabulary())


# --- ein Aufruf -------------------------------------------------------------


def test_a_portrayer_asks_once_and_reads_the_answer() -> None:
    asked: list[str] = []

    class Wire:
        def ask(self, text: str, max_tokens: int = 2000) -> str:
            asked.append(text)
            return answer()

    portrait = Portrayer(Wire(), load_vocabulary()).portray("Leopard", "Jo Nesbø", None)

    assert len(asked) == 1 and "Titel: Leopard" in asked[0]
    assert portrait.known and len(portrait.traits) == 6


# --- gespeichert -------------------------------------------------------------


def test_a_portrait_is_kept_per_subject_and_fingerprint(store: Store) -> None:
    vocabulary = load_vocabulary()
    portrait = parse_answer(answer(), vocabulary)

    store.put_portrait("isbn:9783548289441", portrait, now=NOW)

    again = store.portrait("isbn:9783548289441", portrait.fingerprint)
    assert again == portrait
    assert store.portrait("isbn:9783548289441", "anderer-abdruck") is None
    assert store.portrait("isbn:0000000000000", portrait.fingerprint) is None


def test_the_latest_portrait_wins(store: Store) -> None:
    """Append-only (ADR 5): ein zweiter Steckbrief ersetzt nichts, er kommt dazu."""
    vocabulary = load_vocabulary()
    old = parse_answer(answer(pitch="Alt."), vocabulary)
    new = parse_answer(answer(pitch="Neu."), vocabulary)

    store.put_portrait("book:7", old, now=NOW)
    store.put_portrait("book:7", new, now=NOW.replace(hour=11))

    assert store.portrait("book:7", new.fingerprint).pitch == "Neu."


def test_a_portrait_without_text_does_not_displace_one_with_text(store: Store) -> None:
    """*Gestohlene Erinnerung* (26.09.2026): um 10:35 mit Klappentext
    beschrieben, um 18:49 ohne — und der zweite hielt das Buch für *Dark
    Matter*. Wer nur aus dem Gedächtnis schreibt, verdrängt keinen Beleg."""
    from dataclasses import replace

    vocabulary = load_vocabulary()
    with_text = replace(parse_answer(answer(pitch="Mit Text."), vocabulary), with_text=True)
    without = replace(parse_answer(answer(pitch="Ohne Text."), vocabulary), with_text=False)
    later = replace(parse_answer(answer(pitch="Später mit Text."), vocabulary), with_text=True)

    store.put_portrait("isbn:1", with_text, now=NOW)
    store.put_portrait("isbn:1", without, now=NOW.replace(hour=18))

    assert store.portrait("isbn:1", with_text.fingerprint).pitch == "Mit Text."
    assert store.portraits_for(["isbn:1"], with_text.fingerprint)["isbn:1"].pitch == "Mit Text."

    store.put_portrait("isbn:1", later, now=NOW.replace(hour=19))
    assert store.portrait("isbn:1", later.fingerprint).pitch == "Später mit Text."


def test_an_unknown_book_is_kept_too(store: Store) -> None:
    """Sonst würde jede Seite dasselbe unbekannte Buch erneut fragen."""
    portrait = parse_answer(json.dumps({"bekannt": False}), load_vocabulary())

    store.put_portrait("book:9", portrait, now=NOW)

    assert store.portrait("book:9", portrait.fingerprint) == Portrait(
        known=False, fingerprint=portrait.fingerprint
    )


def test_known_must_be_a_real_yes() -> None:
    """„false" als Text ist kein Ja."""
    portrait = parse_answer(answer(bekannt="false"), load_vocabulary())

    assert not portrait.known


def test_the_instruction_forbids_spoilers_for_sentences_pitch_and_series() -> None:
    """Die Sätze stehen auf der Buchseite, bevor die Leserin das Buch liest.
    Der erste echte Steckbrief (Leopard) verriet den Ausgang des Vorgängers."""
    text = prompt("Leopard", "Jo Nesbø", None, load_vocabulary())

    assert "Keine Spoiler" in text
    assert "früheren Bänden" in text


# --- Erzählmuster (#49) -------------------------------------------------------


def test_story_patterns_are_in_the_vocabulary_under_their_master_plot() -> None:
    vocabulary = load_vocabulary()

    assert vocabulary.is_pattern("dark_lord") and not vocabulary.is_pattern("gritty")
    assert vocabulary.family_of("dark_lord").name == "Heldenreise"
    # Die Grundhandlung ist selbst ein Wort und ihre eigene Familie.
    assert vocabulary.family_of("quest").id == "quest"
    assert len([f for f in vocabulary.families if vocabulary.is_pattern(f.members[0])]) == 20


def test_the_master_plots_bind_lotr_and_otherland_and_the_genre_pattern_parts_them() -> None:
    """Beide sind eine Heldenreise; nur *Herr der Ringe* hat einen dunklen
    Herrscher. Genau diese Trennung verlangte das Gegengewicht (#44)."""
    from ebook_watchlist.facets import families_of

    vocabulary = load_vocabulary()
    lord_of_the_rings = Portrait(known=True, fingerprint="x", traits=(
        Trait("dark_lord", "Sauron sammelt seine Heere.", "wissen"),
        Trait("world_building", "Mittelerde hat Sprachen und Geschichte.", "wissen"),
    ))
    otherland = Portrait(known=True, fingerprint="x", traits=(
        Trait("quest", "Eine Gruppe sucht den Grund für die Komas der Kinder.", "wissen"),
        Trait("inside_the_game", "Das Netz ist eine Welt aus Welten.", "wissen"),
    ))

    shared = families_of(lord_of_the_rings, vocabulary) & families_of(otherland, vocabulary)
    assert "quest" in shared
    assert "dark_lord" in {t.term for t in lord_of_the_rings.traits}
    assert "dark_lord" not in {t.term for t in otherland.traits}


def test_the_prompt_lists_patterns_under_their_master_plot() -> None:
    text = prompt("Leopard", "Jo Nesbø", None, load_vocabulary())

    assert "  quest: Heldenreise" in text
    assert "    dark_lord: der dunkle Herrscher" in text
    assert '"erzaehlmuster"' in text


def test_patterns_are_counted_apart_from_the_terms() -> None:
    """Fünf Merkmale und ein Muster sind regelgerecht; ohne Muster nicht."""
    vocabulary = load_vocabulary()

    assert parse_answer(answer(), vocabulary).violations == ()
    assert "0 Erzählmuster statt eins bis drei" in parse_answer(
        answer(erzaehlmuster=[]), vocabulary
    ).violations


def test_a_pattern_in_the_wrong_list_is_kept_and_named() -> None:
    vocabulary = load_vocabulary()
    terms = LEOPARD["merkmale"] + [{"id": "dark_lord", "satz": "x", "beleg": "wissen"}]

    portrait = parse_answer(answer(merkmale=terms), vocabulary)

    assert "dark_lord" in {t.term for t in portrait.traits}
    assert "in der falschen Liste: dark_lord" in portrait.violations


def test_a_pattern_file_that_names_no_master_plot_is_refused(tmp_path) -> None:
    file = tmp_path / "muster.yaml"
    file.write_text(
        "familien: []\nmuster:\n  - id: x\n    name: x\n    familie: gibtsnicht\n",
        encoding="utf-8",
    )

    with pytest.raises(VocabularyError, match="Grundhandlung"):
        load_vocabulary(patterns=file)


def test_a_pattern_may_not_reuse_a_term_id(tmp_path) -> None:
    file = tmp_path / "muster.yaml"
    file.write_text("familien:\n  - id: gritty\n    name: x\n", encoding="utf-8")

    with pytest.raises(VocabularyError, match="zweimal"):
        load_vocabulary(patterns=file)


def test_the_vocabulary_is_parsed_once_while_the_files_stay_the_same() -> None:
    """Gebraucht wird es bei jedem Eintrag und jedem Buch im Regal (Review)."""
    assert load_vocabulary() is load_vocabulary()


def test_a_changed_file_is_parsed_again(tmp_path: Path) -> None:
    file = _vocabulary(tmp_path, "[{id: fast, name: rasant, beschreibung: a}]")
    before = load_vocabulary(file)
    file.write_text(file.read_text(encoding="utf-8").replace("rasant", "flott"),
                     encoding="utf-8")

    assert load_vocabulary(file).terms["fast"].name == "flott"
    assert before.terms["fast"].name == "rasant"


def test_the_fingerprint_is_computed_once_per_vocabulary(monkeypatch) -> None:
    vocabulary = load_vocabulary()
    fingerprint(vocabulary)
    monkeypatch.setattr(type(vocabulary), "prompt_text", lambda self: pytest.fail("neu gerechnet"))

    assert fingerprint(vocabulary) == fingerprint(load_vocabulary())


# --- mehrere Bücher in einem Aufruf (#66) --------------------------------------


def test_a_batch_prompt_carries_the_vocabulary_once_and_every_book_numbered() -> None:
    vocabulary = load_vocabulary()

    text = prompt_many(
        [("Leopard", "Jo Nesbø", "Harry Hole."), ("Ein Titel", None, None)], vocabulary
    )

    assert text.count("--- VOKABULAR ---") == 1 and text.count(vocabulary.prompt_text()) == 1
    assert "--- BUCH 1 ---" in text and "--- BUCH 2 ---" in text
    assert "Klappentext: Harry Hole." in text and "(nicht angegeben)" in text
    assert "Es sind 2 Bücher" in text and '"bekannt": true' in text


def test_a_batch_costs_far_less_than_the_same_books_one_by_one() -> None:
    """Vokabular und Regeln gehen einmal raus statt je Buch (gemessen: rund 5500
    der rund 6500 Tokens eines Prompts)."""
    vocabulary = load_vocabulary()
    books = [(f"Titel {i}", "Wer", "Ein Klappentext.") for i in range(8)]

    batched = len(prompt_many(books, vocabulary))
    single = sum(len(prompt(t, a, b, vocabulary)) for t, a, b in books)

    assert batched < single / 5


def test_a_batch_prompt_does_not_change_the_fingerprint() -> None:
    """Ein im Bündel angelegter Steckbrief gilt wie ein einzeln angelegter."""
    vocabulary = load_vocabulary()

    prompt_many([("A", None, None)], vocabulary)

    assert fingerprint(vocabulary) == fingerprint(load_vocabulary())


# --- „unbekannt" ohne Text ist keine endgültige Antwort ---------------------------


class _Channel:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    def ask(self, text: str, max_tokens: int = 300) -> str:
        return self.answer


def test_a_portrait_notes_whether_a_text_went_along() -> None:
    """Ein „unbekannt“ ohne Text sagt etwas über den fehlenden Text, nicht über das
    Buch — das muss der Steckbrief festhalten, sonst bleibt es für immer."""
    portrayer = Portrayer(_Channel(json.dumps({"bekannt": False})), load_vocabulary())

    assert portrayer.portray("Auris", "Vincent Kliesch", None).with_text is False
    assert portrayer.portray("Auris", "Vincent Kliesch", "Ein Klappentext.").with_text is True


def test_a_batch_notes_it_per_book() -> None:
    from datetime import datetime as _dt

    from ebook_watchlist.models import MatchReason, Observation

    def find(item: str, blurb: str | None) -> Observation:
        return Observation(source="beam", source_item_id=item, title=f"Fund {item}",
                           match_reason=MatchReason.GENRE_CATEGORY, blurb=blurb,
                           observed_at=_dt(2026, 9, 25))

    answer = json.dumps({"1": {"bekannt": False}, "2": {"bekannt": False}})
    portrayer = Portrayer(_Channel(answer), load_vocabulary())

    described = portrayer.portray_finds([find("a", "Mit Text."), find("b", None)])

    assert described[("beam", "a")].with_text is True
    assert described[("beam", "b")].with_text is False


def test_the_note_is_kept_with_the_portrait(store: Store) -> None:
    vocabulary = load_vocabulary()
    portrait = Portrait(known=False, fingerprint=fingerprint(vocabulary), with_text=False)

    store.put_portrait("book:1", portrait, now=NOW)

    assert store.portrait("book:1", portrait.fingerprint).with_text is False


def test_only_an_unknown_book_described_without_text_is_asked_again_when_a_text_appears() -> None:
    from ebook_watchlist.portrait import worth_asking_again

    known = Portrait(known=True, fingerprint="x", with_text=False)
    unknown_with = Portrait(known=False, fingerprint="x", with_text=True)
    unknown_without = Portrait(known=False, fingerprint="x", with_text=False)
    unknown_old = Portrait(known=False, fingerprint="x")  # Zeile aus der Zeit davor

    assert not worth_asking_again(known, text_now=True)
    assert not worth_asking_again(unknown_with, text_now=True)
    assert not worth_asking_again(unknown_without, text_now=False)
    assert worth_asking_again(unknown_without, text_now=True)
    assert worth_asking_again(unknown_old, text_now=True)


def test_a_batch_answer_becomes_one_portrait_per_number() -> None:
    vocabulary = load_vocabulary()
    answer = json.dumps({"1": LEOPARD, "2": {"bekannt": False}})

    portraits = parse_many(answer, vocabulary, 2)

    assert portraits[1].known and portraits[1].original_title == "Panserhjerte"
    assert not portraits[2].known


def test_one_crooked_entry_costs_one_book_not_the_batch() -> None:
    vocabulary = load_vocabulary()
    answer = json.dumps({"1": LEOPARD, "2": "kaputt", "3": {"bekannt": False}})

    portraits = parse_many(answer, vocabulary, 3)

    assert sorted(portraits) == [1, 3]


def test_a_book_the_answer_skips_is_simply_missing() -> None:
    portraits = parse_many(json.dumps({"1": LEOPARD}), load_vocabulary(), 3)

    assert sorted(portraits) == [1]


def test_an_answer_without_json_fails_the_batch_but_raises_cleanly() -> None:
    with pytest.raises(PortrayalUnavailable):
        parse_many("Dazu kann ich nichts sagen.", load_vocabulary(), 2)


def test_an_unknown_book_is_asked_again_once_a_sample_is_there() -> None:
    """Unbekannt trotz Text: einmal noch mit der Leseprobe, nie wieder danach (#76)."""
    from ebook_watchlist.portrait import Portrait, worth_asking_again

    with_text = Portrait(known=False, fingerprint="x", with_text=True)
    with_sample = Portrait(known=False, fingerprint="x", with_text=True, with_sample=True)

    assert worth_asking_again(with_text, text_now=True, sample_now=True)
    assert not worth_asking_again(with_text, text_now=True, sample_now=False)
    assert not worth_asking_again(with_sample, text_now=True, sample_now=True)
