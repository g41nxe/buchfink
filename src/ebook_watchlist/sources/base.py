"""The Source contract (ADR 7).

A Source raises only when the *site* changed shape — a selector that no longer
matches, an unparseable page. A title that simply is not there returns ``None``
and is not an error. Whatever a Source raises fails that Source alone; the Run
finishes the others and reports the failure in the Digest.
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..config import Profile, WatchlistEntry
from ..dismissals import Dismissed
from ..matching import Confidence, Resolution
from ..models import Attention, LinkOutcome, Observation
from ..store import Store

#: How long a failed resolution is trusted before the Source tries again. Long
#: enough not to hammer a search endpoint, short enough that a title the library
#: acquires later is eventually found.
RESOLUTION_RETRY_AFTER = timedelta(days=7)


class SourceStructureError(Exception):
    """The page no longer looks the way the parser expects. Loud on purpose."""


@dataclass(frozen=True, slots=True)
class Item:
    """What a Source says about *one* product, asked for by its own id.

    Deliberately not an Observation: nothing here is observed, diffed or
    carried forward. It answers a single question — which book does this
    product number mean — and that question has one caller (Ticket 17).
    """

    source_item_id: str
    title: str
    author: str | None = None
    isbn: str | None = None
    url: str | None = None
    #: Der ganze Klappentext von der Detailseite. Die Kachel traegt nur einen
    #: Anriss, und das Bewertungstor urteilt sonst ueber 200 Zeichen.
    blurb: str | None = None
    #: Das Titelbild von der Detailseite — groesser als das der Kachel. Die
    #: Seite wird fuer den Klappentext ohnehin geholt; es hier fallen zu
    #: lassen hiesse, sie fuer dasselbe Bild ein zweites Mal zu holen.
    cover_url: str | None = None
    #: Die Leseprobe als EPUB, wo die Quelle eine anbietet (#17).
    sample_url: str | None = None
    #: Die Schlagwoerter der Quelle, ohne Autor und Titel (#17).
    keywords: tuple[str, ...] = ()
    #: Der Verlag, fuer den Abzug bei Selbstverlag (#28).
    publisher: str | None = None


@dataclass(slots=True)
class RunContext:
    """What a Source may reach for beyond its own configuration.

    Deliberately narrow: resolutions it has made before, and a place to report
    entries it could not place. Sources never touch the Snapshot directly.
    """

    profile_slug: str
    store: Store
    now: datetime
    attention: list[Attention] = field(default_factory=list)
    #: Suggestions waved away for good. Read off the Book Relations, not off a
    #: per-shop id list: "I already own this" is true of the book, so it has to
    #: hold at every Source (ADR 18, Ticket 17).
    dismissed: Dismissed = field(default_factory=Dismissed)
    #: Whether this Run also walks the weekly long tail of Reference Authors.
    sweep_extended: bool = False
    #: Watchlist-Key -> Buch-Id, damit ein Eintrag nicht pro Quelle neu
    #: gesucht wird.
    _books: dict[str, int] = field(default_factory=dict)
    #: Welches Interesse einen Fund hervorgebracht hat. Ohne das liesse sich
    #: die Aussaat nicht pro Interesse fuehren — genau der Fehler, den der
    #: alte gemeinsame Scope hatte (Ticket 05).
    origin: dict[tuple[str, str], int] = field(default_factory=dict)
    #: Interessen dieses Profils, nach Schluessel und Wert.
    interests: dict[tuple[str, str], int] = field(default_factory=dict)
    #: ``(Quelle, Interesse-Id)`` fuer alles, was in diesem Lauf wirklich
    #: gefegt wurde — unabhaengig davon, ob etwas dabei herauskam. Nur an
    #: den Funden zu erkennen, was gefegt wurde, hiesse: eine Autor:in,
    #: deren Titel alle schon auf der Watchlist stehen, saet nie an und
    #: flutet beim naechsten Mal erneut.
    swept: set[tuple[str, int]] = field(default_factory=set)

    def is_dismissed(self, observation: Observation) -> bool:
        """Whether this find is a book the reader has waved away for good.

        The whole Observation rather than the id, because the id only settles
        it at the shop it came from. The ISBN is what carries the answer to the
        *other* Source — which was the point of moving dismissals onto the book.
        """
        return self.dismissed.covers(
            observation.source, observation.source_item_id, observation.isbn
        )

    def book_for(self, entry: WatchlistEntry) -> int:
        """Die Buch-Zeile zu diesem Watchlist-Eintrag, angelegt falls noetig.

        Der Eintrag kommt in diesem Schnitt noch aus der YAML und traegt keine
        ISBN; die Identitaet entsteht also ueber Titel und Autor:in und wird
        spaeter durch die ISBN geschaerft, sobald eine Beobachtung eine
        mitbringt (ADR 18).
        """
        cached = self._books.get(entry.key)
        if cached is not None:
            return cached
        row = self.store.find_or_create_book(
            isbn=None, title=entry.title, author=entry.author, now=self.now
        )
        self._books[entry.key] = row.id
        return row.id

    def remembered_link(self, source: str, entry: WatchlistEntry) -> tuple[str | None, bool]:
        """``(url, still_valid)`` for a previous resolution of this entry.

        ``still_valid`` is False when there is nothing remembered, or when a
        failed attempt has aged out and deserves another try.
        """
        row = self.store.get_book_source(self.book_for(entry), source)
        if row is None:
            return None, False
        if row.url:
            return row.url, True
        return None, self.now - row.resolved_at < RESOLUTION_RETRY_AFTER

    def remember(self, source: str, entry: WatchlistEntry, resolution: Resolution) -> None:
        best = resolution.best
        accepted = resolution.accepted
        if accepted is not None:
            outcome = LinkOutcome.LINKED
        elif resolution.confidence is Confidence.PROVISIONAL:
            outcome = LinkOutcome.UNSURE
        else:
            # Kandidaten gab es, aber keiner war es. Das ist eine Antwort, keine
            # Frage — und es gehoert nicht auf eine Liste, die um Mithilfe bittet.
            outcome = LinkOutcome.NOT_FOUND
        self.store.put_book_source(
            self.book_for(entry),
            source,
            outcome=str(outcome),
            url=str(accepted.payload) if accepted else None,
            resolved_at=self.now,
            reason=resolution.reason,
            # Titel und Autor:in *so, wie diese Quelle sie schreibt* — daran
            # bleibt eine falsche automatische Zuordnung sichtbar (ADR 9).
            matched_title=best.candidate.title if best else None,
            matched_author=best.candidate.author if best else None,
            # Alle, die der Matcher nicht auseinanderhalten konnte — nicht nur
            # der Sieger. Ohne sie stand die Leserin vor einer Auswahl mit
            # genau einer Option, obwohl die Vorlage schon eine Liste war
            # (Ticket 41).
            #
            # **Ohne Preis.** Bei einer Bestaetigung geht es um Identitaet,
            # nicht um ein Angebot, und eine Ablehnung soll halten — sie darf
            # sich nicht auf einen Betrag von vorgestern beziehen.
            candidates=[
                {
                    "title": kandidat.title,
                    "author": kandidat.author,
                    "url": str(kandidat.payload) if kandidat.payload else None,
                    "cover_url": kandidat.cover_url,
                }
                for kandidat in resolution.indistinguishable
            ]
            or None,
        )

    def remember_absence(self, source: str, entry: WatchlistEntry, reason: str) -> None:
        """The catalogue simply does not have it — worth not asking again soon."""
        self.store.put_book_source(
            self.book_for(entry),
            source,
            outcome=str(LinkOutcome.NOT_FOUND),
            url=None,
            resolved_at=self.now,
            reason=reason,
        )

    def needs_attention(self, source: str, entry: WatchlistEntry, resolution: Resolution) -> None:
        best = resolution.best
        self.attention.append(
            Attention(
                source=source,
                entry_title=entry.title,
                entry_author=entry.author,
                reason=resolution.reason,
                best_guess=best.candidate.title if best else None,
                best_guess_url=best.candidate.payload if best else None,
            )
        )


class Source(ABC):
    """Anything a Run can poll."""

    #: Stable identifier used as ``observation.source`` — never change it for a
    #: live Source, the Snapshot is keyed on it.
    name: str

    @abstractmethod
    def collect(
        self, profile: Profile, watchlist: Sequence[WatchlistEntry], context: RunContext
    ) -> list[Observation]:
        """Everything this Source has to say this Run."""

    def probe(self) -> None:
        """Known-good self-check for ``ebw doctor`` (ticket 08). Raises on failure."""
        return None

    def item(self, source_item_id: str) -> Item | None:
        """Which book this Source's own id means. ``None`` if it no longer knows.

        The reverse of everything else here: not "find me this book", but "tell
        me what you filed under this number". A Source that cannot answer that
        says so by leaving this alone.
        """
        return None


class ResolvingSource(Source):
    """A Source that can find a title's own page from just title and author.

    The resolution itself is site-specific; the caching, the retry window and
    the "needs attention" reporting are the same everywhere and live here.
    """

    def resolve(self, entry: WatchlistEntry) -> Resolution | None:
        """Search for ``entry``. ``None`` means a genuine "not in this catalogue"."""
        return None

    def wants(self, entry: WatchlistEntry) -> bool:
        """Ob dieser Eintrag an dieser Art Quelle geprueft werden soll.

        ``restrict`` sagt das je Eintrag: "nur Bibliothek", "nur Shop", oder
        beides. Die Unterklassen sagen, welche der beiden Angaben sie meinen.
        """
        return True

    def watch(
        self, watchlist: Sequence[WatchlistEntry], context: RunContext
    ) -> list[Observation]:
        """Nur die Watchlist — ohne Entdeckung.

        Herausgezogen, weil ein Lauf fuer *einen* Eintrag genau diesen Teil
        braucht und sonst nichts (Ticket 51). Vorher stand die Schleife
        zweimal da, einmal je Quellenart, und ``collect`` haengte bei einem
        Shop die Genre-Suche an — dreihundert Funde, wo einer gefragt war.
        """
        observations = []
        for entry in watchlist:
            if not (entry.active and self.wants(entry)):
                continue
            linked = self.linked_entry(entry, context)
            if linked is None:
                continue
            observation = self.check(linked)
            if observation is not None:
                observations.append(
                    dataclasses.replace(observation, book_id=context.book_for(entry))
                )
        return observations

    def linked_entry(self, entry: WatchlistEntry, context: RunContext) -> WatchlistEntry | None:
        """``entry`` with this Source's link filled in, or ``None`` to skip it."""
        if entry.resolved_links.get(self.name):
            return entry  # a hand-pinned link always wins

        remembered, still_valid = context.remembered_link(self.name, entry)
        if remembered:
            return dataclasses.replace(
                entry, resolved_links={**entry.resolved_links, self.name: remembered}
            )
        if still_valid:
            return None  # we looked recently and came up empty; don't ask again

        resolution = self.resolve(entry)
        if resolution is None:
            # Not in the catalogue at all. Remember that, quietly.
            context.remember_absence(self.name, entry, "not in this catalogue")
            return None

        context.remember(self.name, entry, resolution)
        accepted = resolution.accepted
        if accepted is None:
            # Nur ein *plausibler* Treffer ist eine Frage an einen Menschen.
            # "Nichts passt" auf dieselbe Liste zu setzen hat sie mit Zeilen
            # gefuellt, bei denen es nichts zu entscheiden gab (Ticket 04).
            if resolution.confidence is Confidence.PROVISIONAL:
                context.needs_attention(self.name, entry, resolution)
            return None

        return dataclasses.replace(
            entry, resolved_links={**entry.resolved_links, self.name: str(accepted.payload)}
        )


