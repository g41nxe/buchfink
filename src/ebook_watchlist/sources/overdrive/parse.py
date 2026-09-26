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
    wert = item.get(field)
    if not isinstance(wert, int) or isinstance(wert, bool):
        raise SourceStructureError(
            f"OverDrive: Titel {item.get('id')!r} nennt kein {field} (sondern {wert!r})"
        )
    return wert


def _text(item: dict, field: str) -> str | None:
    """Ein Feld, das eine Zeichenkette sein *darf*, aber keine sein muss.

    Ohne die Pruefung wurde aus einem Objekt die Zeichenkette
    ``"{'text': 'hallo'}"`` — und die stand danach in der Datenbank, im
    Tagesbericht und im Prompt des Bewertungstors.
    """
    wert = item.get(field)
    if not isinstance(wert, str) or not wert.strip():
        return None
    return wert.strip()


def _isbn(item: dict) -> str | None:
    """Die ISBN des Formats, das die Leserin wirklich oeffnen kann.

    OverDrive fuehrt dieselbe Ausgabe in mehreren Formaten; ``ebook-kobo``
    traegt gar keine. Genommen wird die erste, die eine nennt — sie ist bei den
    gemessenen Titeln fuer alle Formate dieselbe.
    """
    for format_ in item.get("formats") or []:
        if not isinstance(format_, dict) or not format_.get("isbn"):
            continue
        if treffer := _ISBN13.search(str(format_["isbn"]).replace("-", "")):
            return treffer.group(1)
    return None


def parse_title(item: dict) -> Detail:
    """Ein Titel, so wie er in der Trefferliste und als Einzelabruf steht.

    Beide Wege liefern dieselbe Gestalt — deshalb liest sie auch dieselbe
    Funktion, statt dass zwei Fassungen auseinanderlaufen.
    """
    titel = item.get("title")
    if not isinstance(titel, str) or not titel.strip():
        raise SourceStructureError(f"OverDrive: Titel {item.get('id')!r} hat keinen Titel")
    return Detail(
        title=titel.strip(),
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
    bilder = item.get("covers")
    bilder = bilder if isinstance(bilder, dict) else {}
    gross = bilder.get("cover510Wide") or bilder.get("cover300Wide") or {}
    return gross.get("href") if isinstance(gross, dict) else None


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
    wert = item.get(field)
    return wert if isinstance(wert, int) and not isinstance(wert, bool) else 0


def parse_collection(
    data: dict, collection: Collection, *, source: str = "overdrive"
) -> list[Observation]:
    """Die Titel einer Sammlung als Funde: deutsch, E-Book, im Rahmen der Codes.

    Ein Fund aus *Lucky Day* ist sofort ausleihbar — ohne Wartezeit, sieben
    Tage —, auch wenn die gewöhnlichen Exemplare verliehen sind: es zählen die
    Lucky-Day-Exemplare (*Der Hausmann*: 0 frei, 44 im Lucky Day).
    """
    items = data.get("items")
    if not isinstance(items, list):
        raise SourceStructureError(
            f"OverDrive: Sammlung {collection.id!r} ohne items — die Antwort hat sich geändert"
        )
    funde = []
    for item in items:
        if not isinstance(item, dict):
            continue
        art = item.get("type")
        if not isinstance(art, dict) or art.get("id") != sel.COLLECTION_TYPE:
            continue
        sprachen = {s.get("id") for s in item.get("languages") or [] if isinstance(s, dict)}
        if sel.COLLECTION_LANGUAGE not in sprachen:
            continue
        codes = [c for c in item.get("bisacCodes") or [] if isinstance(c, str)]
        if collection.bisac and not any(
            c.startswith(prefix) for c in codes for prefix in collection.bisac
        ):
            continue
        titel = _text(item, "title")
        if titel is None:
            continue
        kennung = title_id(item)
        frei = _count(item, "luckyDayAvailableCopies") or _count(item, "availableCopies")
        funde.append(
            Observation(
                source=source,
                source_item_id=kennung,
                title=titel,
                author=_text(item, "firstCreatorName"),
                match_reason=MatchReason.GENRE_CATEGORY,
                category=collection.name,
                isbn=_isbn(item),
                availability=Availability.AVAILABLE if frei else Availability.UNAVAILABLE,
                cover_url=_cover(item),
                blurb=_text(item, "description"),
                url=sel.TITLE_URL.format(title_id=kennung),
            )
        )
    return funde


def title_id(item: dict) -> str:
    """Woran der Snapshot geschluesselt ist.

    Lieber laut scheitern als eine Identitaet erfinden: eine ausgedachte Nummer
    spaltete die Geschichte eines Titels still in zwei (wie ``require_title_id``
    bei der Onleihe).
    """
    kennung = item.get("id")
    if kennung is None or not str(kennung).strip():
        raise SourceStructureError("OverDrive: ein Treffer ohne id")
    return str(kennung)


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
    sprachen = item.get("languages")
    if not isinstance(sprachen, list) or not sprachen or not isinstance(sprachen[0], dict):
        return None
    return sel.LANGUAGE_CODES.get(str(sprachen[0].get("id") or "").lower())


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
    gefunden = []
    for item in items:
        if not isinstance(item, dict):
            raise SourceStructureError(f"OverDrive: ein Treffer ist kein Objekt: {item!r}")
        # Verlangt werden **Titel und Nummer**, sonst nichts. Eine Trefferliste
        # ist voll von Buechern, die uns nicht gemeint sind; ginge jeder durch
        # ``parse_title``, riss ein fremder Nachbar ohne ``holdsCount`` die
        # ganze Quelle fuer den ganzen Lauf ab — auch fuer die vierzehn Titel,
        # deren Zuordnung laengst steht. Die Onleihe verlangt je Karte genau
        # dasselbe: Titel und Link.
        titel = item.get("title")
        if not isinstance(titel, str) or not titel.strip():
            raise SourceStructureError(f"OverDrive: Treffer {item.get('id')!r} ohne Titel")
        gefunden.append(
            Candidate(
                title=titel.strip(),
                author=_text(item, "firstCreatorName"),
                title_id=title_id(item),
                isbn=_isbn(item),
                cover_url=_cover(item),
                language=_language(item),
            )
        )
    return gefunden
