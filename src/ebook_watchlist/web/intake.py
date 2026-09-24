"""Die Erstaufnahme: Bücher nennen und bestätigen (#47), dann das Gemeinsame,
das Verlorene und das Profil (#50).

Eine Leserin ohne Profil nennt drei bis fünf Bücher, die sie geliebt hat, und
bis zu fünf, die sie enttäuscht haben (ADR 33, Punkt 6). Der Titel genügt: im
Hintergrund legt das Modell den Steckbrief an und erkennt dabei, welches Buch
gemeint ist, auch bei einem Tippfehler oder einem deutschen Titel. Die Leserin
bestätigt jeden Vorschlag; erst dann wird aus dem Eintrag ein Buch im Regal.

Es gibt keine Vorgeschichte: kein Klappentext, kein Eintrag im Bestand. Der
Steckbrief hängt deshalb zunächst an der Eingabe selbst und zieht beim
Bestätigen zum Buch um.

Danach fragt die Erstaufnahme nur geschlossen (ADR 33, Punkt 6): Bildschirm 3
zeigt als eine Liste, was mehrere geliebte Bücher tragen — nicht nach Büchern
gruppiert —, Bildschirm 4 das der enttäuschenden. Aus dem Angetippten bündelt
das Werkzeug unsichtbar die Facetten; bestätigt wird es als erste Fassung.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime

from ..config import Settings
from ..facets import (
    GENERAL,
    HERE,
    MIN_FAMILIES,
    STRENGTHS,
    Counterweight,
    Facet,
    ReadingProfile,
    ScopeError,
    derive_facets,
    families_of,
    family_name,
    family_names,
    merge_counterweights,
    scoped_counterweight,
    strength,
    uncovered,
)
from ..portrait import (
    Portrait,
    VocabularyError,
    fingerprint,
    load_vocabulary,
    portray,
)
from ..rating import RatingUnavailable, build_rater
from ..relations import RelationKind
from ..store import Store
from .book import _stored_portrait as stored_portrait
from .book import portrait_subject

#: Die beiden Seiten, in der Reihenfolge der Seite, mit ihren Grenzen.
SIDES: dict[str, tuple[int, int]] = {
    str(RelationKind.LIKED): (3, 5),
    str(RelationKind.DISLIKED): (0, 5),
}

OPEN, CONFIRMED, REMOVED = "open", "confirmed", "removed"


class IntakeError(ValueError):
    """Eine Eingabe, die die Erstaufnahme nicht annimmt."""


def intake_subject(title: str, author: str | None) -> str:
    """Woran der Steckbrief einer Eingabe hängt, bevor es ein Buch gibt.

    Aus der Eingabe selbst gebildet: dieselbe Eingabe findet denselben
    Steckbrief wieder und kostet keinen zweiten Aufruf (ADR 33, Punkt 3).
    """
    return f"intake:{title.strip().casefold()}|{(author or '').strip().casefold()}"


@dataclass(frozen=True, slots=True)
class Entry:
    """Ein genannter Titel und was aus ihm geworden ist."""

    id: int
    side: str
    typed_title: str
    typed_author: str | None
    #: ``asking`` (das Modell arbeitet), ``proposed``, ``unknown`` oder
    #: ``confirmed``.
    state: str
    title: str | None = None
    author: str | None = None
    #: Nur, wenn er anders lautet als der Titel.
    original_title: str | None = None
    genre: str | None = None
    book_id: int | None = None


@dataclass(frozen=True, slots=True)
class Side:
    kind: str
    entries: tuple[Entry, ...]
    fewest: int
    most: int

    @property
    def confirmed(self) -> int:
        return sum(e.state == "confirmed" for e in self.entries)

    @property
    def full(self) -> bool:
        return len(self.entries) >= self.most


@dataclass(frozen=True, slots=True)
class Page:
    liked: Side
    disliked: Side

    @property
    def ready(self) -> bool:
        """Genug geliebte Bücher bestätigt, und keines wartet mehr auf Antwort."""
        return self.liked.confirmed >= self.liked.fewest and not any(
            e.state in ("asking", "proposed") for e in (*self.liked.entries, *self.disliked.entries)
        )


def _stored(store: Store, row) -> Portrait | None:
    try:
        abdruck = fingerprint(load_vocabulary())
    except VocabularyError:
        return None
    return store.portrait(intake_subject(row.typed_title, row.typed_author), abdruck)


def entry(store: Store, row) -> Entry:
    """Ein Eintrag, wie die Seite ihn zeigt."""
    if row.status == CONFIRMED:
        buch = store.book(row.book_id) if row.book_id else None
        return Entry(
            row.id, row.side, row.typed_title, row.typed_author, "confirmed",
            title=buch.title if buch else row.typed_title,
            author=buch.author if buch else row.typed_author,
            book_id=row.book_id,
        )
    bild = _stored(store, row)
    if bild is None:
        return Entry(row.id, row.side, row.typed_title, row.typed_author, "asking")
    if not bild.known:
        return Entry(row.id, row.side, row.typed_title, row.typed_author, "unknown")
    titel = bild.title or row.typed_title
    original = bild.original_title
    if original and original.strip().casefold() == titel.strip().casefold():
        original = None
    return Entry(
        row.id, row.side, row.typed_title, row.typed_author, "proposed",
        title=titel, author=bild.author, original_title=original, genre=bild.genre,
    )


def build(store: Store, settings: Settings) -> Page:
    eintraege = [entry(store, row) for row in store.intake_entries(settings.slug)]
    seiten = {
        kind: Side(kind, tuple(e for e in eintraege if e.side == kind), *grenzen)
        for kind, grenzen in SIDES.items()
    }
    return Page(liked=seiten[str(RelationKind.LIKED)], disliked=seiten[str(RelationKind.DISLIKED)])


def add(
    store: Store, settings: Settings, side: str, title: str, author: str | None, *, now: datetime
) -> int:
    """Einen Titel aufnehmen — sofort gespeichert, gefragt wird danach."""
    if side not in SIDES:
        raise IntakeError(f"unbekannte Seite {side!r}")
    title, author = title.strip(), (author or "").strip() or None
    if not title:
        raise IntakeError("Ohne Titel lässt sich nichts suchen.")
    genannt = [row for row in store.intake_entries(settings.slug) if row.side == side]
    if len(genannt) >= SIDES[side][1]:
        raise IntakeError(f"Höchstens {SIDES[side][1]} Bücher auf dieser Seite.")
    return store.add_intake_entry(settings.slug, side, title, author, now=now)


def identify(store: Store, settings: Settings, entry_id: int, *, now: datetime) -> str:
    """Das Modell fragen, welches Buch gemeint ist — die Arbeit im Hintergrund.

    Gibt zurück, was schiefging, oder nichts. Gespeichert wird nur eine
    Antwort; ein Fehler lässt den Eintrag offen, und er wird erneut gefragt.
    """
    row = store.intake_entry(entry_id)
    if row is None or row.status != OPEN:
        return ""
    try:
        vocabulary = load_vocabulary()
    except VocabularyError as exc:
        return str(exc)
    subject = intake_subject(row.typed_title, row.typed_author)
    if store.portrait(subject, fingerprint(vocabulary)) is not None:
        return ""
    rater = build_rater(settings.rating_model)
    if rater is None:
        return "Kein Bewerter eingerichtet: ohne Modell lässt sich kein Buch erkennen."
    try:
        bild = portray(row.typed_title, row.typed_author, None, rater.ask, vocabulary)
    except RatingUnavailable as exc:
        return str(exc)
    store.put_portrait(subject, bild, now=now)
    return ""


def retype(store: Store, entry_id: int, title: str, author: str | None) -> None:
    """„Anderes Buch": die Leserin gibt es genauer ein, und es wird neu gefragt."""
    row = store.intake_entry(entry_id)
    title = title.strip()
    if row is None or row.status != OPEN:
        raise IntakeError("Diesen Eintrag gibt es nicht mehr.")
    if not title:
        raise IntakeError("Ohne Titel lässt sich nichts suchen.")
    store.update_intake_entry(
        entry_id, typed_title=title, typed_author=(author or "").strip() or None
    )


