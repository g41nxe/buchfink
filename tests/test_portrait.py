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

from ebook_watchlist.portrait import (
    Portrait,
    Trait,
    VocabularyError,
    fingerprint,
    load_vocabulary,
    parse_answer,
    portray,
    prompt,
)
from ebook_watchlist.rating import RatingUnavailable
from ebook_watchlist.store import Store

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
         "beleg": "wissen"},
        {"id": "violent", "satz": "Der Leopoldsapfel wird genau ausgemalt.", "beleg": "wissen"},
        {"id": "flawed", "satz": "Er greift bei jedem Rückschlag zur Flasche.", "beleg": "wissen"},
        {"id": "intricate", "satz": "Mehrere Opfer, deren Verbindung sich spät zeigt.",
         "beleg": "wissen"},
        {"id": "intensifying", "satz": "Nach der Rückkehr nach Oslo zieht es an.",
         "beleg": "wissen"},
    ],
}


def antwort(**anders) -> str:
    return json.dumps({**LEOPARD, **anders}, ensure_ascii=False)


# --- das Vokabular ----------------------------------------------------------


def test_the_vocabulary_is_the_one_in_the_repository() -> None:
    wort = load_vocabulary()

    assert len(wort.terms) == 72
    assert wort.terms["gritty"].name == "schonungslos"
    assert wort.terms["gritty"].dimension == "Stil"


def test_a_term_knows_its_family() -> None:
    """Drei Begriffe, die NoveList trennt und die Leserin nicht unterscheidet."""
    wort = load_vocabulary()

    assert {wort.family_of(t).name for t in ("violent", "disturbing", "gritty")} == {"hart"}


def test_a_term_outside_every_family_is_its_own() -> None:
    wort = load_vocabulary()

    familie = wort.family_of("leisurely")

    assert familie.name == "gemächlich"
    assert familie.members == ("leisurely",)


def _vokabular(tmp_path: Path, merkmale: str, familien: str = "[]") -> Path:
    datei = tmp_path / "merkmale.yaml"
    datei.write_text(
        "dimensionen:\n"
        "  - id: pace\n    name: Tempo\n    frage: wie es vorangeht\n"
        f"    merkmale: {merkmale}\n"
        f"familien: {familien}\n",
        encoding="utf-8",
    )
    return datei


def test_a_duplicate_id_is_refused(tmp_path: Path) -> None:
    datei = _vokabular(
        tmp_path,
        "[{id: fast, name: rasant, beschreibung: a}, {id: fast, name: schnell, beschreibung: b}]",
    )

    with pytest.raises(VocabularyError, match="fast"):
        load_vocabulary(datei)


def test_a_family_may_only_name_terms_that_exist(tmp_path: Path) -> None:
    datei = _vokabular(
        tmp_path,
        "[{id: fast, name: rasant, beschreibung: a}]",
        "[{id: quick, name: flott, merkmale: [fast, gibtsnicht]}]",
    )

    with pytest.raises(VocabularyError, match="gibtsnicht"):
        load_vocabulary(datei)


def test_a_term_belongs_to_one_family_only(tmp_path: Path) -> None:
    datei = _vokabular(
        tmp_path,
        "[{id: fast, name: rasant, beschreibung: a}, {id: slow, name: langsam, beschreibung: b}]",
        "[{id: a, name: A, merkmale: [fast, slow]}, {id: b, name: B, merkmale: [fast]}]",
    )

    with pytest.raises(VocabularyError, match="fast"):
        load_vocabulary(datei)


# --- die Anweisung ----------------------------------------------------------


def test_the_prompt_carries_the_book_and_every_term() -> None:
    wort = load_vocabulary()

    text = prompt("Leopard", "Jo Nesbø", None, wort)

    assert "Titel: Leopard" in text and "Autor: Jo Nesbø" in text
    assert "Klappentext" not in text.split("--- BUCH ---")[1]
    assert all(term_id in text for term_id in wort.terms)


def test_a_blurb_goes_along_when_there_is_one() -> None:
    text = prompt("Leopard", "Jo Nesbø", "Harry Hole kehrt zurück.", load_vocabulary())

    assert "Klappentext: Harry Hole kehrt zurück." in text


def test_the_fingerprint_follows_the_terms_not_the_families(tmp_path: Path) -> None:
    """Die Familien sind ein Arbeitsstand; sie zu ändern darf kein Buch neu
    fragen lassen. Ein geänderter Begriff dagegen schon."""
    merkmale = (
        "[{id: fast, name: rasant, beschreibung: a}, "
        "{id: slow, name: langsam, beschreibung: b}]"
    )
    ohne = load_vocabulary(_vokabular(tmp_path, merkmale))
    mit = load_vocabulary(
        _vokabular(tmp_path, merkmale, "[{id: t, name: Tempo, merkmale: [fast, slow]}]")
    )
    geaendert = merkmale.replace("beschreibung: a", "beschreibung: x")
    anders = load_vocabulary(_vokabular(tmp_path, geaendert))

    assert fingerprint(ohne) == fingerprint(mit)
    assert fingerprint(ohne) != fingerprint(anders)


# --- die Antwort ------------------------------------------------------------


def test_a_good_answer_becomes_a_portrait() -> None:
    wort = load_vocabulary()

    bild = parse_answer(antwort(), wort)

    assert bild.known
    assert bild.original_title == "Panserhjerte"
    assert (bild.genre, bild.subgenre) == ("Kriminalroman", "Nordic Noir")
    assert [t.term for t in bild.traits] == ["brooding", "violent", "flawed", "intricate",
                                            "intensifying"]
    assert bild.traits[0] == Trait("brooding", "Harry Hole wird aus einer Opiumhöhle "
                                               "zurückgeholt.", "wissen")
    assert bild.violations == ()
    assert bild.fingerprint == fingerprint(wort)


