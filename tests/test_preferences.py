"""Genres und Autor:innen mögen und nicht mögen (ADR 37, #91)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from ebook_watchlist.facets import ReadingProfile
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.preferences import book_codes, excluded_by
from ebook_watchlist.store import Store

NOW = datetime(2026, 10, 4, 12, 0)
EMPTY = ReadingProfile((), ())


def find(author: str = "Jemand", isbn: str | None = None,
         reason: MatchReason = MatchReason.GENRE_CATEGORY) -> Observation:
    return Observation(source="beam", source_item_id="1", title="T", author=author,
                       isbn=isbn, match_reason=reason)


def test_the_profile_keeps_genres_and_authors(store: Store) -> None:
    profile = replace(EMPTY, liked_genres=("FIC028030",), disliked_genres=("FIC027000",),
                      disliked_authors=("Rosamunde Pilcher",))

    store.put_reading_profile("t", profile, cause="test", now=NOW)
    again = store.reading_profile("t")

    assert again.liked_genres == ("FIC028030",)
    assert again.disliked_genres == ("FIC027000",)
    assert again.disliked_authors == ("Rosamunde Pilcher",)


def test_the_source_code_comes_before_the_models() -> None:
    """Der Verlag vor dem Modell (ADR 37); ein BISAC-Code, der nicht auf der
    Liste steht, zählt mit dem „General" seiner Gruppe."""
    assert book_codes(("FIC031020",), "FIC031080") == ("FIC031000",)
    assert book_codes(("FIC027020", "FIC031080"), None) == ("FIC027020", "FIC031080")
    assert book_codes((), "FIC009020") == ("FIC009020",)
    assert book_codes(("ZZZ000000",), None) == ()


def test_a_disliked_genre_covers_its_subgenres() -> None:
    profile = replace(EMPTY, disliked_genres=("FIC027000",))

    assert excluded_by(profile, find(), ("FIC027030",)) == "Genre Liebesroman"
    assert excluded_by(profile, find(), ("FIC031080",)) is None


def test_one_code_of_a_book_is_enough() -> None:
    """Ein Thriller, den der Verlag auch als Romance einordnet, ist für sie
    ein Liebesroman (ADR 37)."""
    profile = replace(EMPTY, disliked_genres=("FIC027000",))

    assert excluded_by(profile, find(), ("FIC031000", "FIC027110")) is not None


def test_a_disliked_author_in_any_spelling() -> None:
    profile = replace(EMPTY, disliked_authors=("Pilcher, Rosamunde",))

    assert excluded_by(profile, find(author="Rosamunde Pilcher"), ()) == (
        "Autor:in Rosamunde Pilcher")


def test_a_book_without_a_code_is_not_excluded_by_genre() -> None:
    profile = replace(EMPTY, disliked_genres=("FIC027000",))

    assert excluded_by(profile, find(), ()) is None


def test_a_watchlist_title_is_never_excluded() -> None:
    """Was sie selbst benannt hat, sortiert keine Regel aus."""
    profile = replace(EMPTY, disliked_authors=("Jemand",), disliked_genres=("FIC027000",))

    assert excluded_by(profile, find(reason=MatchReason.WATCHLIST), ("FIC027020",)) is None


def test_a_liked_genre_adds_a_small_bonus() -> None:
    """Kleiner als ein verstärktes Merkmal, und als eigener Schritt sichtbar."""
    from ebook_watchlist.facets import load_weights
    from ebook_watchlist.portrait import Portrait, Trait, fingerprint, load_vocabulary
    from ebook_watchlist.taste_form import learn, overlap

    vocabulary, weights = load_vocabulary(), load_weights()
    portrait = Portrait(known=True, fingerprint=fingerprint(vocabulary), genre_code="FIC028030",
                        traits=(Trait("world_building", "Satz.", "wissen", "praegend"),))
    from ebook_watchlist.facets import Liked

    plain = replace(EMPTY, liked=(Liked(vocabulary.family_of("world_building").id),))
    liking = replace(plain, liked_genres=("FIC028000",))

    without = overlap(portrait, plain, learn(plain, (), vocabulary, weights), vocabulary, weights)
    with_ = overlap(portrait, liking, learn(liking, (), vocabulary, weights), vocabulary, weights)

    assert with_.share > without.share
    assert any(step.kind == "liked_genre" for step in with_.steps)
    assert weights.genre_bonus < weights.prior_boosted


# --- im Lauf und im Stapel ------------------------------------------------------


def delta(observation: Observation):
    from ebook_watchlist.models import Delta, DeltaKind

    return Delta(DeltaKind.FIRST_SEEN, observation, None)


