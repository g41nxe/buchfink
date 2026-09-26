"""Aus OverDrive-JSON Werte machen. Reine Funktionen — kein Netz, keine Config.

Dasselbe Versprechen wie im Onleihe-Parser: Jede Funktion wirft
:class:`SourceStructureError`, sobald die Antwort nicht mehr aussieht wie das,
was die Recherche beschrieben hat. Diese Lautstaerke ist der Zweck — ein still
leeres Ergebnis ist von "heute nichts Neues" nicht zu unterscheiden (ADR 7).

Ein JSON-Feld, das *fehlen darf*, ist etwas anderes als eine Antwort, die nicht
mehr die erwartete Gestalt hat. Ein fehlender Klappentext ist Alltag; eine
Antwort ohne ``items`` ist ein Umbau.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ...models import Availability, MatchReason, Observation
from ..base import SourceStructureError
from . import selectors as sel

#: Dieselbe Pruefung wie bei den beiden anderen Quellen: eine ISBN-13 beginnt
#: mit 978 oder 979. Ungeprueft durchgereicht kostet sie zweierlei — der
#: Matcher vergleicht Kennungen **zeichengenau**, und eine zweite Schreibweise
#: derselben ISBN legt in ``books.find_book`` eine zweite Buchzeile an.
_ISBN13 = re.compile(r"\b(97[89]\d{10})\b")


def payload(text: str) -> dict:
    """Die Antwort als Objekt — oder ein lauter Fehler."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SourceStructureError(f"OverDrive: Antwort ist kein JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SourceStructureError(f"OverDrive: Antwort ist kein Objekt, sondern {type(data)}")
    return data


@dataclass(frozen=True, slots=True)
class Detail:
    """Was OverDrive ueber einen Titel sagt."""

    title: str
    author: str | None
    isbn: str | None
    #: Wie viele Lizenzen die Bibliothek haelt und wie viele davon frei sind.
    owned_copies: int
    available_copies: int
    #: Wie viele Vormerkungen anstehen.
    holds: int
    blurb: str | None = None
    cover_url: str | None = None

    @property
    def availability(self) -> Availability:
        """Verliehen ist nicht dasselbe wie "fuehrt die Bibliothek nicht".

        Ohne eine einzige Lizenz weiss OverDrive ueber diesen Titel nichts zu
        sagen, was eine Verfuegbarkeit waere — das ist ``unknown`` und nicht
        ``unavailable``, denn "verliehen" verspricht, dass er zurueckkommt.
        """
        if self.owned_copies <= 0:
            return Availability.UNKNOWN
        return Availability.AVAILABLE if self.available_copies > 0 else Availability.UNAVAILABLE


def _int(item: dict, field: str) -> int:
    """Eine Zahl, die dasein muss. Fehlt sie, hat sich die Antwort geaendert."""
    value = item.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SourceStructureError(
            f"OverDrive: Titel {item.get('id')!r} nennt kein {field} (sondern {value!r})"
        )
    return value


def _text(item: dict, field: str) -> str | None:
    """Ein Feld, das eine Zeichenkette sein *darf*, aber keine sein muss.

    Ohne die Pruefung wurde aus einem Objekt die Zeichenkette
    ``"{'text': 'hallo'}"`` — und die stand danach in der Datenbank, im
    Tagesbericht und im Prompt des Bewertungstors.
    """
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _isbn(item: dict) -> str | None:
    """Die ISBN des Formats, das die Leserin wirklich oeffnen kann.

    OverDrive fuehrt dieselbe Ausgabe in mehreren Formaten; ``ebook-kobo``
    traegt gar keine. Genommen wird die erste, die eine nennt — sie ist bei den
    gemessenen Titeln fuer alle Formate dieselbe.
    """
    for format_ in item.get("formats") or []:
        if not isinstance(format_, dict) or not format_.get("isbn"):
            continue
        if hit := _ISBN13.search(str(format_["isbn"]).replace("-", "")):
            return hit.group(1)
    return None


def parse_title(item: dict) -> Detail:
    """Ein Titel, so wie er in der Trefferliste und als Einzelabruf steht.

    Beide Wege liefern dieselbe Gestalt — deshalb liest sie auch dieselbe
    Funktion, statt dass zwei Fassungen auseinanderlaufen.
    """
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise SourceStructureError(f"OverDrive: Titel {item.get('id')!r} hat keinen Titel")
    return Detail(
        title=title.strip(),
        author=_text(item, "firstCreatorName"),
        isbn=_isbn(item),
        owned_copies=_int(item, "ownedCopies"),
        available_copies=_int(item, "availableCopies"),
        holds=_int(item, "holdsCount"),
        blurb=_text(item, "description"),
        cover_url=_cover(item),
    )


