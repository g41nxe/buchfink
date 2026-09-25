"""Was die Watchlist-Seite über ein beobachtetes Buch weiß (Ticket 06).

Getrennt von den Routen, damit die Zusammenstellung testbar ist, ohne einen
HTTP-Client zu bemühen — und damit die Vorlage nichts rechnet.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ..config import Settings
from ..deals import is_strong_deal
from ..judging import load_judge
from ..matching.bundles import looks_like_bundle
from ..models import Availability, LinkOutcome, Observation
from ..ratings import book_subject, subject_of
from ..relations import DONE_LABELS, RelationKind, labelled_actions
from ..sources import registry
from ..store import Store
from . import sorting

#: Was die Leserin je Eintrag einschränken kann. Leer heißt: alle Quellen, die
#: eingeschaltet sind — nicht "keine".
RESTRICTIONS = ("library", "shop")

#: Womit ein Eintrag die Watchlist verlässt. Dieselben zwei Arten, nach denen
#: :func:`entries` filtert — und die Namen aus der einen Tabelle statt aus der
#: Vorlage, in der sie bis hierher zum zweiten Mal standen.
#:
#: Ausschließen zuerst, wie in der Reihe der Vorschlagsseite (``triage.ACTIONS``):
#: dieselben zwei Zeichen stehen jetzt in beiden Listen, und sie sollen in
#: derselben Reihenfolge stehen (#22).
CLOSINGS: tuple[tuple[str, str], ...] = labelled_actions(
    RelationKind.DISMISSED, RelationKind.OWNED
)


def _details(row) -> dict:
    try:
        return json.loads(row.details or "{}")
    except (TypeError, ValueError):  # pragma: no cover - defekte Zeile
        return {}


@dataclass(frozen=True, slots=True)
class SourceState:
    """Was eine Quelle über dieses Buch sagt."""

    name: str
    outcome: str
    url: str | None
    matched_title: str | None
    matched_author: str | None
    reason: str
    #: "library" oder "shop" — was diese Quelle *ist*. Die Registry sagt es,
    #: nicht eine Namensliste in der Vorlage (Ticket 14).
    category: str = "shop"
    #: Wie sie der Leserin gegenueber heisst.
    display: str = "Shop"
    #: Die Ausgaben, die der Matcher nicht auseinanderhalten konnte, und
    #: die schon abgelehnten. Beide ohne Preis: bei einer Bestaetigung geht
    #: es um Identitaet, nicht um ein Angebot (Ticket 41).
    candidates: tuple = ()
    rejected: tuple = ()

    @property
    def is_question(self) -> bool:
        """Ob hier ein Mensch entscheiden muss.

        ``not_found`` ist eine Antwort und braucht niemanden; nur ``unsure``
        ist eine Frage (Ticket 04).
        """
        return self.outcome == LinkOutcome.UNSURE

    @property
    def label(self) -> str:
        return {
            LinkOutcome.LINKED: "gefunden",
            LinkOutcome.CONFIRMED: "bestätigt",
            LinkOutcome.UNSURE: "unklar",
            LinkOutcome.NOT_FOUND: "nicht im Katalog",
        }.get(self.outcome, self.outcome)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SourceGroup:
    """Alle Quellen einer Art, als *ein* Zeichen in der Zeile (#35).

    In einer Liste zaehlt: kann ich es leihen, und ist es billig. Das
    beantwortet die Farbe; die Zahl sagt, wie viele Quellen nachgesehen haben.
    Ein Zeichen je Quelle waere bei acht Quellen kein Ueberblick mehr, sondern
    ein Muster — und welche Bibliothek welches Zeichen ist, sieht man ohnehin
    nicht. Welche es genau war, steht auf der Buchseite (#34).

    Die Breite der Zeile bleibt damit gleich, egal wie viele Quellen
    dazukommen. Das ist der Punkt: in einer Liste sollen alle Zeilen gleich
    gebaut sein.
    """

    category: str
    sources: tuple[SourceState, ...]

    @property
    def library(self) -> bool:
        return self.category == "library"

    @property
    def count(self) -> int:
        return len(self.sources)

    @property
    def found(self) -> bool:
        """Ob ueberhaupt eine Quelle dieser Art das Buch fuehrt."""
        return any(state.outcome in ("linked", "confirmed") for state in self.sources)

    @property
    def url(self) -> str | None:
        """Wohin der Klick fuehrt: zur ersten Quelle, die es hat.

        Eine Zeile hat ein Ziel. Welche Quelle sonst noch, steht auf der
        Buchseite.
        """
        for state in self.sources:
            if state.url and state.outcome in ("linked", "confirmed"):
                return state.url
        return None

    @property
    def hint(self) -> str:
        """Die Zahl sagt wie viele, dieser Hinweis welche."""
        return " · ".join(f"{state.display}: {state.label}" for state in self.sources)


def source_groups(sources: Sequence[SourceState]) -> tuple[SourceGroup, ...]:
    """Die Quellen einer Zeile, nach Art gebuendelt (#35).

    Innerhalb der Art die gefundenen zuerst: sie faerben das Zeichen, sie
    tragen den Verweis, und sie stehen im Hinweis vorn.
    """
    groups = []
    for category in registry.CATEGORY_ORDER:
        same_kind = [state for state in sources if state.category == category]
        if not same_kind:
            continue
        same_kind.sort(key=lambda state: state.outcome not in ("linked", "confirmed"))
        groups.append(SourceGroup(category, tuple(same_kind)))
    return tuple(groups)


@dataclass(frozen=True, slots=True)
class Entry:
    """Eine Zeile der Watchlist."""

    book_id: int
    title: str
    author: str | None
    active: bool
    restrict: str | None
    note: str | None
    cover_file: str | None
    sources: tuple[SourceState, ...]
    #: Je Quelle die juengste Beobachtung, neueste zuerst. Frueher war es
    #: **eine** je Buch, und welche, entschied die Reihenfolge der Quellen in
    #: ``settings.yaml`` — mit zwei Bibliotheken also der Zufall.
    latest: tuple[Observation, ...] = ()
    #: Unter der Schnaeppchen-Grenze. Faerbt den Preis und setzt das
    #: Abzeichen aufs Cover — dieselbe Farbe bedeutet ueberall dasselbe.
    deal: bool = False
    #: Der Titel, zu dem die Leserin "kenne ich" gesagt hat (ADR 27).
    known_missing: str | None = None
    #: Das gerechnete Urteil, wo ein Steckbrief und ein Profil vorliegen —
    #: dieselbe Spalte wie im Stapel (#16, #48). Die eigenen Sterne der Leserin
    #: stehen hier bewusst nicht: die vergibt sie nach dem Lesen, und dann ist
    #: der Titel meist schon abgeschlossen und von der Liste.
    stars: int | None = None
    percent: int | None = None
    pitch: str | None = None
    #: Wann dieser Titel auf die Watchlist kam. Der Zeitstempel der Beziehung,
    #: und der wird nur beim Anlegen gesetzt — ein Pausieren und Fortsetzen
    #: macht einen alten Eintrag also nicht zu einem neuen (#37).
    added_at: datetime | None = None

    @property
    def is_bundle(self) -> bool:
        """Siehe ``triage.Suggestion.is_bundle`` — dieselbe Ableitung."""
        return looks_like_bundle(self.title)

    @property
    def source_groups(self) -> tuple[SourceGroup, ...]:
        """Die Quellen dieser Zeile, nach Art gebuendelt (#35)."""
        return source_groups(self.sources)

    @property
    def needs_attention(self) -> bool:
        return any(state.is_question for state in self.sources)

    @property
    def newest(self) -> Observation | None:
        """Die juengste Beobachtung ueberhaupt — fuer alles, was keine Quelle meint."""
        return self.latest[0] if self.latest else None

    @property
    def price_cents(self) -> int | None:
        """Der Preis in Cent, aus derselben Quelle wie :attr:`price`.

        Eigenes Feld, weil die Startseite nach ihm sortiert und eine Zeichenkette
        mit Komma dafuer nicht taugt.
        """
        return next((o.price_cents for o in self.latest if o.price_cents is not None), None)

    @property
    def price(self) -> str | None:
        """Der Preis der juengsten Quelle, die einen nennt.

        Eine Bibliothek nennt keinen. Frueher stand hier nichts, sobald ihre
        Beobachtung zufaellig die neueste war.
        """
        cents = self.price_cents
        if cents is None:
            return None
        return f"{cents / 100:.2f} €".replace(".", ",")

    @property
    def _availability(self) -> Availability | None:
        """Die beste Auskunft, die *irgendeine* Bibliothek gibt.

        "Ausleihbar" ist eine Aussage ueber das Buch, nicht ueber eine Quelle:
        sagt eine der beiden Bibliotheken, sie hat es da, dann hat die Leserin
        es da. Frueher zaehlte, welche Quelle zuletzt eingefuegt wurde — und
        seit es zwei Bibliotheken gibt, schrieb das "verliehen" in die Zeile,
        waehrend die andere es auslieh.
        """
        answers = [o.availability for o in self.latest if o.availability is not None]
        for rank in (Availability.AVAILABLE, Availability.UNAVAILABLE, Availability.UNKNOWN):
            if rank in answers:
                return rank
        return None

    @property
    def availability(self) -> str | None:
        return {
            Availability.AVAILABLE: "ausleihbar",
            Availability.UNAVAILABLE: "verliehen",
            Availability.UNKNOWN: "unklar",
        }.get(self._availability)

    @property
    def borrowable(self) -> bool:
        return self._availability is Availability.AVAILABLE

    @property
    def seen(self) -> str | None:
        newest = self.newest
        if newest is None or newest.observed_at is None:
            return None
        return newest.observed_at.strftime("%d.%m. %H:%M")

    @property
    def candidates(self) -> tuple:
        """Die Ausgaben, die es sein koennten — leer, wenn alles klar ist.

        Entschieden wird **hier**, nicht auf einer eigenen Seite: der Titel,
        wie die Leserin ihn geschrieben hat, steht dann eine Zeile darueber,
        und genau der hilft beim Erkennen (Ticket 41).
        """
        for state in self.sources:
            if state.is_question and state.candidates:
                return state.candidates
        return ()

    @property
    def rejected(self) -> tuple:
        """Was schon abgelehnt wurde — zum Zuruecknehmen."""
        for state in self.sources:
            if state.is_question and state.rejected:
                return state.rejected
        return ()

    @property
    def needs_choice(self) -> bool:
        """Ob hier eine Entscheidung ansteht.

        Ein **pausierter** Eintrag fragt nicht: er wird nicht mehr geprueft,
        also ist seine Zuordnung auch keine offene Frage. Auf der eigenen
        Seite filterte das die Abfrage; in der Liste steht er weiter da, nur
        ausgegraut.
        """
        return self.active and bool(self.candidates)

    @property
    def choice_source(self) -> str | None:
        """Welche Quelle fragt — die Entscheidung gilt fuer sie."""
        state = self._asking
        return state.name if state else None

    @property
    def choice_label(self) -> str | None:
        """Wie diese Quelle der Leserin gegenueber heisst.

        Die Frage gilt einer Quelle, nicht dem Buch: derselbe Titel kann im
        Shop richtig zugeordnet sein und in der Bibliothek offen. Ohne den
        Namen las sich die Frage, als stuende das Buch ueberhaupt in Zweifel.
        """
        state = self._asking
        return state.display if state else None

    @property
    def _asking(self) -> SourceState | None:
        for state in self.sources:
            if state.is_question and state.candidates:
                return state
        return None

    @property
    def missing(self) -> bool:
        """Keine der geprueften Quellen kennt diesen Titel (ADR 27).

        `not_found` bleibt sonst eine Antwort und braucht niemanden — hier
        aber sagt es nichts ueber das Buch, sondern ueber die **Eingabe**.
        Gemessen am 6.9.: von neun so stehenden Titeln waren sieben schlicht
        falsch benannt, darunter ein Schnaeppchen zu 2,99 Euro, das einen Tag
        lang unsichtbar blieb.

        **Alle** Quellen, nicht eine: vierzehn von vierzehn Eintraegen stehen
        bei der Onleihe auf `not_found`, sie fuehrt die meisten nicht. Eine
        Meldung je Quelle haette jeden Titel jeden Tag gemeldet — genau der
        Fehler, den Ticket 04 vermieden hat.

        Ein pausierter Eintrag schweigt: er wird nicht mehr geprueft.
        """
        if not self.active or not self.sources:
            return False
        return all(state.outcome == LinkOutcome.NOT_FOUND for state in self.sources)

    @property
    def missing_known(self) -> bool:
        """Ob die Leserin diese Luecke schon weggeklickt hat.

        Gemerkt wird der **Titel**, nicht das Buch: wer nach einer
        Umbenennung wieder nichts findet, hoert eine neue Behauptung ueber
        eine neue Eingabe (ADR 27).
        """
        return self.known_missing == self.title

    @property
    def unresolved(self) -> bool:
        """Noch kein Lauf hat dieses Buch angesehen.

        Die Weboberfläche sucht nicht selbst (ADR 3) — sie schreibt die
        Beziehung, und der nächste Lauf löst auf.
        """
        return not self.sources


def _candidates(details: dict, url: str | None, *, rejected: bool) -> tuple:
    """Die Kandidaten aus einer ``book_source``-Zeile, geteilt in offen und
    abgelehnt."""
    from .assignments import Candidate, _cover_file

    rejected_urls = set(details.get("rejected") or [])
    raw_list = details.get("candidates")
    if not raw_list and details.get("matched_title"):
        # Rueckfall fuer Zeilen aus der Zeit vor der Kandidatenliste: sie
        # tragen nur den Sieger. Ohne das hoerten sie stillschweigend auf zu
        # fragen — der teuerste denkbare Weg, eine Entscheidung zu verlieren.
        raw_list = [
            {
                "title": details["matched_title"],
                "author": details.get("matched_author"),
                "url": url,
                "cover_url": None,
            }
        ]
    out = []
    for raw in raw_list or []:
        url = raw.get("url")
        is_rejected = bool(url) and url in rejected_urls
        if is_rejected is not rejected:
            continue
        out.append(
            Candidate(
                title=raw.get("title") or "ohne Titel",
                author=raw.get("author"),
                url=url,
                cover_file=_cover_file(raw.get("cover_url")),
                rejected=is_rejected,
            )
        )
    return tuple(out)


def _portrait_subjects(book, observations: Sequence[Observation]) -> list[str]:
    """Woran der Steckbrief dieses Buchs hängen kann, das Nächstliegende zuerst.

    Ein Buch kann bei mehreren Quellen stehen, und jeder Fund trägt seinen
    eigenen Schlüssel; ein Titel ohne Fund trägt seinen am Buch (#38). Dieselbe
    Auswahl wie auf der Buchseite.
    """
    subjects = [book_subject(book.id)]
    if book.isbn:
        subjects.insert(0, f"isbn:{book.isbn}")
    subjects.extend(subject_of(observation) for observation in observations)
    return subjects


def entries(
    store: Store,
    settings: Settings,
    *,
    include_paused: bool = True,
    sort: str | None = None,
) -> list[Entry]:
    """Die Watchlist, wie die Seite sie zeigt.

    ``sort`` ist der Schluessel aus der Adresse; was ihn nicht trifft, bekommt
    die Voreinstellung (:mod:`.sorting`).
    """
    profile_slug = settings.slug
    relations = store.relations(
        profile_slug, kind=str(RelationKind.WATCHING), active_only=not include_paused
    )
    # Wer nicht mehr beobachtet wird, steht nicht auf der Watchlist. Die
    # Beziehung bleibt trotzdem stehen — auf der Buchseite liest sie sich
    # danach als "Frueher: beobachtet" (ADR 18, Ticket 48).
    closed = {
        row.book_id
        for kind in (RelationKind.OWNED, RelationKind.DISMISSED)
        for row in store.relations(profile_slug, kind=str(kind))
    }
    relations = [row for row in relations if row.book_id not in closed]
    book_ids = [relation.book_id for relation in relations]
    latest = store.latest_by_book(profile_slug, book_ids)
    # Drei Abfragen fuer die ganze Liste statt zwei je Zeile: neunzehn
    # Eintraege kosteten so 9 der 25 ms, die diese Funktion braucht.
    books = store.books_by_id(book_ids)
    sources = store.book_sources_of(book_ids)
    # Das Urteil rechnet der Code aus dem Steckbrief (ADR 33, #48). Steckbriefe
    # hängen am *Fund* (ADR 18): an der ISBN, wo es eine gibt, sonst an der
    # Produktnummer, und ein Titel ohne Fund trägt seinen am Buch (#38). Ein
    # Zugriff für die ganze Liste, nicht einer je Zeile — dieselbe Regel wie im
    # Stapel.
    judge = load_judge(store, settings.slug)
    portraits = {}
    if judge is not None:
        portraits = judge.portraits(
            store,
            [
                subject
                for book_id in book_ids
                if (book := books.get(book_id)) is not None
                for subject in _portrait_subjects(book, latest.get(book_id, ()))
            ],
        )

    rows = []
    for relation in relations:
        book = books.get(relation.book_id)
        if book is None:  # pragma: no cover - nur bei geloeschtem Buch
            continue
        details = _details(relation)
        states = tuple(
            SourceState(
                name=link.source,
                outcome=_details(link).get("outcome", ""),
                url=link.url,
                matched_title=_details(link).get("matched_title"),
                matched_author=_details(link).get("matched_author"),
                reason=_details(link).get("reason", ""),
                category=registry.category(settings, link.source),
                display=registry.label(settings, link.source),
                candidates=_candidates(_details(link), link.url, rejected=False),
                rejected=_candidates(_details(link), link.url, rejected=True),
            )
            for link in sources.get(book.id, ())
        )
        verdict = (
            judge.verdict_among(portraits, _portrait_subjects(book, latest.get(book.id, ())))
            if judge is not None
            else None
        )
        rows.append(
            Entry(
                book_id=book.id,
                title=book.title,
                author=book.author,
                active=relation.active,
                restrict=details.get("restrict"),
                note=details.get("note"),
                cover_file=book.cover_file,
                added_at=relation.created_at,
                sources=states,
                latest=tuple(latest.get(book.id, ())),
                known_missing=details.get("known_missing"),
                stars=verdict.stars if verdict else None,
                percent=verdict.percent if verdict else None,
                pitch=(verdict.pitch or None) if verdict else None,
                # Der Preis der juengsten Quelle, die einen nennt — nicht der
                # der juengsten Beobachtung: eine Bibliothek nennt keinen, und
                # seit es zwei gibt, war das oft die neueste.
                deal=is_strong_deal(
                    next(
                        (
                            o.price_cents
                            for o in latest.get(book.id, ())
                            if o.price_cents is not None
                        ),
                        None,
                    ),
                    settings,
                ),
            )
        )
    # Die gewaehlte Reihenfolge gilt woertlich: auch offene Zuordnungen stehen
    # nach Preis sortiert mittendrin. Verloren gehen sie nicht — die Leiste
    # ueber der Liste nennt ihre Zahl und filtert auf genau sie (#37).
    return sorting.apply(sorting.WATCHLIST, rows, sort)


def add(store: Store, profile_slug: str, *, title: str, author: str | None, now: datetime) -> int:
    """Ein Buch auf die Watchlist setzen.

    Aufgelöst wird hier **nicht**: die Weboberfläche scrapt nie (ADR 3). Sie
    schreibt die Beziehung, der nächste Lauf sucht das Buch bei den Quellen.
    Bis dahin steht der Eintrag als „noch nicht gesucht“ da — sichtbar, statt
    so zu tun, als sei schon etwas passiert.
    """
    book = store.find_or_create_book(
        isbn=None, title=title.strip(), author=(author or "").strip() or None, now=now
    )
    store.put_relation(profile_slug, book.id, str(RelationKind.WATCHING), now=now)
    return book.id


@dataclass(frozen=True, slots=True)
class Undo:
    """Was die Seite zurückzunehmen anbietet."""

    book_id: int
    kind: str
    title: str

    @property
    def done(self) -> str:
        """Was geschehen ist, als Satz — nicht das Knopfwort. Dieselbe Tabelle
        wie auf der Startseite, damit dort und hier dasselbe dasteht."""
        return DONE_LABELS[self.kind]


def undo_for(store: Store, book_id: int, kind: str) -> Undo | None:
    """Nichts, wenn die Adresse etwas nennt, das es nicht gibt."""
    if kind not in (str(RelationKind.OWNED), str(RelationKind.DISMISSED)):
        return None
    book = store.book(book_id)
    return Undo(book_id, kind, book.title) if book is not None else None


def unfinish(
    store: Store, profile_slug: str, book_id: int, kind: str, *, now: datetime
) -> None:
    """Einen Abschluss zurücknehmen — die Umkehrung von :func:`finish`.

    Stillgelegt, nicht gelöscht (ADR 18): dass das Buch einmal als gekauft
    galt, bleibt als ruhende Zeile stehen.
    """
    if kind not in (str(RelationKind.OWNED), str(RelationKind.DISMISSED)):
        return
    store.deactivate_relation(profile_slug, book_id, kind, now=now)
    store.put_relation(profile_slug, book_id, str(RelationKind.WATCHING), now=now)


def finish(
    store: Store, profile_slug: str, book_id: int, kind: str, *, now: datetime
) -> None:
    """Einen Eintrag abschliessen: gekauft, oder nicht mehr interessant.

    Zwei Wirkungen in einem Vorgang, und das ist der ganze Punkt des Tickets:
    ``put_relation`` fasst immer nur **eine** Art an. Wer bisher auf der
    Buchseite "besitze ich" klickte, bekam ``owned`` dazu — ``watching`` blieb
    aktiv, das Buch wurde weiter abgerufen und weiter gemeldet. Genau der
    Fall, der bei *Ausloeschung* auffiel: ausgegraut und trotzdem als
    ausleihbar markiert (Ticket 48).

    Stillgelegt, nicht geloescht: dass ein Buch einmal beobachtet wurde, ist
    selbst eine Auskunft (ADR 18).
    """
    if kind not in (str(RelationKind.OWNED), str(RelationKind.DISMISSED)):
        return
    store.put_relation(profile_slug, book_id, kind, now=now)
    store.deactivate_relation(profile_slug, book_id, str(RelationKind.WATCHING), now=now)


def set_restriction(
    store: Store, profile_slug: str, book_id: int, restrict: str | None, *, now: datetime
) -> None:
    """Auf welche Art Quelle der Eintrag geprüft wird. ``None`` heißt: alle."""
    details = {}
    for relation in store.relations_of(profile_slug, book_id):
        if relation.kind == RelationKind.WATCHING:
            details = _details(relation)
            break
    details.pop("restrict", None)
    if restrict:
        details["restrict"] = restrict
    # Ersetzen, nicht ergaenzen: sonst liesse sich eine Einschraenkung setzen,
    # aber nie wieder aufheben.
    store.set_relation_details(
        profile_slug, book_id, str(RelationKind.WATCHING), details, now=now
    )
