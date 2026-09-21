"""Alles, was über ein Buch bekannt ist, an einer Stelle (Ticket 07).

Diese Seite zahlt das Modell aus ADR 18 zum ersten Mal aus: dieselben Angaben
lagen vorher über vier Dateien verstreut, die einander nicht kannten —
*Cold Eternity* als Titel in ``owned.yaml``, als Produktnummer in
``dismissed.yaml``, und einmal als Zeile in ``watchlist.yaml``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime

from ..cleaning import is_truncated
from ..config import Profile
from ..deals import is_strong_deal
from ..evidence import gather as gather_evidence
from ..http import HttpClient, build_user_agent
from ..models import Availability, MatchReason
from ..rating import RatingUnavailable, build_rater, confidence_label, load_leseprofil
from ..ratings import (
    BY_CONVERSATION,
    BY_MODEL,
    BY_ONLEIHE_READERS,
    BY_READER,
    FOREIGN_ORIGINS,
    HUMAN_ORIGINS,
    LABELS,
    VIA_BOOK_PAGE,
    book_subject,
    subject_of,
)
from ..reasons import short_why, why_shown
from ..relations import RELATION_KINDS, RelationKind, labelled_actions
from ..sources import build_sources, registry
from ..store import Store
from .watchlist import SourceState

#: Die Reihenfolge, in der Urteile auf der Seite stehen: was ein Mensch gesagt
#: hat, zuerst.
#: Zuletzt die fremden Stimmen: sie sind Auskunft ueber das Buch, nicht ueber
#: die Passung zum Profil (Ticket 54).
ORIGIN_ORDER: tuple[str, ...] = (BY_READER, BY_CONVERSATION, BY_MODEL, BY_ONLEIHE_READERS)

#: Was die Leserin über ein Buch sagen kann, in der Reihenfolge, in der es auf
#: der Seite steht. Mehrere gelten gleichzeitig — das ist der Normalfall.
#:
#: Knopfwörter, nicht Zustandsnamen: hier stehen Knöpfe, und derselbe Knopf
#: heißt im Stapel und auf der Fundseite genauso (ADR 29 mit Nachtrag). Was
#: gerade gilt, sagt die Farbe des Knopfs, nicht sein Wort.
#: Vorn die drei, die es auch im Stapel gibt, in derselben Reihenfolge;
#: hinten die beiden Urteile nach dem Lesen. Sie beantworten eine andere
#: Frage — nicht "was tue ich damit?", sondern "wie war es?".
KINDS: tuple[tuple[str, str], ...] = labelled_actions(
    RelationKind.WATCHING,
    RelationKind.OWNED,
    RelationKind.DISMISSED,
    RelationKind.LIKED,
    RelationKind.DISLIKED,
)

#: Herkuenfte, deren Urteil an einer *Ausgabe* haengt statt am Buch der
#: Leserin — das Tor (ADR 18) und fremde Leserstimmen (Ticket 54).
_AT_THE_FIND: frozenset[str] = frozenset({BY_MODEL}) | FOREIGN_ORIGINS

#: Nur für den Vergleich zweier Zeitstempel, von denen einer fehlen darf.
_EPOCH = datetime.min

_AVAILABILITY = {
    Availability.AVAILABLE: "ausleihbar",
    Availability.UNAVAILABLE: "verliehen",
    Availability.UNKNOWN: "unklar",
}


def _details(row) -> dict:
    try:
        return json.loads(row.details or "{}")
    except (TypeError, ValueError):  # pragma: no cover - defekte Zeile
        return {}


@dataclass(frozen=True, slots=True)
class Relation:
    kind: str
    label: str
    active: bool
    note: str | None
    since: datetime | None

    @property
    def is_history(self) -> bool:
        """Abgelegt, aber nicht vergessen.

        Eine deaktivierte Beziehung ist selbst eine Auskunft — "beobachtet, bis
        du es gekauft hast" (ADR 18).
        """
        return not self.active


@dataclass(frozen=True, slots=True)
class Sighting:
    """Eine Zeile der Geschichte."""

    when: datetime | None
    #: Der Quellname — die **Identitaet**, nicht die Beschriftung. Beides war
    #: hier dasselbe Feld, solange es eine Bibliothek gab; mit zweien suchte
    #: die Onleihe-Kachel ihre Sichtung unter "Bibliothek" und fand die von
    #: OverDrive. Die Seite behauptete dann "verliehen" fuer einen Titel, den
    #: die Onleihe gar nicht fuehrt.
    name: str
    #: Die *Art* der Quelle, wie sie der Leserin gezeigt wird: "voebb" war nie
    #: ein Wort fuer sie (Ticket 14).
    source: str
    price: str | None
    availability: str | None
    #: Wie *diese* Quelle das Buch damals nannte — aber nur, wenn es von
    #: unserem Titel abweicht. Sonst wiederholte die Spalte in jeder Zeile
    #: dasselbe, und der eine interessante Fall ginge darin unter.
    other_title: str | None
    deal: bool
    #: Derselbe Betrag als Zahl. Der Text ist fuers Auge ("4,99 €"), die Zahl
    #: fuers Sortieren: die Kachel nennt den guenstigsten Shop (#33), und
    #: als Text waere "12,99 €" kleiner als "4,99 €".
    price_cents: int | None = None
    #: Wie viele vor der Leserin warten, und ab wann das Exemplar wieder da
    #: ist. Beides lag bisher ungenutzt in der Beobachtung (#34).
    reservation_count: int | None = None
    available_from: str | None = None

    @property
    def hold(self) -> str | None:
        """Was die Wartezeit sagt — oder nichts.

        Bei einem ausleihbaren Titel wartet niemand, und "0 Vormerkungen"
        waere eine Antwort auf eine Frage, die sich nicht stellt. Sonst zaehlt
        zuerst das Datum: "frei ab 12.10." sagt mehr als eine Zahl, denn
        danach richtet man sich. Erst wenn keines bekannt ist, sagt die Zahl
        wenigstens, wie lang die Schlange ist.
        """
        if self.availability == "ausleihbar":
            return None
        if self.available_from:
            return f"frei ab {self.available_from}"
        if self.reservation_count:
            eine = self.reservation_count == 1
            return f"{self.reservation_count} Vormerkung{'' if eine else 'en'}"
        return None


@dataclass(frozen=True, slots=True)
class Origin:
    """Was dieses Buch hereingebracht hat — in den Worten des Digests.

    Ein Watchlist-Titel braucht das nicht: warum er da ist, weiß die Leserin,
    sie hat ihn hingeschrieben. Eine Entdeckung ist der ganze Grund, aus dem
    die Frage überhaupt gestellt wird — und wer sie nicht über den Digest
    öffnet, bekam bisher keine Antwort darauf.
    """

    why: str
    short: str
    #: Autor:in oder Thema — dieselbe Farbtrennung wie in der Triage.
    author_driven: bool
    when: datetime | None


@dataclass(frozen=True, slots=True)
class Judgement:
    """Ein Urteil über dieses Buch, mit der Angabe, wer es gefällt hat.

    Der Unterschied ist der ganze Zweck der Zeile: eine 4 von der Leserin ist
    eine Tatsache, eine 4 vom Modell ein Vorschlag (ADR 17). Sie dürfen
    deswegen nicht gleich aussehen.
    """

    origin: str
    label: str
    stars: float
    reason: str
    confidence: str
    profile_version: int
    when: datetime | None
    #: Auf wie vielen Stimmen die Angabe ruht — nur bei fremden Urteilen.
    votes: int | None = None
    #: Welche Achsen das Urteil trifft und verfehlt (#12). Leer bei Urteilen
    #: von vorher und bei allem, was kein Modell gefaellt hat.
    hits: tuple[str, ...] = ()
    misses: tuple[str, ...] = ()
    #: Was der Code nach dem Urteil abzog, und die Sterne des Modells davor (#28).
    deductions: tuple[str, ...] = ()
    model_stars: float | None = None

    @property
    def confidence_label(self) -> str:
        """Worauf das Urteil ruht, in einem Wort, das fuer sich steht."""
        return confidence_label(self.confidence)

    @property
    def is_human(self) -> bool:
        return self.origin in HUMAN_ORIGINS

    @property
    def is_foreign(self) -> bool:
        """Fremde Leserstimmen — weder das Werkzeug noch die Leserin.

        Sie sagen etwas ueber das *Buch*, nicht ueber die Passung zum Profil,
        und duerfen deshalb nicht neben einem Modellurteil stehen, als waeren
        sie dasselbe (Ticket 54).
        """
        return self.origin in FOREIGN_ORIGINS

    def stale(self, current: int | None) -> bool:
        """Gegen eine ältere Profilfassung gefällt — und deshalb nur noch Auskunft.

        Gilt nur für Maschinenurteile: was ein Mensch gesagt hat, verfällt
        nicht, wenn er sein Profil schärft.
        """
        if self.is_human or self.is_foreign:
            # Eine fremde Durchschnittsnote ist kein Urteil gegen das Profil.
            # Sie kann deshalb auch nicht gegen eine aeltere Fassung gefaellt
            # worden sein.
            return False
        return current is not None and self.profile_version != current


#: Wie viele Zeilen die Tabelle "Was beobachtet wurde" zeigt. Der Snapshot ist
#: anhaengend (ADR 5) und wird nie kuerzer — die Seite muss es sein.
HISTORY_ROWS = 5


def _series_label(series: str | None, index: str | None) -> str | None:
    """"Southern Reach, Band 2" — oder nur die Reihe, wenn niemand den Band kennt."""
    if not series:
        return None
    return f"{series}, Band {index}" if index else series


@dataclass(frozen=True, slots=True)
class Category:
    """Was eine Quellen*art* ueber dieses Buch sagt (#33).

    Der Kopf zeigt je Art **eine** Kachel, nicht eine je Quelle: die Seite
    beantwortet zwei Fragen — kann ich es leihen, was kostet es —, und beide
    haben genau eine Antwort. Mit drei Quellen standen dort dreimal 65 Pixel,
    davon zweimal "nicht im Katalog".

    ``best`` ist die Quelle, die die Frage beantwortet: bei Bibliotheken die
    ausleihbare, bei Shops die guenstigste. Kennt keine das Buch, ist sie
    ``None`` — dann gibt es keinen Namen zu nennen.

    ``sources`` bleibt vollstaendig, beste zuerst: darunter steht je Quelle
    eine Blase, damit die Uebersicht nicht verloren geht.
    """

    category: str
    best: SourceState | None
    sighting: Sighting | None
    sources: tuple[SourceState, ...]

    @property
    def library(self) -> bool:
        return self.category == "library"


#: Der schlechteste Rang: diese Quelle hat nachgesehen und nichts gefunden.
#: Nur er heisst "kein Name zu nennen" — ein verliehenes Exemplar ist
#: gefunden, es ist nur gerade nicht da.
NOT_FOUND = 2


@dataclass(frozen=True, slots=True)
class Page:
    book_id: int
    title: str
    author: str | None
    series: str | None
    isbn: str | None
    cover_file: str | None
    relations: tuple[Relation, ...]
    sources: tuple[SourceState, ...]
    history: tuple[Sighting, ...]
    judgements: tuple[Judgement, ...]
    #: Die heutige Profilversion, oder ``None``, wenn das Profil nicht lesbar ist.
    profile_version: int | None
    #: Warum dieser Fund überhaupt hereinkam — nur bei Entdeckungen (Ticket 22).
    origin: Origin | None
    #: An welcher Art Quelle geprüft wird — ``None`` heißt: an allen. Steht
    #: hier und nicht mehr in der Watchlist-Zeile: das ist eine Einstellung
    #: dieses Buchs, keine Handlung an der Liste (Ticket 48).
    restrict: str | None = None
    #: Ob das Buch überhaupt beobachtet wird — sonst gibt es nichts zu prüfen.
    watching: bool = False
    #: Der Klappentext, wie er an der ``book``-Zeile steht (Ticket 52).
    blurb: str | None = None
    #: Was die Leserin sich selbst zu dem Buch notiert hat.
    note: str | None = None
    #: Die jüngste Beobachtung je Quelle — daraus baut der Kopf seine Kacheln.
    latest: tuple[Sighting, ...] = ()

    @property
    def price(self) -> str | None:
        """Der zuletzt gesehene Preis, gleich von welcher Quelle."""
        for sichtung in self.latest:
            if sichtung.price:
                return sichtung.price
        return None

    @property
    def seen(self) -> datetime | None:
        return max((s.when for s in self.latest if s.when), default=None)

    @property
    def deal(self) -> bool:
        """Schnaeppchen — dieselbe Regel wie in den Listen."""
        return any(sichtung.deal for sichtung in self.latest)

    @property
    def borrowable(self) -> bool:
        return any(sichtung.availability == "ausleihbar" for sichtung in self.latest)

    def latest_at(self, name: str) -> Sighting | None:
        """Die juengste Sichtung dieser Quelle, oder ``None``.

        Gefragt wird nach dem Quellnamen. Nach der Beschriftung zu fragen war
        richtig, solange keine zwei Quellen dieselbe trugen — seit es zwei
        Bibliotheken gibt, beantwortete es die Frage einer anderen Quelle.
        """
        for sichtung in self.latest:
            if sichtung.name == name:
                return sichtung
        return None

    @property
    def categories(self) -> tuple[Category, ...]:
        """Je Quellenart eine Kachel, mit allen Quellen dieser Art (#33)."""
        arten = []
        for art in registry.CATEGORY_ORDER:
            quellen = [state for state in self.sources if state.category == art]
            if not quellen:
                continue
            quellen.sort(key=lambda state: self._rank(art, state))
            beste = quellen[0]
            sichtung = self.latest_at(beste.name)
            if self._rank(art, beste)[0] >= NOT_FOUND:
                # Keine Quelle dieser Art kennt das Buch: die Kachel sagt das,
                # ohne einen Namen zu nennen, den es nicht gibt. *Gefuehrt und
                # gerade verliehen* gehoert nicht hierher — das heisst warten,
                # nicht anderswo suchen.
                beste, sichtung = None, None
            arten.append(Category(art, beste, sichtung, tuple(quellen)))
        return tuple(arten)

    def _rank(self, category: str, state: SourceState) -> tuple[int, int]:
        """Je kleiner, desto eher beantwortet diese Quelle die Frage der Art.

        Bibliothek: ausleihbar schlaegt alles, danach zaehlt ueberhaupt
        gefunden. Shop: der guenstigste Preis; ohne Preis ist der Fund nur ein
        Eintrag im Katalog und kommt dahinter.
        """
        sichtung = self.latest_at(state.name)
        gefunden = state.outcome in ("linked", "confirmed")
        if category == "library":
            if sichtung and sichtung.availability == "ausleihbar":
                return (0, 0)
            return (1 if gefunden else NOT_FOUND, 0)
        if sichtung and sichtung.price_cents is not None:
            return (0, sichtung.price_cents)
        return (1 if gefunden else NOT_FOUND, 0)

    @property
    def my_stars(self) -> int | None:
        """Was die Leserin selbst vergeben hat — sonst ``None``.

        Ausdrücklich nicht ``0``: keine Bewertung und "passt überhaupt nicht"
        sind zwei verschiedene Auskünfte, und eine Reihe grauer Sterne würde
        die zweite behaupten, wo gar nichts gesagt wurde.
        """
        for judgement in self.judgements:
            if judgement.origin == BY_READER:
                return judgement.stars
        return None

    @property
    def active_kinds(self) -> set[str]:
        return {row.kind for row in self.relations if row.active}

    @property
    def has_history(self) -> bool:
        return bool(self.history)

    @property
    def recent_history(self) -> tuple[Sighting, ...]:
        """Die letzten Sichtungen — mehr zeigt die Tabelle nicht.

        Ein Buch, das seit elf Laeufen dasselbe kostet, hatte elf Zeilen mit
        elfmal demselben Betrag, und alles darunter rutschte aus dem Bild. Was
        sich geaendert hat, steht ohnehin darueber in der Preisliste; hier geht
        es um den letzten Stand, nicht um ein Archiv.
        """
        return self.history[:HISTORY_ROWS]

    @property
    def hidden_history(self) -> int:
        """Wie viele aeltere Sichtungen die Tabelle nicht zeigt."""
        return max(0, len(self.history) - HISTORY_ROWS)

    @property
    def mismatch(self) -> tuple[SourceState, ...]:
        """Quellen, deren eigener Titel nicht nach demselben Buch klingt.

        Kein Urteil, nur ein Hinweis: der Vergleich ist absichtlich stumpf —
        er soll auffallen lassen, was ein Mensch nachsehen sollte, nicht selbst
        entscheiden (ADR 8).
        """
        mine = _words(self.title)
        odd = []
        for state in self.sources:
            if not state.matched_title:
                continue
            theirs = _words(state.matched_title)
            if mine and theirs and not (mine & theirs):
                odd.append(state)
        return tuple(odd)


def _words(text: str) -> set[str]:
    return {word for word in text.casefold().split() if len(word) > 3}


def _price(cents: int | None) -> str | None:
    if cents is None:
        return None
    return f"{cents / 100:.2f} €".replace(".", ",")


def _origin(seen) -> Origin | None:
    """Die jüngste Sichtung, die keine Watchlist-Prüfung war.

    Ein Buch, das nur über die Watchlist beobachtet wird, hat keine solche
    Sichtung — und bekommt deshalb keine Zeile, ohne dass es dafür eine eigene
    Regel bräuchte. Die Formulierung kommt aus :mod:`ebook_watchlist.reasons`,
    damit Digest, Triage und diese Seite nicht dreimal dasselbe verschieden
    sagen (Ticket 14).
    """
    for observation in seen:
        if observation.match_reason is MatchReason.WATCHLIST:
            continue
        return Origin(
            why=why_shown(observation),
            short=short_why(observation),
            author_driven=observation.match_reason is MatchReason.PROFILE_AUTHOR,
            when=observation.observed_at,
        )
    return None


def _judgements(
    store: Store, book, seen, *, isbn: str | None = None
) -> tuple[Judgement, ...]:
    """Alle Urteile, die zu diesem Buch gehören — an drei Sorten Schlüssel.

    Was ein Mensch gesagt hat, hängt am Buch. Das Tor schlüsselt dagegen am
    Fund, weil es dreihundert Funde bewertet, von denen die wenigsten je eine
    Buchzeile bekommen (ADR 18) — sein Urteil ist deshalb über die ISBN oder
    über die Produktnummern der Quellen zu finden, unter denen dieses Buch
    gesichtet wurde.

    ``book`` darf ``None`` sein: die Discovery-Seite zeigt einen Fund, zu dem
    es noch keine Buch-Zeile gibt. Dann bleibt genau das übrig, was am Fund
    hängt — das Urteil des Tors und fremde Leserstimmen zur ISBN.
    """
    of_book = book_subject(book.id) if book is not None else None
    subjects = {of_book} if of_book else set()
    if isbn := (book.isbn if book is not None else isbn):
        subjects.add(f"isbn:{isbn}")
    subjects.update(subject_of(observation) for observation in seen)

    rows = store.ratings_for(subjects)
    found: dict[str, object] = {}
    for (subject, origin), row in rows.items():
        # Am *Fund* darf hängen, was über eine Ausgabe spricht: das Urteil des
        # Tors und fremde Leserstimmen, die zu einer ISBN gehören. Was ein
        # Mensch gesagt hat, hängt dagegen am Buch — unter einem Fund-Schlüssel
        # gäbe es das nur, wenn jemand es dort hinschriebe (Ticket 54).
        if origin not in _AT_THE_FIND and subject != of_book:
            continue
        previous = found.get(origin)
        if previous is None or (row.rated_at or _EPOCH) > (previous.rated_at or _EPOCH):
            found[origin] = row

    return tuple(
        Judgement(
            origin=origin,
            label=LABELS[origin],
            stars=row.stars,
            reason=row.reason,
            confidence=row.confidence,
            profile_version=row.profile_version,
            when=row.rated_at,
            votes=row.votes,
            hits=row.hits,
            misses=row.misses,
            deductions=row.deductions,
            model_stars=row.model_stars,
        )
        for origin in ORIGIN_ORDER
        if (row := found.get(origin)) is not None
    )


def _latest_per_source(history: tuple[Sighting, ...]) -> tuple[Sighting, ...]:
    """Je Quelle die juengste Sichtung, in der Reihenfolge der Geschichte.

    Der Kopf zeigt je Quelle eine Kachel; welche Zeile dafuer gilt, ist die
    neueste — nicht die erste, die zufaellig oben steht.
    """
    neueste: dict[str, Sighting] = {}
    for sichtung in history:
        # Nach dem Namen, nicht nach der Beschriftung: zwei Bibliotheken tragen
        # dieselbe, und die eine verschwand still hinter der anderen.
        vorher = neueste.get(sichtung.name)
        if vorher is None or (sichtung.when or datetime.min) > (vorher.when or datetime.min):
            neueste[sichtung.name] = sichtung
    return tuple(neueste.values())


def build(store: Store, profile: Profile, book_id: int) -> Page | None:
    """Die Seite zu einem Buch, oder ``None``, wenn es das nicht gibt."""
    book = store.book(book_id)
    if book is None:
        return None

    known = {row.kind: row for row in store.relations_of(profile.slug, book_id)}
    relations = tuple(
        Relation(
            kind=kind,
            label=label,
            active=known[kind].active,
            note=_details(known[kind]).get("note"),
            since=known[kind].created_at,
        )
        for kind, label in KINDS
        if kind in known
    )

    sources = tuple(
        SourceState(
            name=link.source,
            outcome=_details(link).get("outcome", ""),
            url=link.url,
            matched_title=_details(link).get("matched_title"),
            matched_author=_details(link).get("matched_author"),
            reason=_details(link).get("reason", ""),
            category=registry.category(profile, link.source),
            display=registry.label(profile, link.source),
        )
        for link in store.book_sources(book_id)
    )

    seen = store.observations_for_book(profile.slug, book_id)
    history = tuple(
        Sighting(
            when=observation.observed_at,
            name=observation.source,
            source=registry.label(profile, observation.source),
            price=_price(observation.price_cents),
            price_cents=observation.price_cents,
            reservation_count=observation.reservation_count,
            available_from=observation.available_from,
            availability=_AVAILABILITY.get(observation.availability)
            if observation.availability
            else None,
            other_title=(
                observation.title if observation.title.strip() != book.title.strip() else None
            ),
            deal=is_strong_deal(observation.price_cents, profile),
        )
        for observation in seen
    )

    try:
        _, current_version = load_leseprofil()
    except RatingUnavailable:
        current_version = None

    return Page(
        book_id=book.id,
        title=book.title,
        author=book.author,
        series=_series_label(book.series, book.series_index),
        isbn=book.isbn,
        cover_file=book.cover_file,
        relations=relations,
        sources=sources,
        history=history,
        judgements=_judgements(store, book, seen),
        profile_version=current_version,
        origin=_origin(seen),
        blurb=book.blurb,
        note=_details(known[str(RelationKind.WATCHING)]).get("note")
        if str(RelationKind.WATCHING) in known
        else None,
        latest=_latest_per_source(history),
        restrict=_details(known[str(RelationKind.WATCHING)]).get("restrict")
        if str(RelationKind.WATCHING) in known
        else None,
        watching=str(RelationKind.WATCHING) in known
        and known[str(RelationKind.WATCHING)].active,
    )


def set_relation(
    store: Store, profile: Profile, book_id: int, kind: str, *, active: bool, now: datetime
) -> None:
    """Eine Beziehung setzen oder stilllegen — nie löschen (ADR 18)."""
    if kind not in RELATION_KINDS:
        raise ValueError(f"unbekannte Beziehung {kind!r}")
    store.put_relation(profile.slug, book_id, kind, active=active, now=now)


def price_points(history: tuple[Sighting, ...]) -> list[Sighting]:
    """Nur die Sichtungen, bei denen sich der Preis geändert hat.

    Eine Zeile je Lauf wäre nach einem Jahr eine Wand aus derselben Zahl. Was
    interessiert, ist die Änderung — und mit nur einem Punkt bleibt es eben
    ein Punkt, statt ein Diagramm zu behaupten.

    Ältestes zuerst, anders als die Tabelle darunter: eine Preisliste ist eine
    Entwicklung und liest sich von links nach rechts. Die Tabelle beantwortet
    dagegen "was war zuletzt".
    """
    seen: list[Sighting] = []
    last: str | None = None
    for sighting in reversed(history):
        if sighting.price is None or sighting.price == last:
            continue
        seen.append(sighting)
        last = sighting.price
    return seen


def rate(store: Store, profile: Profile, book_id: int, *, now: datetime) -> str:
    """Das Tor jetzt über dieses eine Buch urteilen lassen (Ticket 55).

    Im Lauf sieht das Tor nur, was auch im Stapel landen würde. Ein
    Watchlist-Titel ist gewollt und wird deshalb nie gefragt — über ihn
    entscheidet das Tor nichts, und auf seiner Seite stand für immer „Noch
    nicht bewertet". Eine Auskunft wäre das Urteil trotzdem, und hier holt es
    sich die Leserin.

    Laeuft im Hintergrund (#15): ein Aufruf dauert rund 43 Sekunden, und
    vorher wartete der Browser so lange auf die Antwort.

    Zurück kommt der Grund, warum es nicht ging — leer heißt: das Urteil steht.
    """
    seen = store.observations_for_book(profile.slug, book_id)
    if not seen:
        return "Noch kein Fund zu diesem Buch — es gibt nichts zu beurteilen."

    # Das Urteil hängt am Fund, nicht am Buch (ADR 18): am jüngsten, denn er
    # trägt den aktuellen Preis und die aktuelle Verfügbarkeit.
    book = store.book(book_id)
    return rate_observation(
        store, profile, seen[0], now=now, via=VIA_BOOK_PAGE,
        blurb=book.blurb if book is not None else None,
    )


def evidence_sources(profile: Profile, store: Store) -> list:
    """Die eingeschalteten Quellen, mit Kontaktadresse wie im Rundgang."""
    client = HttpClient(user_agent=build_user_agent(profile.contact))
    return [s for s in build_sources(profile, client) if store.is_enabled(s.name)]


def rate_observation(
    store: Store,
    profile: Profile,
    observation,
    *,
    now: datetime,
    via: str,
    blurb: str | None = None,
) -> str:
    """Einen Fund beurteilen lassen und das Urteil speichern — für Buch- und Fundseite.

    Eine Stelle, damit beide Seiten dasselbe tun (#15): welcher Fund beurteilt
    wird, entscheidet die Seite, wie beurteilt wird, entscheidet diese
    Funktion. Gespeichert wird **erst bei Erfolg** — scheitert der Aufruf,
    bleibt das alte Urteil stehen.

    Zurück kommt der Grund, warum es nicht ging — leer heißt: das Urteil steht.
    """
    rater = build_rater(profile.rating_model)
    if rater is None:
        return (
            "Kein Bewerter eingerichtet: weder ein API-Schlüssel in der Umgebung "
            "noch eine angemeldete Claude-Code-Installation."
        )

    # Dieselben Belege wie im Lauf (#17): Detailseite, Leseprobe,
    # Schlagwoerter. Bis dahin fragte ein Knopfdruck keine Quelle an — aber
    # ohne Leseprobe kommt ein Urteil nie ueber "teils" hinaus, und dasselbe
    # Buch bekaeme hier ein schwaecheres als im Lauf. Es laeuft ohnehin im
    # Hintergrund (#15); zwei Anfragen mehr fallen in der Minute nicht auf.
    observation = gather_evidence(
        store, profile, [observation], evidence_sources(profile, store)
    )[0]
    duenn = not observation.blurb or is_truncated(observation.blurb)
    if duenn and blurb:
        observation = replace(observation, blurb=blurb)

    try:
        rating = rater.rate(observation)
    except RatingUnavailable as exc:
        # Das Tor scheitert nie zu (ADR 7): der Grund wird genannt, das Buch
        # bleibt sichtbar und unbewertet.
        return str(exc)

    store.put_rating(
        subject_of(observation),
        stars=rating.stars,
        confidence=rating.confidence,
        reason=rating.reason,
        profile_version=rating.profile_version,
        now=now,
        origin=BY_MODEL,
        pitch=rating.pitch,
        via=via,
        hits=rating.hits,
        misses=rating.misses,
        model_stars=rating.model_stars,
        deductions=rating.deductions,
    )
    return ""


def set_stars(store: Store, book_id: int, stars: int | None, *, now: datetime) -> None:
    """Die eigenen Sterne der Leserin setzen oder zurücknehmen.

    Sie stehen unter ihrer eigenen Herkunft und damit neben dem Modellurteil,
    nicht darüber: keines überschreibt das andere (ADR 17, Ticket 21). Der
    Profilfassung wird mitgeschrieben, damit später nachvollziehbar bleibt, wovon
    hier die Rede war — verfallen tut ihr Urteil deswegen nicht.
    """
    if stars is None:
        store.drop_rating(book_subject(book_id), BY_READER)
        return
    if not 0 <= stars <= 5:
        raise ValueError(f"Sterne müssen zwischen 0 und 5 liegen, nicht {stars}")
    try:
        _, version = load_leseprofil()
    except RatingUnavailable:
        # Ohne lesbares Profil bleibt ihre Bewertung trotzdem gültig — sie
        # hängt nicht an ihm. Die 0 sagt: unter keiner bekannten Fassung.
        version = 0
    store.put_rating(
        book_subject(book_id),
        stars=stars,
        confidence="belegt",
        reason="",
        profile_version=version,
        now=now,
        origin=BY_READER,
    )
