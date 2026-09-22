"""Die YAML-Dateien einmalig in die Datenbank überführen (Ticket 05, ADR 10).

Vier Dateien werden zu vier Begriffen: **Profil**, **Buch**, **Beziehung**,
**Interesse**. Vorher lagen dieselben Bücher verstreut — *Cold Eternity* stand
in ``owned.yaml`` als Titel, in ``dismissed.yaml`` als beam-Produktnummer, und
war einmal eine Zeile in ``watchlist.yaml``.

``dismissed.yaml`` gehört ausdrücklich nicht dazu: es nennt Produktnummern, und
welches Buch eine Nummer meint, weiß nur der Shop. Das ist eine Anfrage und
kein Import — sie steht in :mod:`ebook_watchlist.dismissals` (Ticket 17).

Das Risiko ist nicht das Schema, sondern der Import. ``liked_books`` ist
Freitext wie ``"Cry Baby - Gillian Flynn"``, und daraus ein Buch zu machen
heißt raten. Es gilt dieselbe Regel wie überall sonst: was sich nicht
zweifelsfrei auflösen lässt, kommt auf die Liste "braucht Aufmerksamkeit" und
wird **nicht** erraten (ADR 8).

Der Import ist wiederholbar. Ein zweiter Lauf legt nichts doppelt an, und er
setzt nichts zurück, was die Leserin inzwischen in der Oberfläche geändert hat
— nur fehlende Zeilen kommen dazu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .config import OwnedBook, Settings, WatchlistEntry
from .ratings import BY_CONVERSATION, book_subject
from .relations import InterestKey, RelationKind
from .store import Store

#: Die Profilfassung, gegen die die Urteile in ``owned.yaml`` entstanden sind.
OWNED_PROFILE_VERSION = 1
#: ``owned.yaml`` nennt zu keinem Eintrag eine Sicherheit — der Dateikopf
#: beschreibt ein ``confidence``-Feld, das kein Eintrag trägt. Also tragen alle
#: dieselbe ein, und zwar die mittlere: die Urteile entstanden im Gespräch über
#: Titel, Reihe und Klappentextebene, nicht über gelesene Texte. Sie je Eintrag
#: zu unterscheiden hieße, eine Angabe zu erfinden, die die Datei nicht macht.
OWNED_CONFIDENCE = "teils"

#: ``"Cry Baby - Gillian Flynn"`` -> Titel und Autor:in. Der Bindestrich ist die
#: Konvention dieser Liste; ein Titel, der selbst einen enthält, wird an der
#: *letzten* Trennung geteilt, weil der Name hinten steht.
#: Der Namensteil darf keine Ziffern tragen. Ohne das wurde aus
#: "Achtsam morden - Karsten Dusse - Band 1" ein Buch der Autorin
#: "Band 1" - der Ausdruck teilt an der *letzten* Trennung, und ein
#: angehaengter Bandzusatz sieht von hinten aus wie ein Name.
_FREE_TEXT = re.compile(r"^(?P<title>.+?)\s+[-–—]\s+(?P<author>[^-–—\d]+)$")
#: Ein Klammerzusatz am Ende ist eine Begruendung, kein Namensbestandteil.
_TRAILING_NOTE = re.compile(r"\s*\((?P<note>[^()]*)\)\s*$")


@dataclass(slots=True)
class SeedReport:
    """Was der Import getan hat — und was er nicht zu entscheiden wagte."""

    books: int = 0
    relations: int = 0
    interests: int = 0
    #: Urteile aus ``owned.yaml`` — Maschinenurteile, keine der Leserin.
    ratings: int = 0
    #: Freitext, der sich nicht zweifelsfrei auflösen liess. Kein Fehler,
    #: sondern eine Frage an einen Menschen.
    unresolved: list[str] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return bool(self.unresolved)


def split_free_text(entry: str) -> tuple[str, str | None, str | None]:
    """``"Cry Baby - Gillian Flynn"`` -> ``("Cry Baby", "Gillian Flynn", None)``.

    Ein Klammerzusatz am Ende ist eine Begruendung, kein Teil des Namens:
    ``"Der Schwarm - Frank Schätzing (Grund: langsames Erzähltempo)"``. Ohne
    diese Regel klebte der Grund am Autornamen, und jeder spaetere Vergleich
    haette gegen "Frank Schätzing (Grund: …)" gematcht.

    Ohne erkennbare Trennung bleibt der ganze Text der Titel. Einen Namen aus
    einem Text zu raten, der keinen nennt, wäre genau die Sorte stille
    Erfindung, die dieses Werkzeug vermeidet.
    """
    cleaned = " ".join(entry.split())
    note = None
    trailing = _TRAILING_NOTE.search(cleaned)
    if trailing is not None:
        note = trailing.group("note").strip() or None
        cleaned = cleaned[: trailing.start()].strip()

    match = _FREE_TEXT.match(cleaned)
    if match is None:
        return cleaned, None, note
    return match.group("title").strip(), match.group("author").strip(), note


def _book_for_free_text(
    store: Store, entry: str, now: datetime
) -> tuple[int | None, str | None]:
    title, author, note = split_free_text(entry)
    if not title or author is None:
        # Nichts, woran ein Titel sich festmachen liesse. Der Matcher wuerde
        # hier auf gut Glueck vergleichen; das ist die Stelle, an der wir
        # fragen statt zu raten (ADR 8).
        return None, note
    book = store.find_or_create_book(isbn=None, title=title, author=author, now=now)
    return book.id, note


def _put_missing_relation(
    store: Store, profile_slug: str, book_id: int, kind: str, *,
    active: bool = True, now: datetime, **details: object,
) -> bool:
    """Eine Beziehung anlegen, wenn es sie noch nicht gibt. Wahr, wenn ja.

    ``put_relation`` ist für die Oberfläche gebaut und setzt ``active`` und die
    Angaben auch an einer bestehenden Zeile. Blind aufgerufen hätte ein zweiter
    Import eine pausierte Beobachtung wiederbelebt und eine aufgehobene
    Einschränkung zurückgebracht — genau das, was der Modulkopf ausschließt.
    Dieselbe Regel wie in :mod:`ebook_watchlist.dismissals`.
    """
    if any(row.kind == kind for row in store.relations_of(profile_slug, book_id)):
        return False
    store.put_relation(profile_slug, book_id, kind, active=active, now=now, **details)
    return True


def seed(store: Store, settings: Settings, watchlist: list[WatchlistEntry],
         *, owned: list[OwnedBook] | None = None,
         now: datetime | None = None) -> SeedReport:
    """Alles einlesen, was heute in YAML steht."""
    at = now or datetime.now()
    report = SeedReport()
    before = len(store.books())

    # --- Watchlist: Titel und Autor:in stehen ausdruecklich da --------------
    for entry in watchlist:
        book = store.find_or_create_book(
            isbn=None, title=entry.title, author=entry.author, now=at
        )
        details: dict[str, object] = {}
        if entry.notes:
            details["note"] = entry.notes
        # Die *Art* der Quelle, nicht ihr Name: wie eine Bibliothek in dieser
        # Installation heisst, sagt die Konfiguration, und ein Import darf sich
        # keinen Namen ausdenken. "voebb" und "beam" hier hart einzutragen war
        # genau das - und wäre bei jeder umbenannten Quelle falsch gewesen.
        if entry.check_library != entry.check_shop:
            details["restrict"] = "library" if entry.check_library else "shop"
        if _put_missing_relation(
            store,
            settings.slug,
            book.id,
            str(RelationKind.WATCHING),
            active=entry.active,
            now=at,
            **details,
        ):
            report.relations += 1

    # --- Gefallen und nicht gefallen: Freitext, also mit Vorbehalt ----------
    for kind, entries in (
        (RelationKind.LIKED, settings.liked_books),
        (RelationKind.DISLIKED, settings.disliked_books),
    ):
        for entry in entries:
            book_id, note = _book_for_free_text(store, entry, at)
            if book_id is None:
                report.unresolved.append(f"{kind}: {entry}")
                continue
            details = {"note": note} if note else {}
            if _put_missing_relation(store, settings.slug, book_id, str(kind), now=at, **details):
                report.relations += 1

    # --- Besitz: Titel und Autor:in stehen da, das Urteil auch -------------
    # Der Import ging bisher an dieser Datei vorbei; sie trug ihren eigenen
    # Hinweis, dass sie von nichts gelesen wird. Die Sterne darin sind
    # ausdrücklich **Maschinenurteile** (ADR 17, Ticket 21) — sie kommen
    # deshalb mit ``origin=conversation`` an und nicht als das, was die Leserin
    # gesagt hätte.
    for entry in owned or []:
        book = store.find_or_create_book(
            isbn=None, title=entry.title, author=entry.author, now=at
        )
        # Der ``hinweis`` betrifft die Identifikation, nicht das Urteil: er
        # bittet um Gegenprüfung, ob dieser Titel im Handel so heißt. Genau das
        # gehört an die Beziehung, wo die Leserin es beim Nachsehen findet.
        details = {"note": entry.hinweis} if entry.hinweis else {}
        if _put_missing_relation(
            store, settings.slug, book.id, str(RelationKind.OWNED), now=at, **details
        ):
            report.relations += 1
            # Was "besitze ich" in der Oberfläche tut, tut auch der Import: ein
            # gekauftes Buch wird nicht weiter beobachtet (Ticket 48), und die
            # Beobachtung wird stillgelegt, nicht gelöscht (ADR 18). Nur bei
            # neuem Besitz — hat die Leserin neben einem bekannten Besitz die
            # Beobachtung wieder eingeschaltet, bleibt sie an. Und nur, wenn es
            # eine gibt: sonst stünde da ein "Früher: beobachtet", das nie galt.
            watching = str(RelationKind.WATCHING)
            if any(row.kind == watching for row in store.relations_of(settings.slug, book.id)):
                store.deactivate_relation(settings.slug, book.id, watching, now=at)
        if entry.stars is None:
            continue
        store.put_rating(
            book_subject(book.id),
            stars=entry.stars,
            confidence=OWNED_CONFIDENCE,
            reason=entry.why or "",
            profile_version=OWNED_PROFILE_VERSION,
            now=at,
            origin=BY_CONVERSATION,
        )
        report.ratings += 1

    # Die alten Ablehnungen stehen hier bewusst nicht mehr. Sie sind je Shop
    # eine Produktnummer, und die sagt nicht, welches Buch gemeint ist — nur
    # der Shop kann das. Das ist eine Anfrage, und eine Anfrage gehoert nicht
    # in einen Import: ``ebw dismissals`` loest sie einmalig auf (Ticket 17).

    # --- Interessen: Autor:innen und Themen --------------------------------
    for author in settings.reference_authors:
        store.put_interest(settings.slug, str(InterestKey.AUTHOR), author, now=at, tier="core")
        report.interests += 1
    for author in settings.extended_authors:
        if author in settings.reference_authors:
            continue
        store.put_interest(
            settings.slug, str(InterestKey.AUTHOR), author, now=at, tier="extended"
        )
        report.interests += 1
    for category in settings.genre_categories:
        store.put_interest(settings.slug, str(InterestKey.THEMA), category, now=at, tier="core")
        report.interests += 1

    report.books = len(store.books()) - before
    return report