def remove(store: Store, settings: Settings, entry_id: int, *, now: datetime) -> None:
    """Einen Eintrag aus der Erstaufnahme nehmen — auch einen bestätigten.

    Ein bestätigtes Buch trägt danach nichts mehr bei, und die Beziehung, die
    die Erstaufnahme gesetzt hat (*Mag ich* oder *Doof*), wird stillgelegt,
    nicht gelöscht (ADR 18). Das Buch selbst bleibt.
    """
    row = store.intake_entry(entry_id)
    if row is None:
        return
    if row.status == CONFIRMED and row.book_id is not None:
        store.put_relation(settings.slug, row.book_id, row.side, active=False, now=now)
    store.update_intake_entry(entry_id, status=REMOVED)


def confirm(store: Store, settings: Settings, entry_id: int, *, now: datetime) -> int:
    """Ja, dieses Buch: es kommt mit seinem Steckbrief ins Regal.

    Das Buch wird unter dem erkannten Titel angelegt, nicht unter dem
    getippten — sonst stünde "Ted Williams" im Regal. Der Steckbrief zieht zum
    Buch um, damit die Buchseite ihn findet, ohne ein zweites Mal zu fragen.
    """
    row = store.intake_entry(entry_id)
    if row is None or row.status != OPEN:
        raise IntakeError("Diesen Eintrag gibt es nicht mehr.")
    bild = _stored(store, row)
    if bild is None or not bild.known:
        raise IntakeError("Zu diesem Eintrag gibt es noch keinen Vorschlag.")
    buch = store.find_or_create_book(
        isbn=None, title=bild.title or row.typed_title, author=bild.author, now=now
    )
    store.put_portrait(portrait_subject(buch), bild, now=now)
    store.put_relation(settings.slug, buch.id, row.side, active=True, now=now)
    store.update_intake_entry(entry_id, status=CONFIRMED, book_id=buch.id)
    return buch.id