def _cover(item: dict) -> str | None:
    """Die Adresse des Titelbilds, aus ``covers``.

    ``covers`` ist ebenso gegen eine fremde Gestalt gesichert wie das Bild
    darunter: eine Liste statt eines Objekts warf einen ``AttributeError``,
    und der steht im Tagesbericht als Panne statt als Auskunft (ADR 7).
    """
    images = item.get("covers")
    images = images if isinstance(images, dict) else {}
    large = images.get("cover510Wide") or images.get("cover300Wide") or {}
    return large.get("href") if isinstance(large, dict) else None


@dataclass(frozen=True, slots=True)
class Collection:
    """Eine Sammlung der Bibliothek als Vorschlagsquelle (#74), etwa „Lucky Day".

    ``bisac`` sind Präfixe der BISAC-Codes, von denen ein Titel einen tragen
    muss: voreingestellt ``FIC``, also Belletristik — eine Sammlung führt auch
    Kochbücher und Politik. Den Geschmack prüft das Tor, nicht die Quelle.
    """

    id: str
    name: str
    bisac: tuple[str, ...] = ("FIC",)


def _count(item: dict, field: str) -> int:
    value = item.get(field)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


#: Die BISAC-Präfixe der Belletristik: für Erwachsene und für Jugendliche.
FICTION_CODES = ("FIC", "YAF")


def observation_of(
    item: dict,
    *,
    source: str,
    reason: MatchReason,
    category: str | None = None,
    lucky_day: bool = False,
) -> Observation | None:
    """Ein Titel als Fund: E-Book auf Deutsch, sonst nichts (#74).

    ``lucky_day``: es zählen die Lucky-Day-Exemplare, die ohne Wartezeit zu
    leihen sind, auch wenn die gewöhnlichen verliehen sind.
    """
    art = item.get("type")
    if not isinstance(art, dict) or art.get("id") != sel.COLLECTION_TYPE:
        return None
    sprachen = {s.get("id") for s in item.get("languages") or [] if isinstance(s, dict)}
    if sel.COLLECTION_LANGUAGE not in sprachen:
        return None
    codes = [c for c in item.get("bisacCodes") or [] if isinstance(c, str)]
    if any(c.startswith("JUV") for c in codes):
        return None  # ein Kinderbuch: das Thema Science-Fiction schließt sie ein
    titel = _text(item, "title")
    if titel is None:
        return None
    titel = re.sub(r"<[^>]+>", "", titel).strip()  # „Star Wars<sup>TM</sup>"
    kennung = title_id(item)
    frei = _count(item, "availableCopies")
    if lucky_day:
        frei = _count(item, "luckyDayAvailableCopies") or frei
    return Observation(
        source=source,
        source_item_id=kennung,
        title=titel,
        author=_text(item, "firstCreatorName"),
        match_reason=reason,
        category=category,
        isbn=_isbn(item),
        availability=Availability.AVAILABLE if frei else Availability.UNAVAILABLE,
        cover_url=_cover(item),
        blurb=_text(item, "description"),
        url=sel.TITLE_URL.format(title_id=kennung),
    )


def _items(data: dict, what: str) -> list:
    items = data.get("items")
    if not isinstance(items, list):
        raise SourceStructureError(f"OverDrive: {what} ohne items — die Antwort hat sich geändert")
    return [item for item in items if isinstance(item, dict)]


def parse_collection(
    data: dict, collection: Collection, *, source: str = "overdrive"
) -> list[Observation]:
    """Die Titel einer Sammlung als Funde: deutsch, E-Book, im Rahmen der Codes.

    Ein Fund aus *Lucky Day* ist sofort ausleihbar — ohne Wartezeit, sieben
    Tage —, auch wenn die gewöhnlichen Exemplare verliehen sind: es zählen die
    Lucky-Day-Exemplare (*Der Hausmann*: 0 frei, 44 im Lucky Day).
    """
    funde = []
    for item in _items(data, f"Sammlung {collection.id!r}"):
        codes = [c for c in item.get("bisacCodes") or [] if isinstance(c, str)]
        if collection.bisac and not any(
            c.startswith(prefix) for c in codes for prefix in collection.bisac
        ):
            continue
        fund = observation_of(
            item, source=source, reason=MatchReason.GENRE_CATEGORY,
            category=collection.name, lucky_day=True,
        )
        if fund is not None:
            funde.append(fund)
    return funde


