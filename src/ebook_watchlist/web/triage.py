"""Der Vorschlagsstapel (Ticket 08).

Das ist der Vorgang, den ein Gespräch am schlechtesten kann — zwanzig Titel
einzeln diktiert — und ein Formular am besten.

Eine Entscheidung wirkt **buchweit**, nicht auf eine Produktnummer. Die alte
``dismissed.yaml`` konnte nur "dieser Shop soll das nicht mehr zeigen"; dasselbe
Buch bei der Onleihe wäre trotzdem wieder aufgetaucht (ADR 18).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .. import paths
from ..bundle_deal import BundleAdvantage, advantage_finder
from ..config import Profile
from ..covers import CoverStore, file_name
from ..deals import is_strong_deal
from ..diff import worth_announcing
from ..junk import is_junk
from ..language import is_foreign, language_finder
from ..matching.bundles import looks_like_bundle, volume_titles
from ..models import Availability, MatchReason, Observation
from ..rating import DEFAULT_THRESHOLD
from ..ratings import BY_MODEL, subject_of
from ..reasons import short_why, thema_name, why_shown
from ..relations import RELATION_KINDS, RelationKind, labelled_actions
from ..sources import registry
from ..store import Store
from . import sorting

#: Was mit einem Stapel geschehen kann. Alle drei schreiben eine Beziehung —
#: "verworfen" ist keine Löschung, sondern eine Aussage über das Buch.
ACTIONS: tuple[tuple[str, str], ...] = labelled_actions(
    RelationKind.DISMISSED, RelationKind.OWNED, RelationKind.WATCHING
)

#: Wie viele Zeilen eine Seite zeigt. Der Rückstand ist dreistellig, und eine
#: Seite mit dreihundert Einträgen ist keine Aufgabe, sondern eine Strafe —
#: der eigentliche Schnitt kommt aber vom Bewertungstor (ADR 19), nicht hier.
#:
#: Zehn, nicht fünfzig: solange der Stapel aus einem einmaligen Rückstand
#: besteht, den das Tor ohnehin neu erzeugt, ist eine kurze Liste billiger —
#: gezeigt wird nur, was auch bewertet werden muss.
PAGE_SIZE = 10


@dataclass(frozen=True, slots=True)
class Suggestion:
    source: str
    source_item_id: str
    title: str
    author: str | None
    blurb: str | None
    url: str | None
    isbn: str | None
    price_cents: int | None
    thema: str | None
    reason: MatchReason
    deal: bool
    source_label: str
    source_category: str
    #: Warum dieser Fund hier steht — in denselben Worten wie im Digest, aus
    #: einer Stelle (Ticket 14).
    why: str
    why_short: str
    #: Was das Bewertungstor von dem Buch hält — ``None``, solange es nicht
    #: gelaufen ist.
    stars: int | None = None
    #: Der Dateiname im Cover-Ordner, falls das Bild schon geholt wurde. Eine
    #: Entdeckung hat keine ``book``-Zeile, an der er stehen könnte — er ergibt
    #: sich aus Schlüssel und Adresse und wird deshalb nachgesehen, nicht
    #: gespeichert.
    cover_file: str | None = None
    #: Ein Satz, warum das Buch in Frage kommt. Steht hier **statt** des
    #: Klappentexts: der sagt, wovon das Buch handelt, der Pitch sagt, warum es
    #: für diese Leserin zählt (bewertungsschema.yaml).
    pitch: str | None = None
    #: Was die Sammelausgabe gegenueber den Einzelbaenden spart — ``None``,
    #: wenn es keine ist oder die Baende nicht bekannt sind (ADR 24).
    bundle: BundleAdvantage | None = None
    #: Ob eine Bibliothek den Fund gerade herausgibt. Fuer die Sortierung
    #: gebraucht (#37) — in der Zeile steht es als Zeichen der Quellenart.
    borrowable: bool = False
    #: Wann der Fund zuletzt gesehen wurde. Die Watchlist nennt denselben
    #: Schluessel "zuletzt hinzugefuegt"; ein Fund wird nicht hinzugefuegt,
    #: er taucht auf.
    observed_at: datetime | None = None

    @property
    def is_bundle(self) -> bool:
        """Eine Sammelausgabe — mehrere Baende in einer Ausgabe (ADR 24).

        Abgeleitet und nicht gespeichert: die Auskunft steckt im Titel, und
        eine Spalte dafuer waere eine zweite Wahrheit, die veralten kann.
        """
        return looks_like_bundle(self.title)

    @property
    def baende(self) -> tuple[str, ...]:
        """Die Bandtitel, wenn der Name sie nennt — sonst leer."""
        return volume_titles(self.title)

    @property
    def key(self) -> str:
        """Was im Formular steht. Quelle und Nummer, nicht die Buch-Id — ein
        Buch gibt es zu diesem Fund ja noch gar nicht."""
        return f"{self.source}:{self.source_item_id}"

    @property
    def price(self) -> str | None:
        if self.price_cents is None:
            return None
        return f"{self.price_cents / 100:.2f} €".replace(".", ",")


@dataclass(frozen=True, slots=True)
class Pile:
    items: tuple[Suggestion, ...]
    #: Wie viele es insgesamt sind, auch wenn die Seite weniger zeigt.
    total: int
    hidden_junk: int
    #: Vom Bewertungstor unter dem Schwellwert einsortiert. Nicht verworfen:
    #: das Urteil steht auf der Buchseite, und eine neue Profilversion holt sie
    #: zurück.
    hidden_weak: int = 0
    #: Weder Schnäppchen noch ausleihbar — würde nie gemeldet, steht also auch
    #: nicht im Stapel. Verschwunden ist nichts: fällt der Preis, ist das Buch
    #: wieder da (ADR 19).
    hidden_priced: int = 0
    #: Funde, die die DNB ausdruecklich in einer anderen Sprache fuehrt (#10).
    hidden_language: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.items


def _cover_file(observation: Observation, covers: CoverStore | None = None) -> str | None:
    """Das Titelbild, falls es schon im Ordner liegt.

    Nachgesehen statt gespeichert: der Name ergibt sich allein aus der Adresse,
    und eine Entdeckung hat keine ``book``-Zeile, an der er stehen könnte. Wird
    aus dem Vorschlag später ein Buch, zeigt dessen ``cover_file`` auf dieselbe
    Datei — das Bild wird kein zweites Mal geholt.

    Die Oberfläche lädt nie selbst nach (ADR 3): geholt wird beim Bewerten, und
    nur für das, was durchkommt.

    Der Ordner wird mitgegeben, wo mehrere Zeilen nacheinander fragen: ihn je
    Zeile neu zu bestimmen kostet ein ``Path.resolve`` — gemessen 0,22 ms je
    Fund, 6,6 fuer eine Stapelseite.
    """
    if not observation.cover_url:
        return None
    name = file_name(observation.cover_url)
    ordner = covers if covers is not None else CoverStore(paths.covers_dir())
    return name if ordner.has(name) else None


def _suggestion(
    observation: Observation,
    profile: Profile,
    judgement=None,
    bundle=None,
    covers: CoverStore | None = None,
) -> Suggestion:
    return Suggestion(
        source=observation.source,
        source_item_id=observation.source_item_id,
        title=observation.title,
        author=observation.author,
        blurb=observation.blurb,
        url=observation.url,
        isbn=observation.isbn,
        price_cents=observation.price_cents,
        thema=thema_name(observation.category),
        reason=observation.match_reason,
        deal=is_strong_deal(observation.price_cents, profile),
        source_label=registry.label(profile, observation.source),
        source_category=registry.category(profile, observation.source),
        why=why_shown(observation),
        why_short=short_why(observation),
        stars=judgement.stars if judgement else None,
        cover_file=_cover_file(observation, covers),
        pitch=(judgement.pitch or None) if judgement else None,
        bundle=bundle,
        borrowable=observation.availability is Availability.AVAILABLE,
        observed_at=observation.observed_at,
    )


def pending(
    store: Store,
    profile: Profile,
    *,
    reason: str | None = None,
    limit: int = PAGE_SIZE,
    sort: str | None = None,
) -> Pile:
    """Die Funde, zu denen noch nichts gesagt wurde.

    Entschieden ist ein Fund, sobald es ein Buch mit einer Beziehung gibt, das
    diese Quelle unter dieser Nummer führt — oder das dieselbe ISBN trägt. Der
    zweite Weg ist der Grund, warum eine Entscheidung bei *jeder* Quelle wirkt.
    """
    decided_items = store.decided_items(profile.slug)
    decided_isbns = set(store.books_with_relations(profile.slug))
    found = store.latest_discoveries(profile.slug)
    # Ein Zugriff für den ganzen Stapel, nicht einer je Zeile.
    judgements = store.ratings_for(subject_of(observation) for observation in found)
    # Einmal fuer den ganzen Stapel: Titel -> guenstigster bekannter Preis.
    # Der Buendelvorteil braucht die Preise *anderer* Buecher (ADR 24).
    # Eine Stelle rechnet den Buendelvorteil aus — dieselbe, die der
    # Tagesbericht benutzt (ADR 24).
    buendelvorteil = advantage_finder(store, profile)
    # Einmal fuer die ganze Seite: der Ordner der Titelbilder wird sonst je
    # Zeile neu aufgeloest.
    covers = CoverStore(paths.covers_dir())
    sprache_von = language_finder(store)

    items: list[Suggestion] = []
    hidden_junk = 0
    hidden_priced = 0
    hidden_weak = 0
    hidden_language = 0
    for observation in found:
        if (observation.source, observation.source_item_id) in decided_items:
            continue
        if observation.isbn and observation.isbn in decided_isbns:
            continue
        if is_junk(observation):
            hidden_junk += 1
            continue
        # Vor der Preisregel und vor dem Urteil: ein Fund in fremder Sprache
        # ist kein Kandidat, gleich was er kostet oder wie er bewertet wurde.
        if is_foreign(observation, profile, sprache_von):
            hidden_language += 1
            continue
        # Dieselbe Regel wie im Digest, aus einer Stelle: was dich nie
        # erreichen würde, ist keine Aufgabe. Und was hier nicht steht, kostet
        # weder eine Anfrage für den Klappentext noch ein Urteil.
        vorteil = buendelvorteil(observation)
        if not worth_announcing(observation, profile, bundle_advantage=vorteil):
            hidden_priced += 1
            continue
        # Dieselbe Schwelle wie im Digest: was das Tor zurückhält, ist keine
        # Aufgabe. Ein Fund **ohne** Urteil bleibt — "noch nicht beurteilt" ist
        # etwas anderes als "passt nicht".
        judgement = judgements.get((subject_of(observation), BY_MODEL))
        if judgement is not None and judgement.stars < DEFAULT_THRESHOLD:
            hidden_weak += 1
            continue
        if reason and str(observation.match_reason) != reason:
            continue
        items.append(
            _suggestion(observation, profile, judgement, vorteil, covers)
        )

    # Sortiert wird **vor** dem Abschneiden: sonst zeigte die Seite die
    # ersten fuenfzig einer zufaelligen Reihe, nur huebsch geordnet.
    # Voreingestellt steht das Beste oben und Unbewertetes am Ende — es ist
    # keine Empfehlung, sondern eine offene Frage (#37).
    geordnet = sorting.apply(sorting.SUGGESTIONS, items, sort)

    return Pile(
        items=tuple(geordnet[:limit]),
        total=len(items),
        hidden_junk=hidden_junk,
        hidden_priced=hidden_priced,
        hidden_weak=hidden_weak,
        hidden_language=hidden_language,
    )


def decide(
    store: Store,
    profile: Profile,
    keys: list[str],
    kind: str,
    *,
    now: datetime,
) -> int:
    """Eine Entscheidung auf mehrere Funde anwenden.

    Jeder Fund wird zu einem Buch — gegen vorhandene Bücher geprüft, bevor ein
    neues entsteht (ADR 18) — und bekommt die Beziehung. Die Verknüpfung zur
    Quelle wird mitgeschrieben, damit derselbe Fund beim nächsten Lauf nicht
    wieder im Stapel steht.
    """
    # Zuerst die Art, dann irgendetwas anlegen: `put_relation` prueft sie auch,
    # aber erst nachdem `find_or_create_book` die Zeile geschrieben hat — eine
    # unbekannte Art hinterliess so ein Buch ohne jede Beziehung, und das
    # leitete den Fund von seiner eigenen Seite weg.
    if kind not in RELATION_KINDS:
        raise ValueError(f"unbekannte Beziehung {kind!r}")

    wanted = set(keys)
    if not wanted:
        return 0

    by_key = {
        f"{observation.source}:{observation.source_item_id}": observation
        for observation in store.latest_discoveries(profile.slug)
    }

    decided = 0
    for key in wanted:
        observation = by_key.get(key)
        if observation is None:
            continue
        book = store.find_or_create_book(
            isbn=observation.isbn,
            title=observation.title,
            author=observation.author,
            series=observation.series,
            now=now,
        )
        store.put_relation(profile.slug, book.id, kind, now=now)
        store.put_book_source(
            book.id,
            observation.source,
            outcome="confirmed",
            url=observation.url,
            source_item_id=observation.source_item_id,
            resolved_at=now,
            reason="aus der Triage",
        )
        # Das Titelbild liegt schon auf der Platte — geholt wurde es fuer den
        # Stapel, und geholt wird hier nichts (ADR 3). Ohne diese Zeile verlor
        # ein Fund beim Uebergang zur Watchlist sein Bild: der Stapel rechnet
        # den Dateinamen aus der Adresse aus, die Watchlist-Zeile fragt die
        # `book`-Zeile — und die kannte ihn nicht.
        bild = _cover_file(observation)
        if bild and not book.cover_file:
            store.set_cover(book.id, bild)
        decided += 1
    return decided