# --- Bildschirme 3 bis 5: das Gemeinsame, das Verlorene, dein Profil (#50) ------

LOVED, LOST = "loved", "lost"

#: Ab wie vielen Büchern der neutrale Bestand etwas über Häufigkeit sagt, und
#: ab welchem Anteil eine Familie als häufig gilt. Vorläufig; darunter wird
#: nicht sortiert (#44).
NEUTRAL_MIN_BOOKS = 30
FREQUENT_SHARE = 0.4


@dataclass(frozen=True, slots=True)
class ShelfBook:
    """Ein bestätigtes Buch der Erstaufnahme mit seinen Familien."""

    key: str
    book_id: int
    title: str
    genre: str | None
    #: Familie → der Satz aus dem Steckbrief, der sie an diesem Buch zeigt.
    families: dict[str, str]
    #: Familie → das Merkmal, über das das Buch sie trägt.
    terms: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Pill:
    family_id: str
    name: str
    pattern: bool
    frequent: bool
    on: bool
    #: Nur auf Bildschirm 4: an welchem Buch.
    book_id: int | None = None


@dataclass(frozen=True, slots=True)
class Group:
    """Familien, die dieselben Bücher tragen, unter einer Überschrift.

    Die Überschrift in drei Teilen, damit die Titel in Serifen stehen können:
    „Weil du" · *Leichenblässe* und *Kruzifix Killer* · „mochtest".
    """

    lead: str
    titles: tuple[str, ...]
    tail: str
    pills: tuple[Pill, ...]
    #: Je Familie die Sätze aus den Steckbriefen — für „warum?".
    why: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: Nur auf Bildschirm 4: ob ein geliebtes Buch sie auch trägt.
    conflict: bool = False


@dataclass(frozen=True, slots=True)
class ScopeQuestion:
    """Die Nachfrage bei einem Gegengewicht, das ein geliebtes Buch auch trägt."""

    family_id: str
    name: str
    book_id: int
    scope: str
    genre: str | None
    #: Welche geliebten Bücher dasselbe tragen — der Grund für die Nachfrage,
    #: und die eine Stelle auf Bildschirm 4, an der ein Buch genannt wird.
    also_in: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Card:
    """Ein Merkmal oder Erzählmuster auf Bildschirm 3, als Karte.

    Name, ein Satz, was es heißt, wie stark es bei der Leserin vertreten ist,
    und aufklappbar die Belege — je Buch der Satz aus dem Steckbrief. Bücher
    stehen nur dort, als Beleg, nicht als Gruppe (24.09.2026).
    """

    pill: Pill
    description: str
    strength: str
    evidence: tuple[tuple[str, str], ...]

    @property
    def level(self) -> int:
        return STRENGTHS.index(self.strength) + 1


@dataclass(frozen=True, slots=True)
class LostBook:
    title: str
    book_id: int
    groups: tuple[Group, ...]
    questions: tuple[ScopeQuestion, ...]


