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
from dataclasses import dataclass, field, replace
from datetime import datetime

from ..config import Settings
from ..facets import (
    GENERAL,
    HERE,
    MOST_BOOSTED,
    STRENGTHS,
    Counterweight,
    Facet,
    Liked,
    ReadingProfile,
    ScopeError,
    derive_facets,
    families_of,
    family_description,
    family_name,
    family_names,
    merge_counterweights,
    scoped_counterweight,
    strength,
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


# --- Bildschirme 3 bis 5: was dich hält, was dich verloren hat, dein Profil ------
#
# Seit dem 24.09.2026: Bildschirm 3 zeigt alle Merkmale und Erzählmuster der
# geliebten Bücher, gerankt. Die Leserin tippt an, was für sie zählt, und
# verstärkt davon bis zu drei. Die Facetten — Kombinationen, die mehrere
# geliebte Bücher gemeinsam tragen — bildet das Werkzeug daraus selbst; sie
# werden nicht bestätigt. Erzählmuster stecken nie in einer Facette (#63).

LOVED, LOST, BOOST = "loved", "lost", "boost"

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
    #: Von der Leserin verstärkt.
    boosted: bool = False


@dataclass(frozen=True, slots=True)
class LostCard:
    """Ein Merkmal oder Erzählmuster, das enttäuschende Bücher tragen, als
    Karte (24.09.2026) — wie eine Karte auf Bildschirm 3, nur mit ⊘ statt ♥,
    und ebenso nicht nach Büchern gruppiert: das las sich wie ein
    Buchvergleich, genau wie „Weil du A und B mochtest" auf Bildschirm 3
    vorher (#44). Welche enttäuschenden Bücher dahinterstehen, steht nur in
    den Belegen.

    Trägt es auch ein geliebtes Buch, steht direkt in der Karte die Nachfrage,
    wie weit es gilt: nur bei diesen Büchern (voreingestellt), überall, oder
    nur zusammen mit dem Genre — so wird aus „klassisch" ein Bündel aus Genre
    und Heldenreise statt eines Gegengewichts gegen jede Heldenreise. Nur hier
    werden geliebte Bücher genannt; ohne sie wäre die Nachfrage nicht zu
    verstehen.
    """

    pill: Pill
    description: str
    #: Je enttäuschendem Buch, das es trägt, der Satz aus seinem Steckbrief.
    evidence: tuple[tuple[str, str], ...]
    #: Welche geliebten Bücher dieselbe Familie tragen — der Grund für die
    #: Nachfrage.
    also_in: tuple[str, ...] = ()
    scope: str = HERE
    #: Nur, wenn alle tragenden enttäuschenden Bücher dasselbe Genre haben.
    genre: str | None = None


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
class FacetCard:
    """Eine erkannte Kombination — Auskunft, keine Frage."""

    families: tuple[str, ...]
    #: Je Merkmal sein Name und der Satz, was es heißt: so versteht man die
    #: Kombination, ohne zwei Kurzwörter mit einem Punkt dazwischen zu deuten.
    parts: tuple[tuple[str, str], ...]
    strength: str
    #: Aus welchen geliebten Büchern — gespeichert, nicht gezeigt.
    books: tuple[str, ...]

    @property
    def level(self) -> int:
        return STRENGTHS.index(self.strength) + 1


@dataclass(frozen=True, slots=True)
class WeightCard:
    families: tuple[str, ...]
    name: str
    genre: str | None
    books: tuple[str, ...]

    @property
    def key(self) -> str:
        """Woran das Formular es wiedererkennt — nicht an seiner Stelle."""
        return ",".join(self.families) + "|" + (self.genre or "")


@dataclass(frozen=True, slots=True)
class Draft:
    """Das Profil, wie es aus den Antworten gerade entsteht — als Übersicht."""

    #: Was verstärkt ist, als Namen.
    boosted: tuple[str, ...]
    #: Die übrigen gemochten Merkmale und Erzählmuster, als Namen.
    terms: tuple[str, ...]
    patterns: tuple[str, ...]
    #: Die Kombinationen, die das Werkzeug daraus erkannt hat.
    facets: tuple[FacetCard, ...]
    weights: tuple[WeightCard, ...]
    #: Nur bei einem enttäuschenden Buch gestört — zählt nicht, steht aber da.
    only_here: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not (self.boosted or self.terms or self.patterns or self.weights)


@dataclass(frozen=True, slots=True)
class Choosing:
    """Was Bildschirm 3 und 4 zeigen, und das Profil daneben."""

    loved: tuple[ShelfBook, ...]
    #: Bildschirm 3: alle Merkmale der geliebten Bücher, gerankt.
    terms: tuple[Card, ...]
    #: Bildschirm 3, für sich: alle Erzählmuster der geliebten Bücher.
    patterns: tuple[Card, ...]
    #: Bildschirm 4: alle Merkmale der enttäuschenden Bücher, gerankt.
    lost_terms: tuple[LostCard, ...]
    lost_patterns: tuple[LostCard, ...]
    draft: Draft
    #: Was gemocht ist, in der Reihenfolge des Rangs — daraus wird das Profil.
    liked: tuple[Liked, ...]

    @property
    def lost(self) -> bool:
        return bool(self.lost_terms or self.lost_patterns)

    @property
    def boosted_count(self) -> int:
        return sum(g.boosted for g in self.liked)

    @property
    def can_boost(self) -> bool:
        return self.boosted_count < MOST_BOOSTED


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
    verstaerkt = {c.family_id for c in wahl if c.side == BOOST} & an
    weg = {c.family_id: c.scope for c in wahl if c.side == LOST}

    def pille(f: str, on: bool) -> Pill:
        return Pill(
            f, family_name(f, vocabulary), vocabulary.is_pattern(f), f in haeufig, on,
            boosted=f in verstaerkt,
        )

    traeger: dict[str, list[ShelfBook]] = {}
    for b in geliebt:
        for f in b.families:
            traeger.setdefault(f, []).append(b)

    # Bildschirm 3: alles, was die geliebten Bücher tragen, gerankt — nicht
    # nach Büchern gruppiert. Gerankt wird vorerst nach der Zahl der Bücher;
    # mit #62 kommt die Ausprägung im Buch dazu. Häufiges im neutralen
    # Bestand steht hinten.
    rang = sorted(
        traeger,
        key=lambda f: (-len(traeger[f]), f in haeufig, family_name(f, vocabulary).casefold()),
    )

    def karte(f: str) -> Card:
        return Card(
            pille(f, f in an),
            family_description(f, vocabulary),
            strength(len(traeger[f])),
            tuple((b.title, b.families[f]) for b in traeger[f]),
        )

    merkmale = tuple(karte(f) for f in rang if not vocabulary.is_pattern(f))
    muster = tuple(karte(f) for f in rang if vocabulary.is_pattern(f))

    traeger_verloren: dict[str, list[ShelfBook]] = {}
    for b in enttaeuscht:
        for f in b.families:
            traeger_verloren.setdefault(f, []).append(b)

    # Bildschirm 4: alles, was die enttäuschenden Bücher tragen, ebenso
    # gerankt und nicht nach Büchern gruppiert (24.09.2026) — das las sich
    # wie ein Buchvergleich, genau wie auf Bildschirm 3 vorher (#44).
    rang_verloren = sorted(
        traeger_verloren,
        key=lambda f: (-len(traeger_verloren[f]), f in haeufig,
                       family_name(f, vocabulary).casefold()),
    )

    def karte_verloren(f: str) -> LostCard:
        traeger_f = traeger_verloren[f]
        return LostCard(
            pille(f, f in weg),
            family_description(f, vocabulary),
            tuple((b.title, b.families[f]) for b in traeger_f),
            also_in=tuple(b.title for b in traeger.get(f, ())),
            scope=weg.get(f) or HERE,
            genre=_unique_genre(traeger_f),
        )

    verloren_merkmale = tuple(
        karte_verloren(f) for f in rang_verloren if not vocabulary.is_pattern(f)
    )
    verloren_muster = tuple(karte_verloren(f) for f in rang_verloren if vocabulary.is_pattern(f))

    gemocht = tuple(Liked(f, f in verstaerkt) for f in rang if f in an)
    entwurf = _draft(vocabulary, gemocht, traeger, traeger_verloren, weg)
    return Choosing(
        tuple(geliebt), merkmale, muster, verloren_merkmale, verloren_muster, entwurf, gemocht
    )


def _unique_genre(carriers: Collection[ShelfBook]) -> str | None:
    """Das Genre, wenn alle diese Bücher dasselbe tragen — sonst keins."""
    genres = {b.genre for b in carriers if b.genre}
    return next(iter(genres)) if len(genres) == 1 else None


def _draft(vocabulary, gemocht, traeger, traeger_verloren, weg) -> Draft:
    # Die Facetten bildet das Werkzeug selbst, nur aus Merkmalen (#63).
    merkmale = [g.family for g in gemocht if not vocabulary.is_pattern(g.family)]
    facetten = derive_facets(merkmale, {f: [b.key for b in bs] for f, bs in traeger.items()})
    titel = {b.key: b.title for bs in traeger.values() for b in bs}
    karten = tuple(
        FacetCard(
            f.families,
            tuple(
                (family_name(x, vocabulary), family_description(x, vocabulary))
                for x in f.families
            ),
            strength(len(f.books)),
            tuple(titel[k] for k in f.books),
        )
        for f in facetten
    )

    neu, nur_hier = [], []
    for f, scope in weg.items():
        traeger_f = traeger_verloren.get(f)
        if not traeger_f:
            continue
        # Voreingestellt: steckt es auch in einem geliebten Buch, zählt es nur
        # hier, bis die Leserin es anders sagt — sonst überall.
        umfang = scope or (HERE if traeger.get(f) else GENERAL)
        try:
            gewicht = scoped_counterweight(f, umfang, _unique_genre(traeger_f), traeger_f[0].title)
        except ScopeError:
            gewicht = None
        if gewicht is None:
            nur_hier.append(family_name(f, vocabulary))
        else:
            neu.append(replace(gewicht, books=tuple(b.title for b in traeger_f)))
    gegen, _ = merge_counterweights((), neu)
    karten_gegen = tuple(
        WeightCard(c.families, family_names(c.families, vocabulary), c.genre, c.books)
        for c in gegen
    )

    def namen(auswahl):
        return tuple(family_name(g.family, vocabulary) for g in auswahl)

    return Draft(
        boosted=namen(g for g in gemocht if g.boosted),
        terms=namen(g for g in gemocht if not g.boosted and not vocabulary.is_pattern(g.family)),
        patterns=namen(g for g in gemocht if not g.boosted and vocabulary.is_pattern(g.family)),
        facets=karten,
        weights=karten_gegen,
        only_here=tuple(nur_hier),
    )


def choose(store: Store, settings: Settings, side: str, family_id: str, *, on: bool) -> None:
    """Antippen: ♥ auf Bildschirm 3, ⊘ auf Bildschirm 4 — oder verstärken.

    Verstärken geht nur, was gemocht ist, und höchstens ``MOST_BOOSTED``.
    Wer ein Merkmal wieder löst, löst auch seine Verstärkung.
    """
    if side not in (LOVED, LOST, BOOST):
        raise IntakeError(f"unbekannte Seite {side!r}")
    try:
        load_vocabulary().family(family_id)
    except KeyError:
        raise IntakeError(f"keine solche Familie: {family_id}") from None
    if side == BOOST and on:
        wahl = store.intake_choices(settings.slug)
        gemocht = {c.family_id for c in wahl if c.side == LOVED}
        verstaerkt = {c.family_id for c in wahl if c.side == BOOST} & gemocht
        if family_id not in gemocht:
            raise IntakeError("Verstärken lässt sich nur, was du angetippt hast.")
        if family_id not in verstaerkt and len(verstaerkt) >= MOST_BOOSTED:
            raise IntakeError(f"Höchstens {MOST_BOOSTED} lassen sich verstärken.")
    store.set_intake_choice(settings.slug, side, family_id, active=on)
    if side == LOVED and not on:
        store.set_intake_choice(settings.slug, BOOST, family_id, active=False)


def set_scope(store: Store, settings: Settings, family_id: str, scope: str) -> None:
    """Die Nachfrage beantworten: nur hier, überall, oder nur mit dem Genre."""
    vocabulary = load_vocabulary()
    try:
        vocabulary.family(family_id)
    except KeyError:
        raise IntakeError(f"keine solche Familie: {family_id}") from None
    enttaeuscht = _shelf_books(store, settings, vocabulary, str(RelationKind.DISLIKED))
    traeger = [b for b in enttaeuscht if family_id in b.families]
    try:
        scoped_counterweight(family_id, scope, _unique_genre(traeger), "")
    except ScopeError as exc:
        raise IntakeError(str(exc)) from None
    store.set_intake_choice(settings.slug, LOST, family_id, active=True, scope=scope)


def adopt(
    store: Store, settings: Settings, weights: Collection[str], *, now: datetime
) -> int | None:
    """Bestätigen: was angetippt und verstärkt ist, die erkannten Facetten und
    die gewählten Gegengewichte werden die erste Fassung des Leseprofils.

    Nichts gemocht und kein Gegengewicht heißt neu anfangen (#44) — dann kommt
    nichts zurück. Gegengewichte werden über ihren Schlüssel gewählt, nicht
    ihre Stelle: hat sich der Entwurf seit dem Laden geändert, zählt, was die
    Leserin gesehen hat.
    """
    wahl = choosing(store, settings)
    facetten = tuple(Facet(f.families, f.books) for f in wahl.draft.facets)
    gegen = tuple(
        Counterweight(w.families, w.genre, w.books)
        for w in wahl.draft.weights
        if w.key in weights
    )
    if not wahl.liked and not gegen:
        store.reset_intake(settings.slug)
        return None
    return store.put_reading_profile(
        settings.slug, ReadingProfile(facetten, gegen, wahl.liked), cause="Erstaufnahme", now=now
    )
