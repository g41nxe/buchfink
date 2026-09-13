"""Vier YAML-Dateien werden vier Begriffe: Profil, Buch, Beziehung, Interesse.

Alle Beispiele stammen aus der echten Konfiguration.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ebook_watchlist.config import OwnedBook, Profile, WatchlistEntry
from ebook_watchlist.ratings import BY_CONVERSATION, BY_READER, book_subject
from ebook_watchlist.relations import (
    ConfigurationError,
    InterestKey,
    RelationKind,
    check_details,
    check_interest_key,
    check_relation_kind,
)
from ebook_watchlist.seed import OWNED_PROFILE_VERSION, seed, split_free_text
from ebook_watchlist.store import Store

NOW = datetime(2026, 9, 4, 20, 0)


def profile(**overrides) -> Profile:
    return Profile(slug="t", name="Test", **overrides)


# --- Freitext ---------------------------------------------------------------


def test_the_usual_shape_splits_cleanly() -> None:
    assert split_free_text("Cry Baby - Gillian Flynn") == ("Cry Baby", "Gillian Flynn", None)


def test_a_trailing_parenthesis_is_a_reason_not_part_of_the_name() -> None:
    """Ohne diese Regel hiess die Autorin "Frank Schätzing (Grund: …)" und jeder
    spätere Vergleich hätte dagegen gematcht."""
    title, author, note = split_free_text(
        "Der Schwarm - Frank Schätzing (Grund: langsames Erzähltempo, Achse E)"
    )
    assert (title, author) == ("Der Schwarm", "Frank Schätzing")
    assert note == "Grund: langsames Erzähltempo, Achse E"


def test_a_hyphenated_title_survives() -> None:
    assert split_free_text("Das Rosie-Projekt - Graeme Simsion") == (
        "Das Rosie-Projekt",
        "Graeme Simsion",
        None,
    )


def test_text_that_names_nobody_names_nobody() -> None:
    """Einen Namen zu raten, wo keiner steht, ist genau die stille Erfindung,
    die dieses Werkzeug vermeidet."""
    assert split_free_text("Irgendein Buch") == ("Irgendein Buch", None, None)


# --- das Vokabular ----------------------------------------------------------


def test_an_unknown_relation_fails_loudly() -> None:
    with pytest.raises(ConfigurationError, match="unbekannte Beziehung"):
        check_relation_kind("besitze")


def test_an_unknown_interest_fails_loudly() -> None:
    """Ein Interesse unter 'autor' statt 'author' würde nie abgefragt — und
    nichts würde das sagen."""
    with pytest.raises(ConfigurationError, match="unbekanntes Interesse"):
        check_interest_key("autor")


def test_a_misspelled_tier_fails_loudly() -> None:
    """'extendet' hätte eine wöchentliche Autor:in still in die tägliche Liste
    befördert — ein Fehler, der sich nur durch verändertes Verhalten zeigt."""
    with pytest.raises(ConfigurationError, match="unbekannte Stufe"):
        check_details("author", {"tier": "extendet"})


def test_an_unknown_detail_fails_loudly() -> None:
    with pytest.raises(ConfigurationError, match="unbekannte Angaben"):
        check_details("author", {"activ": False})


def test_the_known_details_pass() -> None:
    assert check_details("author", {"tier": "extended", "sources": ["beam"], "note": "x"})


# --- der Import -------------------------------------------------------------


def test_the_watchlist_becomes_books_and_relations(store: Store) -> None:
    report = seed(
        store,
        profile(),
        [WatchlistEntry(title="Blindflug", author="Peter Watts")],
        now=NOW,
    )
    assert report.books == 1
    book = store.books()[0]
    assert (book.title, book.author) == ("Blindflug", "Peter Watts")

    relations = store.relations("t", kind=str(RelationKind.WATCHING))
    assert [row.book_id for row in relations] == [book.id]


def test_several_relations_hold_at_once(store: Store) -> None:
    """Cold Eternity ist owned *und* war watching. Eine Statusspalte hätte das
    nicht ausdrücken können."""
    seed(
        store,
        profile(liked_books=["Cold Eternity - S.A. Barnes"]),
        [WatchlistEntry(title="Cold Eternity", author="S.A. Barnes")],
        now=NOW,
    )
    book = store.books()[0]
    kinds = {row.kind for row in store.relations_of("t", book.id)}
    assert kinds == {str(RelationKind.WATCHING), str(RelationKind.LIKED)}


def test_a_relation_is_deactivated_not_deleted(store: Store) -> None:
    """Providence von der Watchlist zu nehmen zerstörte bisher die Tatsache,
    dass es je beobachtet wurde."""
    seed(store, profile(), [WatchlistEntry(title="Providence", author="Max Barry")], now=NOW)
    book = store.books()[0]

    store.deactivate_relation("t", book.id, str(RelationKind.WATCHING), now=NOW)

    assert store.relations("t", kind=str(RelationKind.WATCHING)) == []
    kept = store.relations_of("t", book.id)
    assert [row.active for row in kept] == [False]


def test_authors_and_themes_become_interests(store: Store) -> None:
    report = seed(
        store,
        profile(
            reference_authors=["Chris Carter"],
            extended_authors=["Dave Eggers"],
            genre_categories=["belletristik/krimi-thriller/psychothriller"],
        ),
        [],
        now=NOW,
    )
    assert report.interests == 3

    authors = store.interests("t", key=str(InterestKey.AUTHOR))
    assert {row.value for row in authors} == {"Chris Carter", "Dave Eggers"}
    tiers = {row.value: row.details for row in authors}
    assert '"tier": "core"' in tiers["Chris Carter"]
    assert '"tier": "extended"' in tiers["Dave Eggers"]


def test_an_author_on_both_lists_is_swept_daily_not_twice(store: Store) -> None:
    report = seed(
        store,
        profile(reference_authors=["Chris Carter"], extended_authors=["Chris Carter"]),
        [],
        now=NOW,
    )
    assert report.interests == 1


def test_importing_twice_changes_nothing(store: Store) -> None:
    """Der Import ist wiederholbar — sonst wäre er einmalig und damit ein Risiko."""
    args = (
        profile(reference_authors=["Chris Carter"], liked_books=["Cry Baby - Gillian Flynn"]),
        [WatchlistEntry(title="Blindflug", author="Peter Watts")],
    )
    seed(store, *args, now=NOW)
    first = (len(store.books()), len(store.relations("t")), len(store.interests("t")))

    seed(store, *args, now=NOW)
    assert (len(store.books()), len(store.relations("t")), len(store.interests("t"))) == first


def test_a_second_import_does_not_revive_what_was_switched_off(store: Store) -> None:
    args = (profile(), [WatchlistEntry(title="Providence", author="Max Barry", active=False)])
    seed(store, *args, now=NOW)
    assert store.relations("t", kind=str(RelationKind.WATCHING)) == []


def test_a_second_import_keeps_what_the_reader_paused(store: Store) -> None:
    """Der Modulkopf verspricht es, ``put_relation`` hielt es nicht: es setzt
    ``active`` auch an einer bestehenden Zeile. Ein Eintrag, den die Leserin in
    der Oberfläche pausiert hatte, lief nach ``ebw seed`` wieder."""
    args = (profile(), [WatchlistEntry(title="Providence", author="Max Barry")])
    seed(store, *args, now=NOW)
    book = store.books()[0]
    store.deactivate_relation("t", book.id, str(RelationKind.WATCHING), now=NOW)

    seed(store, *args, now=NOW)

    assert store.relations("t", kind=str(RelationKind.WATCHING)) == []


def test_a_second_import_keeps_a_lifted_restriction_lifted(store: Store) -> None:
    """Dieselbe Lücke an den Angaben: ``put_relation`` überschrieb sie, und die
    Einschränkung, die die Leserin auf der Buchseite aufgehoben hatte, war
    wieder da."""
    args = (
        profile(),
        [WatchlistEntry(title="Providence", author="Max Barry", check_shop=False)],
    )
    seed(store, *args, now=NOW)
    book = store.books()[0]
    store.set_relation_details("t", book.id, str(RelationKind.WATCHING), {}, now=NOW)

    seed(store, *args, now=NOW)

    relation = store.relations("t", kind=str(RelationKind.WATCHING))[0]
    assert "restrict" not in (relation.details or "")


# --- die Aussaat, pro Interesse --------------------------------------------


def test_each_interest_is_seeded_on_its_own(store: Store) -> None:
    """Der behobene Fehler: der alte Schlüssel liess 'category' bei Autor:innen
    leer, so dass alle Autor:innen sich eine Aussaat teilten — die erste säte
    still an, jede weitere meldete ihre ganze Backlist."""
    seed(store, profile(reference_authors=["Chris Carter", "Jo Nesbø"]), [], now=NOW)
    carter, nesbo = store.interests("t", key=str(InterestKey.AUTHOR))

    store.mark_interest_seeded(carter.id, "beam", now=NOW)

    assert store.is_interest_seeded(carter.id, "beam") is True
    assert store.is_interest_seeded(nesbo.id, "beam") is False


def test_seeding_is_per_source(store: Store) -> None:
    seed(store, profile(reference_authors=["Chris Carter"]), [], now=NOW)
    carter = store.interests("t")[0]

    store.mark_interest_seeded(carter.id, "beam", now=NOW)

    assert store.is_interest_seeded(carter.id, "onleihe") is False


# --- was der Review gefunden hat -------------------------------------------


def test_a_volume_marker_is_not_an_author() -> None:
    """Der Ausdruck teilt an der letzten Trennung, und ein angehängter
    Bandzusatz sieht von hinten aus wie ein Name. Ohne die Ziffernsperre wäre
    ein Buch der Autorin "Band 1" entstanden."""
    title, author, _ = split_free_text("Achtsam morden - Karsten Dusse - Band 1")
    assert author is None
    assert title.startswith("Achtsam morden")


def test_a_hyphenated_author_is_not_guessed_at() -> None:
    """Jean-Luc Bannalec fällt durch — und das ist die richtige Richtung:
    lieber auf die Liste als falsch aufgelöst (ADR 8)."""
    _, author, _ = split_free_text("Bretonische Verhältnisse - Jean-Luc Bannalec")
    assert author is None


def test_a_restriction_names_the_kind_of_source_not_its_name(store: Store) -> None:
    """"onleihe" und "beam" hart einzutragen wäre bei jeder umbenannten Quelle
    falsch gewesen. Wie eine Quelle heißt, sagt die Konfiguration."""
    seed(
        store,
        profile(),
        [WatchlistEntry(title="Providence", author="Max Barry", check_shop=False)],
        now=NOW,
    )
    relation = store.relations("t", kind=str(RelationKind.WATCHING))[0]
    assert '"restrict": "library"' in relation.details
    assert "onleihe" not in relation.details


def test_relation_details_are_validated_too(store: Store) -> None:
    """Geprüft wurden bisher nur die Interessen — Beziehungen kamen ungeprüft
    durch, obwohl das Ticket beides verlangt."""
    book = store.find_or_create_book(isbn=None, title="Irgendwas", now=NOW)
    with pytest.raises(ConfigurationError, match="unbekannte Angaben"):
        store.put_relation("t", book.id, str(RelationKind.OWNED), now=NOW, activ=False)


def test_an_unknown_restriction_fails_loudly(store: Store) -> None:
    book = store.find_or_create_book(isbn=None, title="Irgendwas", now=NOW)
    with pytest.raises(ConfigurationError, match="unbekannte Einschraenkung"):
        store.put_relation("t", book.id, str(RelationKind.WATCHING), now=NOW, restrict="beam")


def test_deactivating_takes_the_clock_rather_than_reading_it(store: Store) -> None:
    """Ein Store, der selbst nach der Zeit sieht, lässt sich nicht mit einer
    festen Uhr prüfen."""
    book = store.find_or_create_book(isbn=None, title="Providence", now=NOW)
    store.put_relation("t", book.id, str(RelationKind.WATCHING), now=NOW)

    store.deactivate_relation("t", book.id, str(RelationKind.WATCHING), now=NOW)

    assert store.relations("t", kind=str(RelationKind.WATCHING)) == []


# --- owned.yaml: Urteile, aber Maschinenurteile ------------------------------


def test_owned_becomes_a_relation_and_a_machine_judgement(store: Store) -> None:
    """Die Datei trug ihren eigenen Hinweis, dass sie von nichts gelesen wird.
    Jetzt wird sie gelesen — aber als das, was sie ist."""
    report = seed(
        store,
        profile(),
        [],
        owned=[OwnedBook(title="Knochenbrecher", author="Chris Carter", stars=5, why="Hunter.")],
        now=NOW,
    )
    assert (report.books, report.relations, report.ratings) == (1, 1, 1)

    book = store.books()[0]
    assert {row.kind for row in store.relations_of("t", book.id)} == {str(RelationKind.OWNED)}

    row = store.rating(book_subject(book.id), OWNED_PROFILE_VERSION, origin=BY_CONVERSATION)
    assert (row.stars, row.reason) == (5, "Hunter.")


def test_owning_a_watched_book_stops_watching_it(store: Store) -> None:
    """Dieselben zwei Wirkungen wie "besitze ich" in der Oberfläche (Ticket 48).
    Der Import legte ``owned`` an und liess ``watching`` laufen — das Buch wurde
    weiter abgerufen und weiter gemeldet."""
    watchlist = [WatchlistEntry(title="Rosewater", author="Tade Thompson")]
    seed(store, profile(), watchlist, now=NOW)

    seed(
        store,
        profile(),
        watchlist,
        owned=[OwnedBook(title="Rosewater", author="Tade Thompson")],
        now=NOW,
    )

    assert store.relations("t", kind=str(RelationKind.WATCHING)) == []
    book = store.books()[0]
    assert {(row.kind, row.active) for row in store.relations_of("t", book.id)} == {
        (str(RelationKind.OWNED), True),
        (str(RelationKind.WATCHING), False),
    }


def test_a_second_import_keeps_watching_that_the_reader_resumed(store: Store) -> None:
    """Stillgelegt wird nur, wenn der Besitz neu hinzukommt. Hat die Leserin ein
    gekauftes Buch wieder auf die Watchlist geholt, gilt das — auch nach dem
    nächsten Import."""
    args = (
        profile(),
        [WatchlistEntry(title="Rosewater", author="Tade Thompson")],
    )
    owned = [OwnedBook(title="Rosewater", author="Tade Thompson")]
    seed(store, *args, owned=owned, now=NOW)
    book = store.books()[0]
    store.put_relation("t", book.id, str(RelationKind.WATCHING), now=NOW)

    seed(store, *args, owned=owned, now=NOW)

    assert [row.book_id for row in store.relations("t", kind=str(RelationKind.WATCHING))] == [
        book.id
    ]


def test_owned_stars_are_not_the_readers_own(store: Store) -> None:
    """Der ganze Zweck von Ticket 21: dreizehn Vorschläge wären sonst dauerhaft
    zu dreizehn Tatsachen geworden (ADR 17)."""
    seed(store, profile(), [], owned=[OwnedBook(title="Views", stars=4)], now=NOW)
    book = store.books()[0]

    assert store.rating(book_subject(book.id), 1, origin=BY_READER) is None


def test_the_hinweis_is_about_the_identification_not_the_judgement(store: Store) -> None:
    """Er bittet um Gegenprüfung, ob der Band im Handel so heißt — das gehört
    an die Beziehung, wo die Leserin es beim Nachsehen findet."""
    seed(
        store,
        profile(),
        [],
        owned=[OwnedBook(title="Off-Line", stars=3, hinweis="Bitte gegenprüfen.")],
        now=NOW,
    )
    relation = store.relations("t", kind=str(RelationKind.OWNED))[0]
    assert "gegenpr" in relation.details


def test_an_entry_without_stars_gets_no_judgement(store: Store) -> None:
    """Kein Urteil ist etwas anderes als null Sterne."""
    report = seed(store, profile(), [], owned=[OwnedBook(title="Nur ein Titel")], now=NOW)

    assert report.ratings == 0
    book = store.books()[0]
    assert store.ratings_for([book_subject(book.id)]) == {}


def test_importing_twice_leaves_one_judgement(store: Store) -> None:
    entries = [OwnedBook(title="Rosewater", author="Tade Thompson", stars=4, why="Wormwood.")]
    seed(store, profile(), [], owned=entries, now=NOW)
    seed(store, profile(), [], owned=entries, now=NOW)

    book = store.books()[0]
    assert len(store.ratings_for([book_subject(book.id)])) == 1
