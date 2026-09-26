"""Die Deutsche Nationalbibliothek fragen (Ticket 42, ADR 25).

**Keine Quelle in unserem Sinn.** Eine ``Source`` liefert Preis und
Verfügbarkeit, hat ``probe``, ``search``, ``check``, ``item`` und wird bei
jedem Lauf befragt. Die DNB liefert nichts davon — sie beantwortet *eine*
Frage zu *einer* ISBN: was ist das für ein Buch. Deshalb steht sie neben den
Quellen, nicht unter ihnen.

Sie beantwortet, was sonst niemand sagt:

===============  =====================================================
MARC             was daraus wird
===============  =====================================================
``245 $a``       Titel, ohne Untertitel
``245 $b``       Untertitel — bei einer Sammelausgabe oft die Bandzahl
                 im Klartext („Zwei Hunter-und-Garcia-Thriller")
``041 $a``       Sprache, die kein Shop und keine Bibliothek nennt
``490 $a/$v``    Reihe und Bandnummer
``770 $i/$z``    **Enthält** — die ISBNs der Bände einer Sammelausgabe
===============  =====================================================

Gemessen am 06.09.2026: von drei Sammelausgaben im Bestand trägt eine das
``770``-Feld, und dort stimmen alle drei ISBNs mit Büchern überein, deren
Preis wir kennen. Von dreißig Büchern der früheren Messung kannte die DNB
einundzwanzig.

Der Umgang ist absichtlich zurückhaltend: die DNB dokumentiert **keine**
zulässige Anfragefrequenz (`docs/research/metadata-sources-legal.md`). Gefragt
wird deshalb einmal je Buch und mit einer Obergrenze je Lauf — nicht, weil die
Technik es verlangt, sondern aus derselben Höflichkeit, mit der wir den Shop
seriell und mit Pause abfragen.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from .http import FetchError, HttpClient, RateLimited

if TYPE_CHECKING:
    from .store import Store

SRU_URL = "https://services.dnb.de/sru/dnb"

#: Ein ``datafield`` mit seinem Inhalt. Kein XML-Parser: die Antwort ist eine
#: flache, wohlgeformte Liste von Feldern, und ``lxml`` dafür zu laden hiesse,
#: einen Baum aufzubauen, um drei Zweige zu lesen.
_FIELD = re.compile(r'<datafield[^>]*tag="(\d+)"[^>]*>(.*?)</datafield>', re.S)
_SUBFIELD = re.compile(r'<subfield[^>]*code="(\w)"[^>]*>(.*?)</subfield>', re.S)
_RECORDS = re.compile(r"numberOfRecords>(\d+)<")
#: Die DNB schreibt Sortierzeichen um Artikel: ``&#152;Der&#156; Kruzifix``.
_SORT_MARKS = re.compile(r"&#15[26];|[]")
_ISBN13 = re.compile(r"^97[89]\d{10}$")


@dataclass(frozen=True, slots=True)
class Record:
    """Was die DNB über ein Buch sagt. Jedes Feld darf fehlen."""

    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    series: str | None = None
    series_index: str | None = None
    language: str | None = None
    #: ISBNs der enthaltenen Bände, aus ``770 $i Enthält``.
    contains: tuple[str, ...] = ()
    #: Der Titel des Originals, aus ``240 $a`` — bei einer Übersetzung der
    #: Schlüssel zu allem, was nur die englische Ausgabe kennt (#17).
    original_title: str | None = None
    #: Die Schlagwörter des Verlags aus ``653``: Motive und Vergleichstitel.
    #: Ohne die Codes für den Handel, die dort in Klammern vorangestellt sind.
    keywords: tuple[str, ...] = ()
    #: Der Verlag, aus ``264 $b`` (aeltere Saetze: ``260 $b``) — die
    #: Rueckfallquelle fuer den Abzug bei Selbstverlag (#28).
    publisher: str | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            (self.title, self.subtitle, self.author, self.series, self.language, self.contains)
        )


def _clean(text: str) -> str:
    # Die DNB liefert Umlaute zerlegt: "a" und ein kombinierendes Trema. Das
    # sieht gleich aus und vergleicht ungleich — "Realität" fand sich in den
    # eigenen Schlagwörtern nicht wieder. NFC setzt sie zusammen (#17).
    return unicodedata.normalize("NFC", _SORT_MARKS.sub("", text)).strip()


def _fields(xml: str) -> list[tuple[str, dict[str, list[str]]]]:
    out: list[tuple[str, dict[str, list[str]]]] = []
    for tag, content in _FIELD.findall(xml):
        parts: dict[str, list[str]] = {}
        for code, value in _SUBFIELD.findall(content):
            parts.setdefault(code, []).append(_clean(value))
        out.append((tag, parts))
    return out


def parse(xml: str) -> Record:
    """Einen SRU-Treffer in einen :class:`Record` überführen.

    Rein und ohne Netz, damit sich das Auswerten an gespeicherten Antworten
    prüfen lässt — dieselbe Trennung wie bei den Quellen.
    """
    hit = _RECORDS.search(xml)
    if hit and hit.group(1) == "0":
        return Record()

    title = subtitle = author = series = volume = language = original = publisher = None
    contained: list[str] = []
    subjects: list[str] = []

    for tag, parts in _fields(xml):
        first = {code: values[0] for code, values in parts.items() if values}
        if tag == "245":
            title = title or first.get("a")
            subtitle = subtitle or first.get("b")
            author = author or first.get("c")
            volume = volume or first.get("n")
        elif tag == "100":
            author = first.get("a") or author
        elif tag == "490":
            series = series or first.get("a")
            volume = volume or first.get("v")
        elif tag in ("264", "260"):
            publisher = publisher or first.get("b")
        elif tag == "240":
            original = original or first.get("a")
        elif tag == "653":
            # "(BISAC Subject Heading)FIC050000", "(VLB-WN)9112": Codes fuer
            # den Handel. Was ohne Klammer beginnt, hat ein Mensch geschrieben.
            subjects += [w for w in parts.get("a", []) if w and not w.startswith("(")]
        elif tag == "041":
            language = language or first.get("a")
        elif tag == "770":
            # Der Hinweis steht in $i; "Enthält" ist der Fall, der uns angeht.
            # Kleingeschrieben verglichen und nur am Anfang, weil die DNB
            # auch "Enthält außerdem" schreibt.
            if first.get("i", "").lower().startswith("enth"):
                for value in parts.get("z", []):
                    if _ISBN13.match(value):
                        contained.append(value)

    return Record(
        title=title,
        subtitle=subtitle,
        author=author,
        series=series,
        series_index=volume,
        language=language,
        contains=tuple(dict.fromkeys(contained)),
        original_title=original,
        keywords=tuple(dict.fromkeys(subjects)),
        publisher=publisher,
    )


@dataclass(slots=True)
class Dnb:
    """Eine ISBN rein, ein :class:`Record` raus."""

    client: HttpClient
    base: str = SRU_URL
    #: Zählt, was dieser Lauf gefragt hat — die Obergrenze wird beim Aufrufer
    #: durchgesetzt, gezählt wird hier.
    asked: int = field(default=0)

    def about(self, isbn: str) -> Record | None:
        """Der Datensatz zu dieser ISBN, oder ``None``, wenn die DNB schweigt.

        ``None`` ist eine **Antwort**, kein Fehler: neun von dreißig Büchern
        kennt sie nicht, und der Aufrufer hält das fest, damit nicht jeder Lauf
        dieselbe Frage stellt.
        """
        self.asked += 1
        try:
            xml = self.client.get(
                self.base,
                params={
                    "version": "1.1",
                    "operation": "searchRetrieve",
                    "query": f"WOE={isbn}",
                    "recordSchema": "MARC21-xml",
                    "maximumRecords": "1",
                },
            )
        except FetchError:
            # Eine unerreichbare Bibliothek ist kein Grund, einen Lauf zu
            # beenden — dasselbe Zugestaendnis wie bei einem Titelbild.
            return None
        record = parse(xml)
        return None if record.is_empty else record


@dataclass(slots=True)
class OriginalTitles:
    """Der Originaltitel zu ISBNs, fuer die Zuordnung eines Watchlist-Titels (#77).

    Erst die Tabelle ``dnb_record``, dann — nur fuer das, was sie nicht kennt
    — die DNB selbst, und deren Antwort landet in derselben Tabelle, genau wie
    beim Nachschlagen hinter dem Snapshot (ADR 25). Die Frage kostet also
    einmal je ISBN, nicht einmal je Lauf.

    ``budget`` ist dieselbe Obergrenze wie ``dnb_budget``: was die Zuordnung
    verbraucht, steht dem Nachschlagen hinter dem Snapshot nicht mehr zur
    Verfuegung (:attr:`spent`). Ohne ``dnb`` antwortet nur die Tabelle — so
    arbeitet jeder Weg, der keine Anfragen stellen soll.
    """

    store: Store
    dnb: Dnb | None = None
    budget: int = 0
    now: datetime | None = None
    #: Was davon verbraucht ist. Eine gedrosselte DNB verbraucht den Rest:
    #: 429 heisst Halt, auch fuer alles, was nach der Zuordnung noch kaeme.
    spent: int = 0

    def __call__(self, isbns: Sequence[str]) -> dict[str, tuple[str, ...]]:
        known = self.store.dnb_original_titles(isbns)
        for isbn in isbns:
            if isbn in known or self.dnb is None or self.spent >= self.budget:
                continue
            self.spent += 1
            try:
                record = self.dnb.about(isbn)
            except RateLimited:
                self.spent = self.budget
                break
            except Exception:  # noqa: BLE001 - eine Auskunft, nicht die Zuordnung
                continue
            # Auch das Schweigen, damit niemand dieselbe ISBN erneut fragt.
            self.store.save_dnb(isbn, record, self.now or datetime.now())
            known[isbn] = (
                tuple(n for n in (record.original_title, record.title) if n)
                if record
                else ()
            )
        return known