def parse_finds(
    data: dict, *, source: str, reason: MatchReason, category: str | None = None
) -> list[Observation]:
    """Die Treffer einer Suche als Funde — für Autor:innen und Themen (#74).

    Ein Thema der Leserin ist Belletristik: dort zählt nur, was einen Code der
    Belletristik trägt (``FIC``, für Jugendbücher ``YAF``). Das Thema „Science
    Fiction" bei OverDrive führt auch Sachbücher über das Universum.
    """
    funde = []
    for item in _items(data, "Suche"):
        codes = [c for c in item.get("bisacCodes") or [] if isinstance(c, str)]
        if reason is MatchReason.GENRE_CATEGORY and not any(
            c.startswith(FICTION_CODES) for c in codes
        ):
            continue
        fund = observation_of(item, source=source, reason=reason, category=category)
        if fund is not None:
            funde.append(fund)
    return funde


def title_id(item: dict) -> str:
    """Woran der Snapshot geschluesselt ist.

    Lieber laut scheitern als eine Identitaet erfinden: eine ausgedachte Nummer
    spaltete die Geschichte eines Titels still in zwei (wie ``require_title_id``
    bei der Onleihe).
    """
    item_id = item.get("id")
    if item_id is None or not str(item_id).strip():
        raise SourceStructureError("OverDrive: ein Treffer ohne id")
    return str(item_id)


@dataclass(frozen=True, slots=True)
class Candidate:
    """Ein Treffer der Suche, so weit die Zuordnung ihn braucht."""

    title: str
    author: str | None
    title_id: str
    #: Die ISBN des Treffers. Sie ist der Grund, warum diese Quelle "Dark
    #: Matter" ueberhaupt findet: der Titel-Normalisierer macht aus
    #: "Dark Matter - der Zeitenlaeufer" ein "dark matter" und aus
    #: "Der Zeitenläufer (Dark Matter)" ein "zeitenlaufer" — die Klammer gilt
    #: ihm als Ausgabenrauschen, hier steht aber der Originaltitel darin.
    isbn: str | None = None
    #: Das Titelbild des Treffers — bei einer offenen Zuordnung entscheidet
    #: das Auge, welcher der richtige ist (Ticket 41).
    cover_url: str | None = None
    #: Die Sprache der Ausgabe, als Code der DNB (``ger``, ``eng``). Seit ein
    #: Watchlist-Titel auch ohne Sprachfilter gesucht wird, kann das eine
    #: andere als Deutsch sein, und die Kachel sagt es dann (#77).
    language: str | None = None


def _language(item: dict) -> str | None:
    """Die erste Sprache der Karte, in den Codes der DNB — oder nichts.

    Eine fremde Gestalt schweigt statt zu werfen: die Sprache ist eine
    Kennzeichnung, keine Voraussetzung, und ein Umbau an dieser Stelle darf
    keine Zuordnung kosten.
    """
    languages = item.get("languages")
    if not isinstance(languages, list) or not languages or not isinstance(languages[0], dict):
        return None
    return sel.LANGUAGE_CODES.get(str(languages[0].get("id") or "").lower())


def parse_search(text: str) -> list[Candidate] | None:
    """Die Treffer einer Suche — ``None`` heisst: die Bibliothek fuehrt ihn nicht.

    Kein Treffer ist eine **Antwort**, kein Fehler: der Katalog hat
    nachgesehen. Fehlt dagegen ``items`` ganz, hat sich die Schnittstelle
    geaendert, und das darf nicht wie "nichts gefunden" aussehen (ADR 7).
    """
    data = payload(text)
    items = data.get("items")
    if not isinstance(items, list):
        raise SourceStructureError("OverDrive: Antwort ohne Trefferliste 'items'")
    if not items:
        return None
    found = []
    for item in items:
        if not isinstance(item, dict):
            raise SourceStructureError(f"OverDrive: ein Treffer ist kein Objekt: {item!r}")
        # Verlangt werden **Titel und Nummer**, sonst nichts. Eine Trefferliste
        # ist voll von Buechern, die uns nicht gemeint sind; ginge jeder durch
        # ``parse_title``, riss ein fremder Nachbar ohne ``holdsCount`` die
        # ganze Quelle fuer den ganzen Lauf ab — auch fuer die vierzehn Titel,
        # deren Zuordnung laengst steht. Die Onleihe verlangt je Karte genau
        # dasselbe: Titel und Link.
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            raise SourceStructureError(f"OverDrive: Treffer {item.get('id')!r} ohne Titel")
        found.append(
            Candidate(
                title=title.strip(),
                author=_text(item, "firstCreatorName"),
                title_id=title_id(item),
                isbn=_isbn(item),
                cover_url=_cover(item),
                language=_language(item),
            )
        )
    return found
