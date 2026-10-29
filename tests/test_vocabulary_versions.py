"""Zwei Fassungen des Vokabulars, zwischen denen sich hin und her schalten lässt (#59).

Eine neue Fassung nennt je Eintrag, welche alten Ids er ersetzt (``ersetzt``).
Gespeichert wird immer in den alten Ids, gelesen in denen der aktiven Fassung:
so gilt dasselbe Leseprofil unter beiden, und zurückschalten verliert nichts
(29.10.2026).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ebook_watchlist.judging import portrait, reader_reasons
from ebook_watchlist.judging.facets import Counterweight, Facet, Liked, ReadingProfile
from ebook_watchlist.judging.portrait import VocabularyError, load_vocabulary
from ebook_watchlist.store import Store

NOW = datetime(2026, 10, 29, 20, 0)
SLUG = "test"

OLD = """\
dimensionen:
  - name: Ton
    frage: wie es klingt
    merkmale:
      - id: bleak
        name: düster
      - id: gloomy
        name: trübe
      - id: cosy
        name: behaglich
"""

NEW = """\
dimensionen:
  - name: Ton
    frage: wie es klingt
    merkmale:
      - id: grim
        name: finster
        ersetzt: [bleak, gloomy]
      - id: cosy
        name: behaglich
"""


def use(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str, name: str) -> None:
    """Diese Fassung gilt jetzt — wie ``EBW_VOCABULARY_DIR`` für den Dienst."""
    file = tmp_path / f"{name}.yaml"
    file.write_text(text, encoding="utf-8")
    monkeypatch.setattr(portrait, "VOCABULARY_PATH", file)
    monkeypatch.setattr(portrait, "PATTERNS_PATH", tmp_path / "keine-muster.yaml")


def test_a_new_term_knows_which_old_ids_it_replaces(tmp_path: Path) -> None:
    file = tmp_path / "neu.yaml"
    file.write_text(NEW, encoding="utf-8")

    vocabulary = load_vocabulary(file, tmp_path / "keine-muster.yaml")

    assert vocabulary.current("bleak") == "grim"
    assert vocabulary.current("gloomy") == "grim"
    assert vocabulary.current("cosy") == "cosy"
    # Zurück auf die erste der ersetzten: ein zusammengelegtes Paar kommt
    # alt auf einer der beiden an.
    assert vocabulary.stored("grim") == "bleak"
    assert vocabulary.stored("cosy") == "cosy"


def test_an_old_id_replaced_twice_is_an_error(tmp_path: Path) -> None:
    file = tmp_path / "doppelt.yaml"
    file.write_text(NEW.replace("      - id: cosy\n        name: behaglich\n",
                                "      - id: cosy\n        name: behaglich\n"
                                "        ersetzt: [bleak]\n"), encoding="utf-8")

    with pytest.raises(VocabularyError):
        load_vocabulary(file, tmp_path / "keine-muster.yaml")


def test_the_reading_profile_is_stored_old_and_read_in_the_active_version(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, tmp_path, NEW, "neu")
    store.put_reading_profile(SLUG, ReadingProfile(
        facets=(Facet(("grim", "cosy"), ("Ein Buch",)),),
        counterweights=(Counterweight(("grim",), None, ()),),
        liked=(Liked("grim", True), Liked("cosy", False)),
    ), cause="test", now=NOW)

    under_new = store.reading_profile(SLUG)
    use(monkeypatch, tmp_path, OLD, "alt")
    under_old = store.reading_profile(SLUG)

    assert under_new is not None and under_old is not None
    assert [g.family for g in under_new.liked] == ["grim", "cosy"]
    assert [g.family for g in under_old.liked] == ["bleak", "cosy"]
    assert under_old.facets[0].families == ("bleak", "cosy")
    assert under_old.counterweights[0].families == ("bleak",)


def test_an_old_profile_reads_in_the_new_version_without_doubles(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zwei alte, die eins werden, stehen danach einmal da."""
    use(monkeypatch, tmp_path, OLD, "alt")
    store.put_reading_profile(SLUG, ReadingProfile(
        facets=(), counterweights=(),
        liked=(Liked("bleak", False), Liked("gloomy", True), Liked("cosy", False)),
    ), cause="test", now=NOW)

    use(monkeypatch, tmp_path, NEW, "neu")
    profile = store.reading_profile(SLUG)

    assert profile is not None
    assert [(g.family, g.boosted) for g in profile.liked] == [("grim", True), ("cosy", False)]


def test_an_intake_choice_is_stored_old(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, tmp_path, NEW, "neu")
    store.set_intake_choice(SLUG, "loved", "grim")

    assert [c.family_id for c in store.intake_choices(SLUG)] == ["grim"]
    use(monkeypatch, tmp_path, OLD, "alt")
    assert [c.family_id for c in store.intake_choices(SLUG)] == ["bleak"]


def test_reasons_at_a_book_are_stored_old(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = store.find_or_create_book(isbn="9783000000999", title="Ein Buch",
                                     author="Wer Auch Immer", now=NOW)
    store.put_relation(SLUG, book.id, "liked", now=NOW)
    use(monkeypatch, tmp_path, NEW, "neu")
    reader_reasons.keep(store, SLUG, book.id, "liked", {}, {"add": ["grim"]}, now=NOW)

    assert reader_reasons.of(store, SLUG, book.id, "liked")[1] == {"add": ["grim"]}
    use(monkeypatch, tmp_path, OLD, "alt")
    assert reader_reasons.of(store, SLUG, book.id, "liked")[1] == {"add": ["bleak"]}


def test_a_replacing_family_wears_the_picture_and_sign_of_the_one_it_replaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bilder und Zeichen liegen unter den alten Ids; eine neue Fassung muss
    nicht 64 Motive neu haben, um gleich auszusehen."""
    from ebook_watchlist.web import family_art

    signs, pictures = tmp_path / "zeichen", tmp_path / "bilder"
    signs.mkdir()
    pictures.mkdir()
    (signs / "bleak.svg").write_text('<path d="M1 1h2"/>', encoding="utf-8")
    (pictures / "bleak.jpg").write_bytes(b"jpg")
    monkeypatch.setattr(family_art, "SIGNS_DIR", signs)
    monkeypatch.setattr(family_art, "PICTURES_DIR", pictures)
    use(monkeypatch, tmp_path, NEW, "neu")

    art = family_art.load()

    assert 'href="#fz-bleak"' in art.sign("grim")
    assert art.picture("grim") == f"{family_art.PICTURES_URL}/bleak.jpg"
    assert art.sign("cosy") == ""
