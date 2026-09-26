"""Unklare Zuordnungen an einer Stelle entscheiden (Ticket 41).

Der Bestätigungsweg ist kein Randfall, sondern der Regelfall für schwierige
Titel — Open Library hält das Zusammenführen ausdrücklich manuell
(`docs/research/title-matching-practices.md`). Was fehlte, war nicht mehr
Automatik, sondern eine bequeme Stelle zum Bestätigen.

Sie ist eine eigene Seite und nicht ein Kasten unter dem Watchlist-Eintrag:
neun Zuordnungen zu bestätigen ist dieselbe Art Arbeit wie der
Vorschlagsstapel — viele Entscheidungen, in einem Durchgang. Die Watchlist
bleibt eine Liste von Büchern, keine Liste von Aufgaben.

Gezeigt werden die Kandidaten, die der Matcher **nicht auseinanderhalten**
konnte, mit ihrem Titelbild. Kein Preis: bei einer Bestätigung geht es um
Identität, nicht um ein Angebot — und eine Ablehnung soll halten, statt sich
auf einen Betrag von vorgestern zu beziehen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .. import paths
from ..config import Settings
from ..covers import CoverStore, file_name
from ..matching.bundles import looks_like_bundle, volume_titles
from ..models import LinkOutcome
from ..sources import registry
from ..store import Store


def _details(row) -> dict:
    try:
        return json.loads(row.details or "{}")
    except (TypeError, ValueError):  # pragma: no cover - defekte Zeile
        return {}


@dataclass(frozen=True, slots=True)
class Candidate:
    """Eine Ausgabe, die es sein könnte."""

    title: str
    author: str | None
    url: str | None
    cover_file: str | None
    rejected: bool = False

    @property
    def is_bundle(self) -> bool:
        return looks_like_bundle(self.title)

    @property
    def volumes(self) -> tuple[str, ...]:
        return volume_titles(self.title)


@dataclass(frozen=True, slots=True)
class Question:
    """Ein Watchlist-Titel, zu dem eine Quelle unsicher ist."""

    book_id: int
    title: str
    author: str | None
    source: str
    source_label: str
    reason: str
    candidates: tuple[Candidate, ...]
    rejected: tuple[Candidate, ...]

    @property
    def is_open(self) -> bool:
        return bool(self.candidates)


@dataclass(frozen=True, slots=True)
class Pile:
    questions: tuple[Question, ...]

    @property
    def open_count(self) -> int:
        return sum(1 for question in self.questions if question.is_open)

    @property
    def rejected_count(self) -> int:
        return sum(len(question.rejected) for question in self.questions)

    @property
    def is_empty(self) -> bool:
        return not self.questions


def _cover_file(url: str | None) -> str | None:
    """Der Dateiname, falls das Bild schon im Ordner liegt.

    Nachgesehen statt gespeichert — dieselbe Überlegung wie beim
    Vorschlagsstapel: der Name ergibt sich allein aus der Adresse, und die
    Oberfläche lädt nie selbst nach (ADR 3).
    """
    if not url:
        return None
    name = file_name(url)
    return name if CoverStore(paths.covers_dir()).has(name) else None


def _candidate(raw: dict, rejected: set[str]) -> Candidate:
    url = raw.get("url")
    return Candidate(
        title=raw.get("title") or "ohne Titel",
        author=raw.get("author"),
        url=url,
        cover_file=_cover_file(raw.get("cover_url")),
        rejected=bool(url) and url in rejected,
    )


def open_questions(store: Store, settings: Settings) -> Pile:
    """Alles, was auf eine Entscheidung wartet."""
    questions: list[Question] = []
    for row in store.unsure_links(settings.slug):
        details = _details(row)
        rejected = set(details.get("rejected") or [])
        all_candidates = [_candidate(raw, rejected) for raw in details.get("candidates") or []]
        book = store.book(row.book_id)
        if book is None:  # pragma: no cover - nur bei geloeschtem Buch
            continue
        questions.append(
            Question(
                book_id=row.book_id,
                title=book.title,
                author=book.author,
                source=row.source,
                source_label=registry.label(settings, row.source),
                reason=details.get("reason") or "",
                candidates=tuple(c for c in all_candidates if not c.rejected),
                rejected=tuple(c for c in all_candidates if c.rejected),
            )
        )
    return Pile(questions=tuple(questions))


def confirm(store: Store, book_id: int, source: str, url: str, now) -> None:
    """Eine Zuordnung von Hand festmachen.

    Das Ergebnis heißt ``confirmed`` statt ``linked`` — ein Mensch hat
    entschieden, keine Heuristik (ADR 9).

    Dabei erbt das Buch das Titelbild der gewählten Ausgabe. Es liegt schon auf
    der Platte — die Kandidatenkarte hat es gezeigt —, und ohne diesen Schritt
    stünde die Zeile bis zum nächsten Lauf mit einem Platzhalter da, obwohl das
    Bild bekannt ist. Geholt wird nichts (ADR 3): nachgesehen wird nur, ob die
    Datei da ist.
    """
    row = store.get_book_source(book_id, source)
    chosen = next(
        (
            candidate
            for candidate in (_details(row).get("candidates") or [] if row else [])
            if candidate.get("url") == url
        ),
        None,
    )
    store.put_book_source(
        book_id,
        source,
        outcome=str(LinkOutcome.CONFIRMED),
        url=url,
        resolved_at=now,
        reason="von Hand bestätigt",
        # Die gewaehlte Ausgabe behaelt ihre Sprache: eine englische bleibt
        # auf der Kachel als englisch gekennzeichnet (#77).
        **({"language": chosen["language"]} if chosen and chosen.get("language") else {}),
    )
    book = store.book(book_id)
    if book is not None and not book.cover_file and chosen:
        cover = _cover_file(chosen.get("cover_url"))
        if cover:
            store.set_cover(book_id, cover)


def reject_all(store: Store, book_id: int, source: str, now) -> None:
    """„Keiner davon" — und das hält.

    Abgelehnt wird die **gezeigte Gruppe**: dieselben Kandidaten kommen nicht
    wieder, ein neuer schon. Einen einzelnen abzulehnen gibt es nicht mehr —
    wählt man den richtigen, sind die anderen ohnehin erledigt (Ticket 41).
    """
    row = store.get_book_source(book_id, source)
    if row is None:
        return
    details = _details(row)
    urls = [raw.get('url') for raw in details.get('candidates') or [] if raw.get('url')]
    if not urls and row.url:
        # Zeilen aus der Zeit vor der Kandidatenliste tragen nur den Sieger.
        urls = [row.url]
    store.reject_candidates(book_id, source, urls)


def restore(store: Store, book_id: int, source: str, now) -> None:
    """Eine Ablehnung zurücknehmen.

    ``now`` bleibt in der Signatur, weil alle Entscheidungen dieser Seite
    denselben Zeitpunkt hereinreichen — gebraucht wird er hier nicht mehr
    (#39).
    """
    store.restore_candidates(book_id, source)