def test_the_run_drops_what_she_does_not_like_before_the_gate(store: Store) -> None:
    """Vor dem Tor nach Autor:in und Verlags-BISAC: das kostet keinen
    Steckbrief. Danach gilt der Code des Steckbriefs."""
    from ebook_watchlist.dnb import Record
    from ebook_watchlist.run import _without_disliked

    store.put_reading_profile("t", replace(EMPTY, disliked_genres=("FIC027000",),
                                           disliked_authors=("Rosamunde Pilcher",)),
                              cause="test", now=NOW)
    store.save_dnb("9783000000601", Record(title="T", bisac=("FIC027020",)), NOW)
    kept = _without_disliked(store, "t", [
        delta(find(author="Rosamunde Pilcher")),
        delta(find(isbn="9783000000601")),
        delta(find(isbn="9783000000602")),
        delta(find(author="Pilcher, Rosamunde", reason=MatchReason.WATCHLIST)),
    ])

    assert [(d.current.author, d.current.isbn) for d in kept] == [
        ("Jemand", "9783000000602"), ("Pilcher, Rosamunde", None)]


def test_after_the_gate_the_portrait_code_counts(store: Store) -> None:
    from ebook_watchlist.portrait import Portrait, fingerprint, load_vocabulary
    from ebook_watchlist.run import _without_disliked

    store.put_reading_profile("t", replace(EMPTY, disliked_genres=("FIC027000",)),
                              cause="test", now=NOW)
    store.put_portrait("isbn:9783000000603", Portrait(
        known=True, fingerprint=fingerprint(load_vocabulary()), genre_code="FIC027030"), now=NOW)

    assert _without_disliked(store, "t", [delta(find(isbn="9783000000603"))]) == []


def test_the_pile_hides_and_counts_what_she_does_not_like(data_dir) -> None:
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.web import triage

    store, settings = Store(paths.db_path()), load_settings()
    store.put_reading_profile(settings.slug, replace(
        EMPTY, disliked_authors=("Rosamunde Pilcher",)), cause="test", now=NOW)
    seen = [Observation(source="beam", source_item_id=str(n), title=f"T{n}", author=author,
                        price_cents=199, match_reason=MatchReason.GENRE_CATEGORY,
                        observed_at=NOW)
            for n, author in ((1, "Rosamunde Pilcher"), (2, "Jemand Anderes"))]
    store.append(store.start_run(settings.slug, "cli", NOW), settings.slug, seen, NOW)

    pile = triage.pending(store, settings)

    assert [s.author for s in pile.items] == ["Jemand Anderes"]
    assert pile.hidden_disliked == 1
    assert (1, "nicht gemocht") in pile.hidden


# --- aus dem Review (04.10.2026) -------------------------------------------------


def test_following_again_keeps_a_daily_author_daily(store: Store) -> None:
    """Ein Referenzautor aus dem Saatgut ist täglich; ein erneutes Folgen oder
    Zurücknehmen stuft ihn nicht auf wöchentlich herunter."""
    import json

    from ebook_watchlist.preferences import change

    store.put_interest("t", "author", "Chris Carter", now=NOW, tier="core")

    change(store, "t", "liked_author", "Chris Carter", add=True, now=NOW)
    change(store, "t", "liked_author", "Chris Carter", add=False, now=NOW)

    (row,) = store.interests("t", key="author", active_only=False)
    assert json.loads(row.details)["tier"] == "core"
    assert row.active is False


def test_a_field_with_several_authors_is_excluded_by_any_of_them() -> None:
    profile = replace(EMPTY, disliked_authors=("Stephen King",))

    assert excluded_by(profile, find(author="King, Stephen, Straub, Peter"), ())
    assert excluded_by(profile, find(author="Stephen King, Peter Straub"), ())


def test_a_genre_is_either_liked_or_disliked(store: Store) -> None:
    from ebook_watchlist.preferences import change

    store.put_reading_profile("t", EMPTY, cause="test", now=NOW)
    change(store, "t", "liked_genre", "FIC027000", add=True, now=NOW)
    change(store, "t", "disliked_genre", "FIC027000", add=True, now=NOW)

    profile = store.reading_profile("t")
    assert (profile.liked_genres, profile.disliked_genres) == ((), ("FIC027000",))


