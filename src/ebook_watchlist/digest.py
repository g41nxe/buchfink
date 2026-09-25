"""The Digest model — one structured object, two renderers (ADR 15).

Sections are fixed and ordered; empty ones are dropped. The error section is
always last and is enough on its own to make a Digest worth emitting: a broken
scraper must never look like a quiet day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .config import Settings
from .deals import deal_flags
from .judging import Verdict
from .junk import SHORT_STORY_PAGES
from .models import Attention, Delta, DeltaKind, MatchReason, SourceFailure
from .reasons import why_shown

SECTION_LIBRARY = "Bibliothek"
SECTION_PRICES = "Watchlist — Preise"
SECTION_AUTHORS = "Neue Titel deiner Autor:innen"
SECTION_GENRE = "Genre-Vorschläge (unsicher)"
SECTION_ATTENTION = "Braucht Aufmerksamkeit"
SECTION_ERRORS = "⚠️ Fehler"

SECTION_ORDER: tuple[str, ...] = (
    SECTION_LIBRARY,
    SECTION_PRICES,
    SECTION_AUTHORS,
    SECTION_GENRE,
    SECTION_ATTENTION,
    SECTION_ERRORS,
)


@dataclass(frozen=True, slots=True)
class DigestEntry:
    title: str
    author: str | None = None
    detail: str | None = None
    flags: tuple[str, ...] = ()
    url: str | None = None
    #: Das Urteil des Bewertungstors, ausgeschrieben. Gespeichert und nie
    #: gezeigt war es nachprüfbar für niemanden (ADR 19, Ticket 20).
    judgement: str | None = None
    #: Der Kurztext aus dem Steckbrief — warum dieses Buch, in einem Satz.
    pitch: str | None = None


@dataclass(frozen=True, slots=True)
class DigestSection:
    title: str
    entries: tuple[DigestEntry, ...]


@dataclass(frozen=True, slots=True)
class GateNote:
    """Was das Bewertungstor zurückgehalten hat — im Digest, nicht auf stderr.

    Ein zu scharf gesetzter Schwellwert sieht sonst aus wie ein ruhiger Tag,
    und ein Cron-Job wirft stderr weg (ADR 19, Ticket 20).
    """

    held_back: int = 0
    threshold: int = 0
    #: Über dem Budget: nicht bewertet, aber gezeigt.
    over_budget: int = 0
    #: Kein Urteil möglich — der `Portrayer` kam nicht durch (kein Schlüssel, keine
    #: Anmeldung, eine Zeitüberschreitung, eine unlesbare Antwort) oder das Buch
    #: ist dem Modell unbekannt. Das Buch wird gezeigt, und **das muss
    #: dastehen**: ein Tor, das für jedes Buch scheitert, sieht sonst aus wie
    #: ein Tag ohne Rückhalt statt wie ein Defekt.
    unrated: int = 0
    #: Es gibt noch kein Leseprofil: nichts wurde geurteilt (ADR 33, Punkt 8).
    no_profile: bool = False
    #: Kurzgeschichten nach dem Umfang der Detailseite (#73): nicht gezeigt.
    short_stories: int = 0

    @property
    def is_worth_saying(self) -> bool:
        return bool(
            self.held_back or self.over_budget or self.unrated or self.no_profile
            or self.short_stories
        )

    @property
    def text(self) -> str:
        """Eine Stelle für die Formulierung, damit Text und HTML dasselbe sagen."""
        parts = []
        if self.held_back:
            noun = "Vorschlag" if self.held_back == 1 else "Vorschläge"
            parts.append(
                f"{self.held_back} {noun} unter {self.threshold} Sternen zurückgehalten"
            )
        if self.over_budget:
            parts.append(
                f"{self.over_budget} heute nicht bewertet (Budget erschöpft) "
                "und deshalb ungeprüft gezeigt"
            )
        if self.unrated:
            parts.append(
                f"{self.unrated} konnten nicht bewertet werden und werden "
                "ungeprüft gezeigt"
            )
        if self.no_profile:
            parts.append(
                "noch kein Leseprofil, Vorschläge unbewertet — "
                "erst die Erstaufnahme machen"
            )
        if self.short_stories:
            noun = "Kurzgeschichte" if self.short_stories == 1 else "Kurzgeschichten"
            parts.append(
                f"{self.short_stories} {noun} (unter {SHORT_STORY_PAGES} Seiten) nicht gezeigt"
            )
        return "Bewertungstor: " + ", ".join(parts)


@dataclass(frozen=True, slots=True)
class Digest:
    profile_name: str
    generated_at: datetime
    since: datetime | None
    sections: tuple[DigestSection, ...] = field(default_factory=tuple)
    gate: GateNote | None = None

    @property
    def is_empty(self) -> bool:
        # Ein Digest, der nur sagt "zwölf Vorschläge zurückgehalten", ist kein
        # leerer: genau dann muss die Leserin merken, dass das Tor arbeitet.
        if self.gate is not None and self.gate.is_worth_saying:
            return False
        return not self.sections

    @property
    def headline(self) -> str:
        if self.since is None:
            return "Erster Check"
        return f"Änderungen seit letztem Check {self.since:%d.%m.%Y %H:%M}"


def _format_price(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"{cents / 100:.2f} €".replace(".", ",")


_SECTION_BY_REASON = {
    MatchReason.WATCHLIST: SECTION_PRICES,
    MatchReason.PROFILE_AUTHOR: SECTION_AUTHORS,
    MatchReason.GENRE_CATEGORY: SECTION_GENRE,
}


def _judgement_text(verdict: Verdict | None) -> str | None:
    return verdict.text if verdict is not None else None


def _entry_for(
    delta: Delta,
    settings: Settings | None,
    judgements: dict[tuple[str, str], Verdict],
    advantage_of=None,
) -> tuple[str, DigestEntry]:
    current, previous = delta.current, delta.previous

    if delta.kind is DeltaKind.BECAME_AVAILABLE:
        detail = "jetzt verfügbar"
        if previous and previous.reservation_count:
            detail += f" (zuvor {previous.reservation_count} Vormerkungen)"
        return SECTION_LIBRARY, DigestEntry(
            title=current.title, author=current.author, detail=detail, url=current.url
        )

    if delta.kind is DeltaKind.FIRST_SEEN:
        # Der Anlass zuerst, der Preis danach: die alte Reihenfolge las sich,
        # als sei der Preis der Grund (Ticket 14).
        detail = why_shown(current)
        price = _format_price(current.price_cents)
        if price != "—":
            detail += f" · {price}"
    elif delta.kind is DeltaKind.PRICE_DROP and previous is not None:
        detail = f"{_format_price(previous.price_cents)} → {_format_price(current.price_cents)}"
    else:
        raise ValueError(f"no Digest section defined for delta kind {delta.kind!r}")

    # Warum eine Sammelausgabe hier steht, sagt sonst niemand: sie ist weder
    # ein Schnäppchen noch ein Preissturz, sondern billiger als ihre
    # Einzelbände zusammen (ADR 24). Ohne diesen Satz stünde im Tagesbericht
    # ein Titel zu 19,99 € ohne erkennbaren Grund.
    vorteil = advantage_of(current) if advantage_of else None
    if vorteil is not None:
        detail = f"{vorteil.summary} · {detail}"

    section = _SECTION_BY_REASON[current.match_reason]
    flags = deal_flags(current, previous, settings) if settings else ()
    return section, DigestEntry(
        title=current.title,
        author=current.author,
        detail=detail,
        flags=flags,
        url=current.url,
        judgement=_judgement_text(judgements.get(current.key)),
        pitch=(verdict.pitch if (verdict := judgements.get(current.key)) else None),
    )


def build_digest(
    *,
    profile_name: str,
    generated_at: datetime,
    since: datetime | None,
    deltas: list[Delta],
    failures: list[SourceFailure],
    attention: list[Attention] | None = None,
    settings: Settings | None = None,
    judgements: dict[tuple[str, str], Verdict] | None = None,
    gate: GateNote | None = None,
    advantage_of=None,
) -> Digest:
    buckets: dict[str, list[DigestEntry]] = {title: [] for title in SECTION_ORDER}
    judgements = judgements or {}

    for delta in deltas:
        section, entry = _entry_for(delta, settings, judgements, advantage_of)
        buckets[section].append(entry)

    for item in attention or []:
        detail = f"{item.source}: {item.reason}"
        if item.best_guess:
            detail += f" — bester Treffer: „{item.best_guess}“"
        buckets[SECTION_ATTENTION].append(
            DigestEntry(
                title=item.entry_title,
                author=item.entry_author,
                detail=detail,
                url=item.best_guess_url,
            )
        )

    for failure in failures:
        buckets[SECTION_ERRORS].append(
            DigestEntry(title=failure.source, detail=failure.message)
        )

    sections = tuple(
        DigestSection(title=title, entries=tuple(buckets[title]))
        for title in SECTION_ORDER
        if buckets[title]
    )
    return Digest(
        profile_name=profile_name,
        generated_at=generated_at,
        since=since,
        sections=sections,
        gate=gate,
    )
