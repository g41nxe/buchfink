"""Was das Werkzeug über die Leserin zu wissen glaubt (Ticket 09).

Ausdrücklich **nur lesend**. Das Leseprofil liegt als Repo-Datei mit eigenem
Änderungsverfahren und einer asymmetrischen Beweislast (ADR 17): ein Formular
hier würde genau dieses Verfahren umgehen. Die Seite zeigt ihn, verlinkt ihn
und nennt den Weg, auf dem er sich ändert.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import yaml

from ..config import Settings
from ..facets import (
    STRENGTHS,
    family_description,
    family_name,
    family_names,
    is_pattern,
    load_weights,
    strength,
)
from ..judging import load_judge
from ..portrait import VocabularyError, load_vocabulary
from ..reasons import thema_name
from ..relations import InterestKey, RelationKind, labelled
from ..store import Store
from .spider import Spider, reader_spiders

#: Wie oft der lange Ausläufer gefegt wird — dieselbe Frist, die der Lauf
#: benutzt. Hier nur zur Anzeige.
EXTENDED_SWEEP_KEY = "last_extended_sweep"
SWEEP_INTERVAL = timedelta(days=7)

_WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")

_RELATION_LABELS: tuple[tuple[str, str], ...] = labelled(
    RelationKind.WATCHING,
    RelationKind.OWNED,
    RelationKind.LIKED,
    RelationKind.DISLIKED,
    RelationKind.DISMISSED,
)


def _details(row) -> dict:
    try:
        return json.loads(row.details or "{}")
    except (TypeError, ValueError):  # pragma: no cover - defekte Zeile
        return {}


@dataclass(frozen=True, slots=True)
class Interest:
    value: str
    label: str
    tier: str
    active: bool

    @property
    def weekly(self) -> bool:
        return self.tier == "extended"


@dataclass(frozen=True, slots=True)
class Held:
    """Ein Buch, wie es in einer der Regale steht."""

    book_id: int
    title: str
    author: str | None


@dataclass(frozen=True, slots=True)
class Shelf:
    """Eine Beziehungsart mit den Buechern dahinter (Ticket 49).

    Bis dahin stand hier nur eine Zahl. Solange nichts die Watchlist verliess,
    reichte das; seit Ticket 48 verlaesst sie etwas, und ohne diesen Rueckweg
    waere ein Buch nach einem Klick auf "im Besitz" nur noch ueber seine
    Nummer zu finden.
    """

    kind: str
    label: str
    books: tuple[Held, ...]

    @property
    def count(self) -> int:
        return len(self.books)


@dataclass(frozen=True, slots=True)
class FacetLine:
    """Eine Facette oder ein Gegengewicht, wie die Profilseite sie zeigt (#50)."""

    name: str
    books: tuple[str, ...]
    #: Nur bei Facetten: die Stärke als Wort und als Stufe von 1 bis 4.
    strength: str | None = None
    level: int = 0
    #: Nur bei Gegengewichten.
    genre: str | None = None
    #: Nur bei Facetten: je Merkmal sein Name und der Satz, was es heißt.
    parts: tuple[tuple[str, str], ...] = ()
    #: Nur bei Gegengewichten: das Buch, an dem es sich zurücknehmen lässt (#51).
    book_id: int | None = None


@dataclass(frozen=True, slots=True)
class LikedLine:
    """Ein gemochtes Merkmal oder Erzählmuster, wie die Profilseite es zeigt."""

    name: str
    pattern: bool
    boosted: bool
    #: Ein gemochtes Buch, das es trägt: dort lässt es sich abwählen (#51). Die
    #: Profilseite selbst bleibt zum Lesen.
    book_id: int | None = None


@dataclass(frozen=True, slots=True)
class Overview:
    authors: tuple[Interest, ...]
    themen: tuple[Interest, ...]
    counts: tuple[Shelf, ...]
    strong_deal: str
    deal: str
    min_discount: int
    sweep_weekday: str
    last_sweep: datetime | None
    #: Ab wie vielen Sternen ein Vorschlag im Stapel bleibt (Bewertungsschema),
    #: oder ``None``, wenn das Schema nicht lesbar ist.
    gate_stars: int | None
    #: Die Fassung des Leseprofils aus Facetten (ADR 33), oder keine.
    facet_profile: int | None = None
    #: Wie viele Bücher in der Erstaufnahme schon genannt sind (#47).
    intake_named: int = 0
    facets: tuple[FacetLine, ...] = ()
    counterweights: tuple[FacetLine, ...] = ()
    #: Die gemochten Merkmale und Erzählmuster, jedes für sich — verstärkt zuerst.
    liked: tuple[LikedLine, ...] = ()
    #: Die Geschmacksform als Spinnen, Merkmale und Erzählmuster (#79).
    spiders: tuple[Spider, ...] = ()

    @property
    def next_sweep(self) -> str:
        """Wann der wöchentliche Durchgang wieder ansteht.

        Ein Lauf, der nie stattfand, darf keine ganze Woche kosten — deshalb
        ist ein überfälliger Sweep sofort fällig, nicht erst am Wochentag
        (ADR 4). Die Anzeige sagt das genauso.
        """
        if self.last_sweep is None:
            return "beim nächsten Lauf"
        due = self.last_sweep + SWEEP_INTERVAL
        if due <= datetime.now():
            return "überfällig — beim nächsten Lauf"
        return f"{self.sweep_weekday}, frühestens {due:%d.%m.}"


def _money(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")


def build(store: Store, settings: Settings) -> Overview:
    rows = store.interests(settings.slug, active_only=False)

    def collect(key: InterestKey) -> tuple[Interest, ...]:
        return tuple(
            Interest(
                value=row.value,
                label=thema_name(row.value) or row.value
                if key is InterestKey.THEMA
                else row.value,
                tier=_details(row).get("tier", "core"),
                active=row.active,
            )
            for row in rows
            if row.key == key
        )

    # Nicht nur die Zahl, sondern die Buecher dahinter: was Ticket 48 aus der
    # Watchlist entfernt, war sonst nur ueber die Buch-Adresse zu finden, und
    # die muss man kennen (Ticket 49).
    #
    # Nur lesen. Die fuenf Knoepfe stehen auf der Buchseite, und eine dritte
    # Stelle, an der Beziehungen geschrieben werden, waere eine zu viel.
    #
    # Ohne Titelbild: von 53 Buechern haben 13 eine Bilddatei, eine Bildliste
    # bestuende zu drei Vierteln aus Platzhaltern.
    counts = tuple(
        Shelf(
            kind=kind,
            label=label,
            books=tuple(
                Held(book_id=book.id, title=book.title, author=book.author)
                for row in store.relations(settings.slug, kind=kind)
                if (book := store.book(row.book_id)) is not None
            ),
        )
        for kind, label in _RELATION_LABELS
    )

    try:
        gate_stars = load_weights().gate_stars
    except (OSError, KeyError, ValueError, yaml.YAMLError):
        gate_stars = None

    facets, counterweights, liked = _facet_profile(store, settings)
    judge = load_judge(store, settings.slug)
    spiders = (
        tuple(s for s in reader_spiders(judge.form, judge.vocabulary) if s is not None)
        if judge is not None and judge.form is not None
        else ()
    )

    return Overview(
        authors=collect(InterestKey.AUTHOR),
        themen=collect(InterestKey.THEMA),
        counts=counts,
        strong_deal=_money(settings.strong_deal_max_cents),
        deal=_money(settings.deal_max_cents),
        min_discount=settings.min_discount_pct,
        sweep_weekday=_WEEKDAYS[settings.extended_sweep_weekday % 7],
        last_sweep=store.get_state(settings.slug, EXTENDED_SWEEP_KEY),
        gate_stars=gate_stars,
        facet_profile=(
            profile.version if (profile := store.reading_profile(settings.slug)) else None
        ),
        intake_named=len(store.intake_entries(settings.slug)),
        facets=facets,
        counterweights=counterweights,
        liked=liked,
        spiders=spiders,
    )


def _facet_profile(store: Store, settings: Settings):
    """Das Leseprofil aus Facetten, lesbar gemacht — oder nichts."""
    profile = store.reading_profile(settings.slug)
    if profile is None:
        return (), (), ()
    try:
        vocabulary = load_vocabulary()
    except VocabularyError:
        return (), (), ()
    # Die Stärke ist abgeleitet, nicht gespeichert (#51, ADR 16): gezählt
    # werden die gemochten Bücher, die die Facette heute tragen. Gespeichert
    # sind nur die Bücher, aus denen sie entstand — sie zählen, solange ihr
    # Steckbrief fehlt.
    from .intake import defining_in
    from .sharpening import carried_by, liked_shelf

    shelf = liked_shelf(store, settings, vocabulary)

    def facet_line(f) -> FacetLine:
        carriers = carried_by(f.families, shelf)
        titles = tuple(b.title for b in carriers) or f.books
        word = strength(len(titles), defining_in(f.families, carriers))
        return FacetLine(
            family_names(f.families, vocabulary), titles, strength=word,
            level=STRENGTHS.index(word) + 1,
            parts=tuple(
                (family_name(x, vocabulary), family_description(x, vocabulary))
                for x in f.families
            ),
        )

    facets = tuple(facet_line(f) for f in profile.facets)
    # Wo sich etwas ändern lässt: am Buch, nie hier (#51).
    disliked_by_title = {}
    for relation in store.relations(settings.slug, kind=str(RelationKind.DISLIKED)):
        book = store.book(relation.book_id)
        if book is not None:
            disliked_by_title.setdefault(book.title, book.id)
    counterweights = tuple(
        FacetLine(
            family_names(c.families, vocabulary), c.books, genre=c.genre,
            book_id=next((disliked_by_title[t] for t in c.books if t in disliked_by_title),
                         None),
        )
        for c in profile.counterweights
    )
    liked = tuple(
        LikedLine(
            family_name(g.family, vocabulary), is_pattern(g.family, vocabulary), g.boosted,
            book_id=next((b.book_id for b in shelf if g.family in b.families), None),
        )
        for g in sorted(profile.liked, key=lambda g: not g.boosted)
    )
    return facets, counterweights, liked