def test_the_liked_genre_bonus_reads_the_publishers_code_first(store: Store) -> None:
    """Wie der Ausschluss: der Verlag vor dem Modell. Gemocht ist Thriller,
    der Steckbrief sagt Fantasy, der Verlag Psychothriller."""
    from ebook_watchlist.dnb import Record
    from ebook_watchlist.facets import Liked, load_weights
    from ebook_watchlist.portrait import Portrait, Trait, fingerprint, load_vocabulary
    from ebook_watchlist.taste_form import learn, overlap

    vocabulary, weights = load_vocabulary(), load_weights()
    stamp = fingerprint(vocabulary)
    store.save_dnb("9783000000701", Record(title="T", bisac=("FIC031080",)), NOW)
    store.put_portrait("isbn:9783000000701", Portrait(
        known=True, fingerprint=stamp, genre_code="FIC009000",
        traits=(Trait("world_building", "Satz.", "wissen", "praegend"),)), now=NOW)
    portrait = store.portrait("isbn:9783000000701", stamp)
    profile = replace(EMPTY, liked=(Liked(vocabulary.family_of("world_building").id),),
                      liked_genres=("FIC031000",))

    result = overlap(portrait, profile, learn(profile, (), vocabulary, weights), vocabulary,
                     weights)

    assert portrait.source_codes == ("FIC031080",)
    assert any(step.kind == "liked_genre" for step in result.steps)


def test_importing_a_profile_file_keeps_genres_and_authors(store: Store, tmp_path,
                                                          monkeypatch) -> None:
    """Die Datei kennt die neuen Felder nicht; sie gehen deshalb nicht verloren."""
    from ebook_watchlist import facets, paths

    store.put_reading_profile("t", replace(EMPTY, disliked_genres=("FIC027000",),
                                           disliked_authors=("Rosamunde Pilcher",)),
                              cause="test", now=NOW)
    profile_file = tmp_path / "profil.yaml"
    profile_file.write_text("gemocht: [brooding]\n", encoding="utf-8")
    monkeypatch.setattr(paths, "db_path", lambda: store.path)
    monkeypatch.setattr("ebook_watchlist.config.load_settings",
                        lambda: type("S", (), {"slug": "t"})())

    assert facets.main([str(profile_file)]) == 0

    profile = store.reading_profile("t")
    assert profile.disliked_genres == ("FIC027000",)
    assert profile.disliked_authors == ("Rosamunde Pilcher",)


def test_without_a_profile_only_following_is_possible(store: Store) -> None:
    """Vor der Erstaufnahme gibt es kein Leseprofil; ein Genre oder eine
    gesperrte Autor:in legte sonst ein leeres an, und ab dann urteilte der
    Code gegen nichts (Review 04.10.2026)."""
    from ebook_watchlist.preferences import change

    assert not change(store, "t", "disliked_genre", "FIC027000", add=True, now=NOW)
    assert not change(store, "t", "disliked_author", "Rosamunde Pilcher", add=True, now=NOW)
    assert store.reading_profile("t") is None
    assert change(store, "t", "liked_author", "Blake Crouch", add=True, now=NOW)


def test_an_author_is_either_followed_or_not_suggested(store: Store) -> None:
    from ebook_watchlist.preferences import change
    from ebook_watchlist.relations import InterestKey

    store.put_reading_profile("t", EMPTY, cause="test", now=NOW)
    change(store, "t", "liked_author", "Stephen King", add=True, now=NOW)
    change(store, "t", "disliked_author", "King, Stephen", add=True, now=NOW)

    assert not store.interests("t", key=str(InterestKey.AUTHOR))
    assert store.reading_profile("t").disliked_authors == ("King, Stephen",)

    change(store, "t", "liked_author", "Stephen King", add=True, now=NOW)

    assert [r.value for r in store.interests("t", key=str(InterestKey.AUTHOR))] == [
        "Stephen King"]
    assert store.reading_profile("t").disliked_authors == ()


def test_the_suggested_name_is_the_whole_first_person() -> None:
    from ebook_watchlist.preferences import display_author

    assert display_author("Crouch, Blake") == "Blake Crouch"
    assert display_author("Martin, George R. R.") == "George R. R. Martin"
    assert display_author("Ruiz Zafón, Carlos") == "Carlos Ruiz Zafón"
    assert display_author("le Carré, John") == "John le Carré"
    assert display_author("Le Guin, Ursula K.") == "Ursula K. Le Guin"
    assert display_author("King, Stephen, Straub, Peter") == "Stephen King"
    assert display_author("Michael Crichton, Norbert Wölfl") == "Michael Crichton"
    assert display_author("Stephen King; Peter Straub") == "Stephen King"
    assert display_author("Stephen King") == "Stephen King"


def test_a_sort_form_with_a_long_given_name_is_excluded() -> None:
    profile = replace(EMPTY, disliked_authors=("George R. R. Martin",))

    assert excluded_by(profile, find(author="Martin, George R. R."), ()) is not None
