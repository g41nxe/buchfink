"""Genres und Autor:innen, die die Leserin mag oder nicht mag (ADR 37, #91).

Ein nicht gemochtes Genre oder eine nicht gemochte Autor:in ist eine harte
Regel wie die Fremdsprache: der Fund wird nicht vorgeschlagen. Ein gemochtes
Genre ist ein kleiner Bonus im Urteil (`taste_form.overlap`). Gemochte
Autor:innen sind Entdeckungskanäle und stehen nicht hier, sondern bei den
Interessen.

Das Genre eines Buchs: die BISAC-Codes des Verlags, wo eine Quelle sie nennt,
sonst der Code des Steckbriefs. Ein Watchlist-Titel wird nie ausgeschlossen —
was sie selbst benannt hat, sortiert keine Regel aus.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime

from .cleaning import author_key
from .facets import ReadingProfile
from .genres import load_genres
from .models import MatchReason, Observation
from .portrait import VocabularyError, fingerprint, load_vocabulary
from .ratings import book_subject
from .relations import InterestKey
from .store import Store


def book_codes(source_codes: Iterable[str], portrait_code: str | None) -> tuple[str, ...]:
    """Die Genre-Codes eines Buchs, die der Liste: Quelle vor Modell.

    Ein BISAC-Code, der nicht auf der Liste steht, zählt mit dem „General"
    seiner Gruppe (FIC031020 → FIC031000), wo es den gibt. Nennt eine Quelle
    Codes, gilt der Code des Steckbriefs nicht mehr: der Verlag weiß es.
    """
    genres = load_genres()
    found: list[str] = []
    for code in source_codes:
        listed = code if code in genres else f"{code[:6]}000"
        if listed in genres and listed not in found:
            found.append(listed)
    if found:
        return tuple(found)
    return (portrait_code,) if portrait_code and portrait_code in genres else ()


def excluded_by(
    profile: ReadingProfile | None, observation: Observation, codes: Iterable[str]
) -> str | None:
    """Warum dieser Fund nicht vorgeschlagen wird — oder ``None``.

    Ein Treffer unter den Codes reicht; ein Genre gilt für die Untergenres
    darunter. Ein Buch ohne Code ist weder gesperrt noch begünstigt.
    """
    if profile is None or observation.match_reason is MatchReason.WATCHLIST:
        return None
    if observation.author and profile.disliked_authors:
        wanted = author_key(observation.author)
        for name in profile.disliked_authors:
            if author_key(name) == wanted:
                return f"Autor:in {observation.author}"
    genres = load_genres()
    for code in book_codes(codes, None):
        for disliked in profile.disliked_genres:
            if genres.covers(disliked, code):
                return f"Genre {genres.name(disliked)}"
    return None


def liked_genre(profile: ReadingProfile, codes: Iterable[str]) -> str | None:
    """Das gemochte Genre, das dieses Buch trägt — oder ``None``."""
    genres = load_genres()
    for code in book_codes(codes, None):
        for liked in profile.liked_genres:
            if genres.covers(liked, code):
                return liked
    return None


# --- Ansehen und ändern (Profilseite, Erstaufnahme) ----------------------------------

#: Was sich ändern lässt. Gemochte Autor:innen sind Entdeckungskanäle
#: (Interessen), alles andere steht im Leseprofil.
KINDS = ("liked_genre", "disliked_genre", "liked_author", "disliked_author")


@dataclass(frozen=True, slots=True)
class PreferencesView:
    """Was die Profilseite und Bildschirm 5 zeigen."""

    #: (Code, Name) je Genre.
    liked_genres: tuple[tuple[str, str], ...]
    disliked_genres: tuple[tuple[str, str], ...]
    #: (Name, Name) — dieselbe Gestalt wie die Genres, für eine Vorlage.
    liked_authors: tuple[tuple[str, str], ...]
    disliked_authors: tuple[tuple[str, str], ...]
    #: (Code, Name, Untergenre?) — die ganze Liste für die Auswahl.
    options: tuple[tuple[str, str, bool], ...]


def view(store: Store, profile_slug: str) -> PreferencesView:
    genres = load_genres()
    profile = store.reading_profile(profile_slug)

    def named(codes: Iterable[str]) -> tuple[tuple[str, str], ...]:
        return tuple((c, genres.name(c) or c) for c in codes)

    return PreferencesView(
        liked_genres=named(profile.liked_genres if profile else ()),
        disliked_genres=named(profile.disliked_genres if profile else ()),
        liked_authors=tuple(
            (row.value, row.value)
            for row in store.interests(profile_slug, key=str(InterestKey.AUTHOR))
        ),
        disliked_authors=tuple((a, a) for a in (profile.disliked_authors if profile else ())),
        options=tuple((g.code, g.name, g.parent is not None) for g in genres),
    )


def change(
    store: Store, profile_slug: str, kind: str, value: str, *, add: bool, now: datetime
) -> bool:
    """Ein Genre oder eine Autor:in mögen, nicht mögen, oder zurücknehmen.

    Eine Änderung am Leseprofil ist eine neue Fassung mit Anlass, wie beim
    Nachschärfen (ADR 33). Ein Genre, das nicht auf der Liste steht, wird nicht
    angenommen. Gibt zurück, ob sich etwas geändert hat.
    """
    value = " ".join(value.split())
    if kind not in KINDS or not value:
        return False
    if kind == "liked_author":
        store.put_interest(profile_slug, str(InterestKey.AUTHOR), value, active=add, now=now,
                           tier="extended")
        return True
    if kind.endswith("_genre") and value not in load_genres():
        return False
    profile = store.reading_profile(profile_slug) or ReadingProfile((), ())
    field = {"liked_genre": "liked_genres", "disliked_genre": "disliked_genres",
             "disliked_author": "disliked_authors"}[kind]
    current = getattr(profile, field)
    updated = tuple(dict.fromkeys((*current, value))) if add else tuple(
        v for v in current if v != value)
    if updated == current:
        return False
    store.put_reading_profile(profile_slug, replace(profile, **{field: updated}),
                              cause="Profilseite", now=now)
    return True


def from_books(store: Store, book_ids: Iterable[int]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Die Genre-Codes und Autor:innen dieser Bücher — die Vorschläge aus der
    Erstaufnahme. Quelle vor Modell, wie überall."""
    books = store.books_by_id(book_ids)
    isbns = [b.isbn for b in books.values() if b.isbn]
    bisac = store.bisac_codes(isbns)
    try:
        stamp = fingerprint(load_vocabulary())
    except VocabularyError:
        stamp = None
    codes: list[str] = []
    authors: list[str] = []
    for book in books.values():
        portrait = None
        if stamp is not None:
            subjects = ([f"isbn:{book.isbn}"] if book.isbn else []) + [book_subject(book.id)]
            found = store.portraits_for(subjects, stamp)
            portrait = next((found[s] for s in subjects if s in found), None)
        for code in book_codes(bisac.get(book.isbn or "", ()),
                               portrait.genre_code if portrait else None):
            if code not in codes:
                codes.append(code)
        if book.author and book.author not in authors:
            authors.append(book.author)
    return tuple(codes), tuple(authors)