@dataclass(frozen=True, slots=True)
class FacetCard:
    families: tuple[str, ...]
    name: str
    strength: str
    books: tuple[str, ...]

    @property
    def level(self) -> int:
        """Die Stärke als Stufe von 1 bis 4, für die Skala."""
        return STRENGTHS.index(self.strength) + 1

    @property
    def too_broad(self) -> bool:
        return len(self.families) < MIN_FAMILIES

    @property
    def key(self) -> str:
        """Woran das Formular sie wiedererkennt — nicht an ihrer Stelle."""
        return ",".join(self.families)


@dataclass(frozen=True, slots=True)
class WeightCard:
    families: tuple[str, ...]
    name: str
    genre: str | None
    books: tuple[str, ...]

    @property
    def key(self) -> str:
        return ",".join(self.families) + "|" + (self.genre or "")


@dataclass(frozen=True, slots=True)
class Uncovered:
    """Ein geliebtes Buch, das in keiner Facette steckt — gezielt gefragt."""

    title: str
    pills: tuple[Pill, ...]


@dataclass(frozen=True, slots=True)
class Draft:
    """Das Profil, wie es aus den Antworten gerade entsteht."""

    facets: tuple[FacetCard, ...]
    weights: tuple[WeightCard, ...]
    #: Nur bei diesem Buch gestört — zählt nicht, steht aber da.
    only_here: tuple[str, ...]
    uncovered: tuple[Uncovered, ...]

    @property
    def counted(self) -> tuple[FacetCard, ...]:
        return tuple(f for f in self.facets if not f.too_broad)


@dataclass(frozen=True, slots=True)
class Choosing:
    """Was Bildschirm 3 und 4 zeigen, und das Profil darunter."""

    loved: tuple[ShelfBook, ...]
    #: Bildschirm 3: alle Merkmale der geliebten Bücher, gerankt — nicht nach
    #: Büchern gruppiert. Daraus bündelt das Werkzeug die Facetten.
    terms: tuple[Card, ...]
    #: Bildschirm 3, für sich: alle Erzählmuster der geliebten Bücher.
    patterns: tuple[Card, ...]
    lost: tuple[LostBook, ...]
    draft: Draft


def shelf_book(store: Store, vocabulary, book_id: int) -> ShelfBook | None:
    """Ein Buch mit den Familien aus seinem Steckbrief — oder nichts, wenn es
    keinen gibt oder das Modell das Buch nicht kennt."""
    buch = store.book(book_id)
    bild = stored_portrait(store, buch, fingerprint(vocabulary)) if buch else None
    if bild is None or not bild.known:
        return None
    familien: dict[str, str] = {}
    begriffe: dict[str, str] = {}
    for trait in bild.traits:
        if trait.term in vocabulary.terms:
            familie = vocabulary.family_of(trait.term).id
            familien.setdefault(familie, trait.sentence)
            begriffe.setdefault(familie, trait.term)
    # Fein genug für ein Gegengewicht mit Genre: "High Fantasy" statt
    # "Fantasy", sonst träfe es auch Grimdark (#44).
    genre = bild.subgenre.split("/")[0].strip() if bild.subgenre else bild.genre
    return ShelfBook(str(buch.id), buch.id, buch.title, genre, familien, begriffe)


def _shelf_books(store: Store, settings: Settings, vocabulary, side: str) -> list[ShelfBook]:
    """Die bestätigten Bücher einer Seite dieser Erstaufnahme."""
    buecher = (
        shelf_book(store, vocabulary, row.book_id)
        for row in store.intake_entries(settings.slug)
        if row.side == side and row.status == CONFIRMED and row.book_id is not None
    )
    return [b for b in buecher if b is not None]