class LibrarySource(ResolvingSource):
    """Reports whether a title can be borrowed right now."""

    @abstractmethod
    def check(self, entry: WatchlistEntry) -> Observation | None: ...

    def wants(self, entry: WatchlistEntry) -> bool:
        return entry.check_library

    def collect(
        self, profile: Profile, watchlist: Sequence[WatchlistEntry], context: RunContext
    ) -> list[Observation]:
        return self.watch(watchlist, context)


class ShopSource(ResolvingSource):
    """Reports price and catalogue presence."""

    @abstractmethod
    def check(self, entry: WatchlistEntry) -> Observation | None: ...

    def wants(self, entry: WatchlistEntry) -> bool:
        return entry.check_shop

    def by_author(self, author: str) -> list[Observation]:
        """Everything this shop stocks by one Reference Author."""
        return []

    def by_category(self, category_path: str) -> list[Observation]:
        """The newest arrivals on one of the shop's own shelves."""
        return []

    def collect(
        self, profile: Profile, watchlist: Sequence[WatchlistEntry], context: RunContext
    ) -> list[Observation]:
        observations = self.watch(watchlist, context)

        # Discoveries must not collide with what the Watchlist already covers:
        # two Observations of one item in a single Run would leave the diff with
        # no single "latest" to compare against next time.
        seen = {observation.source_item_id for observation in observations}

        def take(discovered: list[Observation], interest_id: int | None) -> None:
            for observation in discovered:
                item_id = observation.source_item_id
                if item_id in seen or context.is_dismissed(observation):
                    continue
                seen.add(item_id)
                observations.append(observation)
                if interest_id is not None:
                    context.origin[(self.name, item_id)] = interest_id

        for author in profile.authors_to_sweep(context.sweep_extended):
            interest_id = context.interests.get(("author", author))
            if interest_id is not None:
                context.swept.add((self.name, interest_id))
            take(self.by_author(author), interest_id)
        for category in profile.genre_categories:
            interest_id = context.interests.get(("thema", category))
            if interest_id is not None:
                context.swept.add((self.name, interest_id))
            take(self.by_category(category), interest_id)
        return observations
