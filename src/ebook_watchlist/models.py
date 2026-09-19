"""The values that flow through a Run: Observations in, Deltas out."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Availability(StrEnum):
    """What a Library Source reports about a title. Shop Sources leave this unset."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class MatchReason(StrEnum):
    """Why an item is in the Snapshot at all (see CONTEXT.md)."""

    WATCHLIST = "watchlist"
    PROFILE_AUTHOR = "profile_author"
    GENRE_CATEGORY = "genre_category"


class LinkOutcome(StrEnum):
    """What happened when a Source was asked where a book is (ADR 18).

    The distinction the old "Braucht Aufmerksamkeit" list could not make:
    NOT_FOUND is an answer and needs nobody, UNSURE is a question and needs a
    human. Listing both together produced a task list with nothing to do in it.
    """

    #: Resolved on its own and trusted (ADR 8's confidence gate).
    LINKED = "linked"
    #: A human picked this one.
    CONFIRMED = "confirmed"
    #: Candidates existed, none good enough. A person has to look.
    UNSURE = "unsure"
    #: The catalogue does not have it. Nothing to do.
    NOT_FOUND = "not_found"


#: The only outcomes a stored link may carry. An unknown one is a bug in the
#: writer, not a value to be tolerated: it would silently fall out of every
#: query that asks "what still needs attention".
LINK_OUTCOMES: frozenset[str] = frozenset(outcome.value for outcome in LinkOutcome)


class DeltaKind(StrEnum):
    #: A discovered title we had never seen before. For a Watchlist Entry a
    #: first sighting is only a baseline, but for a discovery the appearing
    #: *is* the news, so it has no previous Observation to point at.
    FIRST_SEEN = "first_seen"
    BECAME_AVAILABLE = "became_available"
    BECAME_UNAVAILABLE = "became_unavailable"
    PRICE_DROP = "price_drop"
    PRICE_RISE = "price_rise"


@dataclass(frozen=True, slots=True)
class Observation:
    """One recording of an item's state as seen by one Source during one Run."""

    source: str
    source_item_id: str
    title: str
    match_reason: MatchReason
    author: str | None = None
    watchlist_key: str | None = None
    #: Das Buch, auf das sich diese Beobachtung bezieht. Gesetzt bei
    #: Watchlist-Pruefungen, None bei Entdeckungen (ADR 18).
    book_id: int | None = None
    price_cents: int | None = None
    original_price_cents: int | None = None
    availability: Availability | None = None
    reservation_count: int | None = None
    available_from: str | None = None
    category: str | None = None
    url: str | None = None
    #: Der Klappentext-Teaser von der Trefferseite. Kostet keinen eigenen
    #: Request und ist das einzige Signal, aus dem sich Katz-und-Maus,
    #: isolierte Settings und Tonlage überhaupt ablesen lassen (ADR 17).
    blurb: str | None = None
    subtitle: str | None = None
    #: Die ISBN-13, wo die Source eine nennt. Beide tun es (ADR 18).
    isbn: str | None = None
    #: Adresse des Titelbilds bei der Quelle. Wird einmal geholt und lokal
    #: abgelegt, nie verlinkt (Ticket 15).
    cover_url: str | None = None
    #: Was die Leserschaft der Quelle im Schnitt vergeben hat, 0 bis 5 — und
    #: auf wie vielen Stimmen das ruht. Ohne die Anzahl ist der Schnitt
    #: wertlos: 5,0 aus einer Stimme ist keine Auskunft (Ticket 54).
    rating: int | None = None
    rating_votes: int | None = None
    #: Nur gesetzt, wo eine Source die Reihe ausdrücklich benennt.
    series: str | None = None
    observed_at: datetime | None = None
    # --- Belege fuer den Bewerter (#17) ---------------------------------
    # Nicht gespeichert und nicht verglichen: sie werden erst unmittelbar vor
    # einem Urteil zusammengetragen, und nur fuer die Buecher, die eins
    # bekommen. Im Journal stuenden sonst taeglich fuenfzig Seiten Text.
    #: Schlagwoerter von Quelle und DNB — Motive und Vergleichstitel.
    keywords: tuple[str, ...] = ()
    #: Der Titel des Originals, bei einer Uebersetzung (DNB).
    original_title: str | None = None
    #: Der Anfang des Buchs aus der Leseprobe.
    sample: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        """Identity across Runs — the pair a diff is computed over."""
        return (self.source, self.source_item_id)


@dataclass(frozen=True, slots=True)
class Delta:
    """A reportable change between the latest Observation and the previous one."""

    kind: DeltaKind
    current: Observation
    #: ``None`` only for :attr:`DeltaKind.FIRST_SEEN`.
    previous: Observation | None


@dataclass(frozen=True, slots=True)
class SourceFailure:
    """A Source that raised. Collected rather than fatal — other Sources still run."""

    source: str
    message: str


@dataclass(frozen=True, slots=True)
class Attention:
    """A Watchlist Entry a Source could not confidently place.

    Not an error — the site answered fine, we just will not guess. The entry is
    skipped for this Run and named in the Digest so it can be pinned by hand.
    """

    source: str
    entry_title: str
    entry_author: str | None
    reason: str
    best_guess: str | None = None
    best_guess_url: str | None = None