def frequent_families(store: Store, settings: Settings, vocabulary) -> set[str]:
    """Familien, die auf dem neutralen Bestand bei sehr vielen Büchern stehen.

    Gemessen nie an den eigenen Büchern der Leserin: dort stehen "hart" und
    "gezeichnete Figur" oft, weil sie solche Bücher liebt, und das abzuwerten
    hieße, ihren Geschmack zu bestrafen (#44). Ohne genug neutralen Bestand
    wird nicht sortiert.
    """
    # Ein Abruf für alle Bücher statt einer Abfrage je Beziehung: das läuft
    # bei jedem Tipp auf Bildschirm 3 und 4.
    mit_beziehung = {row.book_id for row in store.relations(settings.slug, active_only=False)}
    eigene = {
        subject
        for buch in store.books()
        if buch.id in mit_beziehung
        for subject in (portrait_subject(buch), f"book:{buch.id}")
    }
    bestand = [
        bild
        for subject, bild in store.latest_portraits(fingerprint(vocabulary)).items()
        if bild.known and not subject.startswith("intake:") and subject not in eigene
    ]
    if len(bestand) < NEUTRAL_MIN_BOOKS:
        return set()
    zaehler = Counter(f for bild in bestand for f in families_of(bild, vocabulary))
    return {f for f, n in zaehler.items() if n / len(bestand) >= FREQUENT_SHARE}


def choosing(store: Store, settings: Settings) -> Choosing:
    """Die Bildschirme 3 und 4 mit allem, was die Leserin angetippt hat."""
    vocabulary = load_vocabulary()
    geliebt = _shelf_books(store, settings, vocabulary, str(RelationKind.LIKED))
    enttaeuscht = _shelf_books(store, settings, vocabulary, str(RelationKind.DISLIKED))
    haeufig = frequent_families(store, settings, vocabulary)
    wahl = store.intake_choices(settings.slug)
    an = {c.family_id for c in wahl if c.side == LOVED}
    weg = {(c.family_id, c.book_id): c.scope for c in wahl if c.side == LOST}

    def pille(f: str, on: bool, book_id: int | None = None) -> Pill:
        return Pill(
            f, family_name(f, vocabulary), vocabulary.is_pattern(f), f in haeufig, on, book_id
        )

    def ordnung(fs):
        # Häufiges ans Ende, ausgeblendet wird nichts (#44).
        return sorted(fs, key=lambda f: (f in haeufig, family_name(f, vocabulary).casefold()))

    traeger: dict[str, list[ShelfBook]] = {}
    for b in geliebt:
        for f in b.families:
            traeger.setdefault(f, []).append(b)

    # Bildschirm 3: alles, was die geliebten Bücher tragen, gerankt — nicht
    # nach Büchern gruppiert. Die Gruppen „Weil du A und B mochtest" lasen
    # sich wie Vergleiche von Buch zu Buch (24.09.2026). Gerankt wird vorerst
    # nach der Zahl der Bücher; mit #62 kommt die Ausprägung im Buch dazu.
    # Häufiges im neutralen Bestand steht hinten.
    rang = sorted(
        traeger,
        key=lambda f: (-len(traeger[f]), f in haeufig, family_name(f, vocabulary).casefold()),
    )

    def karte(f: str) -> Card:
        begriff = next(b.terms[f] for b in traeger[f] if f in b.terms)
        return Card(
            pille(f, f in an),
            vocabulary.terms[begriff].description,
            strength(len(traeger[f])),
            tuple((b.title, b.families[f]) for b in traeger[f]),
        )

    merkmale = tuple(karte(f) for f in rang if not vocabulary.is_pattern(f))
    muster = tuple(karte(f) for f in rang if vocabulary.is_pattern(f))

    verloren = []
    for d in enttaeuscht:
        auch = [f for f in d.families if traeger.get(f)]
        nur_hier = [f for f in d.families if not traeger.get(f)]
        dgruppen = []
        if auch:
            dgruppen.append(Group("Steckt auch in Büchern, die du liebst", (), "",
                                  tuple(pille(f, (f, d.book_id) in weg, d.book_id)
                                        for f in ordnung(auch)),
                                  conflict=True))
        if nur_hier:
            dgruppen.append(Group("Nur in diesem Buch", (), "",
                                  tuple(pille(f, (f, d.book_id) in weg, d.book_id)
                                        for f in ordnung(nur_hier))))
        fragen = tuple(
            ScopeQuestion(f, family_name(f, vocabulary), d.book_id, weg[(f, d.book_id)] or HERE,
                          d.genre, tuple(b.title for b in traeger[f]))
            for f in ordnung(auch)
            if (f, d.book_id) in weg
        )
        verloren.append(LostBook(d.title, d.book_id, tuple(dgruppen), fragen))

    entwurf = _draft(vocabulary, geliebt, enttaeuscht, traeger, an, weg, pille,
                     fragen_jetzt=bool(an))
    return Choosing(tuple(geliebt), merkmale, muster, tuple(verloren), entwurf)