def test_the_rules_are_checked_and_kept_not_hidden() -> None:
    """Ein Verstoß verwirft den Steckbrief nicht; er steht daneben."""
    wort = load_vocabulary()
    zu_wenig = LEOPARD["merkmale"][:3]

    bild = parse_answer(antwort(merkmale=zu_wenig), wort)

    assert any("drei" in v or "3" in v for v in bild.violations)
    assert len(bild.traits) == 3


def test_a_term_outside_the_vocabulary_is_dropped_and_named() -> None:
    wort = load_vocabulary()
    erfunden = [*LEOPARD["merkmale"], {"id": "episch-wuchtig", "satz": "x", "beleg": "wissen"}]

    bild = parse_answer(antwort(merkmale=erfunden), wort)

    assert "episch-wuchtig" not in [t.term for t in bild.traits]
    assert any("episch-wuchtig" in v for v in bild.violations)


def test_too_many_from_one_dimension_is_a_violation() -> None:
    wort = load_vocabulary()
    stimmung = [{"id": t, "satz": "x", "beleg": "wissen"}
                for t in ("bleak", "moody", "menacing", "disturbing")]
    dazu = [{"id": "brooding", "satz": "x", "beleg": "wissen"},
            {"id": "gritty", "satz": "x", "beleg": "wissen"}]

    bild = parse_answer(antwort(merkmale=stimmung + dazu), wort)

    assert any("Stimmung" in v for v in bild.violations)


def test_an_unknown_evidence_is_a_violation() -> None:
    wort = load_vocabulary()
    merkmale = [{**m, "beleg": "vermutung"} if i == 0 else m
                for i, m in enumerate(LEOPARD["merkmale"])]

    bild = parse_answer(antwort(merkmale=merkmale), wort)

    assert any("vermutung" in v for v in bild.violations)


def test_a_pitch_that_is_too_long_is_a_violation() -> None:
    bild = parse_answer(antwort(pitch="x" * 400), load_vocabulary())

    assert any("Pitch" in v for v in bild.violations)


def test_a_book_the_model_does_not_know_has_no_traits() -> None:
    """Die Probe für „nichts erfinden": ein erfundener Titel."""
    bild = parse_answer(json.dumps({"bekannt": False}), load_vocabulary())

    assert not bild.known
    assert bild.traits == ()
    assert bild.violations == ()


def test_unknown_but_with_traits_is_a_violation() -> None:
    bild = parse_answer(antwort(bekannt=False), load_vocabulary())

    assert any("unbekannt" in v for v in bild.violations)


def test_no_json_is_no_portrait() -> None:
    with pytest.raises(RatingUnavailable):
        parse_answer("Dazu kann ich nichts sagen.", load_vocabulary())


# --- ein Aufruf -------------------------------------------------------------


def test_portray_asks_once_and_reads_the_answer() -> None:
    gefragt: list[str] = []

    def ask(text: str, max_tokens: int) -> str:
        gefragt.append(text)
        return antwort()

    bild = portray("Leopard", "Jo Nesbø", None, ask, load_vocabulary())

    assert len(gefragt) == 1 and "Titel: Leopard" in gefragt[0]
    assert bild.known and len(bild.traits) == 5


# --- gespeichert -------------------------------------------------------------


def test_a_portrait_is_kept_per_subject_and_fingerprint(store: Store) -> None:
    wort = load_vocabulary()
    bild = parse_answer(antwort(), wort)

    store.put_portrait("isbn:9783548289441", bild, now=NOW)

    wieder = store.portrait("isbn:9783548289441", bild.fingerprint)
    assert wieder == bild
    assert store.portrait("isbn:9783548289441", "anderer-abdruck") is None
    assert store.portrait("isbn:0000000000000", bild.fingerprint) is None


def test_the_latest_portrait_wins(store: Store) -> None:
    """Append-only (ADR 5): ein zweiter Steckbrief ersetzt nichts, er kommt dazu."""
    wort = load_vocabulary()
    alt = parse_answer(antwort(pitch="Alt."), wort)
    neu = parse_answer(antwort(pitch="Neu."), wort)

    store.put_portrait("book:7", alt, now=NOW)
    store.put_portrait("book:7", neu, now=NOW.replace(hour=11))

    assert store.portrait("book:7", neu.fingerprint).pitch == "Neu."


def test_an_unknown_book_is_kept_too(store: Store) -> None:
    """Sonst würde jede Seite dasselbe unbekannte Buch erneut fragen."""
    bild = parse_answer(json.dumps({"bekannt": False}), load_vocabulary())

    store.put_portrait("book:9", bild, now=NOW)

    assert store.portrait("book:9", bild.fingerprint) == Portrait(
        known=False, fingerprint=bild.fingerprint
    )


def test_known_must_be_a_real_yes() -> None:
    """„false" als Text ist kein Ja."""
    bild = parse_answer(antwort(bekannt="false"), load_vocabulary())

    assert not bild.known


def test_the_instruction_forbids_spoilers_for_sentences_pitch_and_series() -> None:
    """Die Sätze stehen auf der Buchseite, bevor die Leserin das Buch liest.
    Der erste echte Steckbrief (Leopard) verriet den Ausgang des Vorgängers."""
    text = prompt("Leopard", "Jo Nesbø", None, load_vocabulary())

    assert "Keine Spoiler" in text
    assert "früheren Bänden" in text