def _draft(vocabulary, geliebt, enttaeuscht, traeger, an, weg, pille, *,
           fragen_jetzt: bool) -> Draft:
    gewaehlt = [f for f in traeger if f in an]
    facetten = derive_facets(gewaehlt, {f: [b.key for b in bs] for f, bs in traeger.items()})
    titel = {b.key: b.title for b in geliebt}
    karten = tuple(
        FacetCard(f.families, family_names(f.families, vocabulary), strength(len(f.books)),
                  tuple(titel[k] for k in f.books))
        for f in facetten
    )
    # Die Abdeckung fragt erst, wenn angetippt wurde: vorher steckt jedes Buch
    # in keiner Facette, und rechts stünde jedes für sich.
    offen = uncovered(facetten, [b.key for b in geliebt]) if fragen_jetzt else []
    fragen = tuple(
        Uncovered(b.title, tuple(pille(f, f in an) for f in b.families))
        for b in geliebt
        if b.key in offen
    )

    buecher_von = {d.book_id: d for d in enttaeuscht}
    neu, nur_hier = [], []
    for (f, book_id), scope in weg.items():
        d = buecher_von.get(book_id)
        if d is None:
            continue
        # Voreingestellt: steckt es auch in einem geliebten Buch, zählt es nur
        # hier, bis die Leserin es anders sagt — sonst überall.
        umfang = scope or (HERE if traeger.get(f) else GENERAL)
        try:
            gewicht = scoped_counterweight(f, umfang, d.genre, d.title)
        except ScopeError:
            gewicht = None
        if gewicht is None:
            nur_hier.append(family_name(f, vocabulary))
        else:
            neu.append(gewicht)
    gegen, _ = merge_counterweights((), neu)
    karten_gegen = tuple(
        WeightCard(c.families, family_names(c.families, vocabulary), c.genre, c.books)
        for c in gegen
    )
    return Draft(karten, karten_gegen, tuple(nur_hier), fragen)


def choose(
    store: Store, settings: Settings, side: str, family_id: str, *,
    book_id: int | None = None, on: bool,
) -> None:
    """Eine Familie antippen: ♥ auf Bildschirm 3, ⊘ auf Bildschirm 4."""
    if side not in (LOVED, LOST):
        raise IntakeError(f"unbekannte Seite {side!r}")
    try:
        load_vocabulary().family(family_id)
    except KeyError:
        raise IntakeError(f"keine solche Familie: {family_id}") from None
    if side == LOST and book_id is None:
        raise IntakeError("Ein Gegengewicht gehört zu einem Buch.")
    store.set_intake_choice(settings.slug, side, family_id, book_id=book_id, active=on)


def set_scope(store: Store, settings: Settings, family_id: str, book_id: int, scope: str) -> None:
    """Die Nachfrage beantworten: nur hier, überall, oder nur mit dem Genre."""
    buch = shelf_book(store, load_vocabulary(), book_id)
    try:
        scoped_counterweight(family_id, scope, buch.genre if buch else None, "")
    except ScopeError as exc:
        raise IntakeError(str(exc)) from None
    store.set_intake_choice(settings.slug, LOST, family_id, book_id=book_id, active=True,
                            scope=scope)


def adopt(
    store: Store, settings: Settings, facets: Collection[str], weights: Collection[str],
    *, now: datetime,
) -> int | None:
    """Bestätigen: die gewählten Facetten und Gegengewichte werden die erste
    Fassung des Leseprofils. Nichts gewählt heißt neu anfangen (#44) — dann
    kommt nichts zurück.

    Gewählt wird über den Schlüssel, nicht die Stelle: hat sich der Entwurf
    seit dem Laden geändert, etwa in einem zweiten Tab, zählt, was die Leserin
    gesehen hat, und was es nicht mehr gibt, fällt weg.
    """
    entwurf = choosing(store, settings).draft
    facetten = tuple(Facet(f.families, f.books) for f in entwurf.counted if f.key in facets)
    gegen = tuple(
        Counterweight(w.families, w.genre, w.books) for w in entwurf.weights if w.key in weights
    )
    if not facetten and not gegen:
        store.reset_intake(settings.slug)
        return None
    return store.put_reading_profile(
        settings.slug, ReadingProfile(facetten, gegen), cause="Erstaufnahme", now=now
    )
