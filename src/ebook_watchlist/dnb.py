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
from dataclasses import dataclass, field

from .http import FetchError, HttpClient

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
    aus: list[tuple[str, dict[str, list[str]]]] = []
    for tag, inhalt in _FIELD.findall(xml):
        teile: dict[str, list[str]] = {}
        for code, wert in _SUBFIELD.findall(inhalt):
            teile.setdefault(code, []).append(_clean(wert))
        aus.append((tag, teile))
    return aus


def parse(xml: str) -> Record:
    """Einen SRU-Treffer in einen :class:`Record` überführen.

    Rein und ohne Netz, damit sich das Auswerten an gespeicherten Antworten
    prüfen lässt — dieselbe Trennung wie bei den Quellen.
    """
    treffer = _RECORDS.search(xml)
    if treffer and treffer.group(1) == "0":
        return Record()

    titel = untertitel = autor = reihe = band = sprache = original = verlag = None
    enthalten: list[str] = []
    schlagwoerter: list[str] = []

    for tag, teile in _fields(xml):
        erste = {code: werte[0] for code, werte in teile.items() if werte}
        if tag == "245":
            titel = titel or erste.get("a")
            untertitel = untertitel or erste.get("b")
            autor = autor or erste.get("c")
            band = band or erste.get("n")
        elif tag == "100":
            autor = erste.get("a") or autor
        elif tag == "490":
            reihe = reihe or erste.get("a")
            band = band or erste.get("v")
        elif tag in ("264", "260"):
            verlag = verlag or erste.get("b")
        elif tag == "240":
            original = original or erste.get("a")
        elif tag == "653":
            # "(BISAC Subject Heading)FIC050000", "(VLB-WN)9112": Codes fuer
            # den Handel. Was ohne Klammer beginnt, hat ein Mensch geschrieben.
            schlagwoerter += [w for w in teile.get("a", []) if w and not w.startswith("(")]
        elif tag == "041":
            sprache = sprache or erste.get("a")
        elif tag == "770":
            # Der Hinweis steht in $i; "Enthält" ist der Fall, der uns angeht.
            # Kleingeschrieben verglichen und nur am Anfang, weil die DNB
            # auch "Enthält außerdem" schreibt.
            if erste.get("i", "").lower().startswith("enth"):
                for wert in teile.get("z", []):
                    if _ISBN13.match(wert):
                        enthalten.append(wert)

    return Record(
        title=titel,
        subtitle=untertitel,
        author=autor,
        series=reihe,
        series_index=band,
        language=sprache,
        contains=tuple(dict.fromkeys(enthalten)),
        original_title=original,
        keywords=tuple(dict.fromkeys(schlagwoerter)),
        publisher=verlag,
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
        datensatz = parse(xml)
        return None if datensatz.is_empty else datensatz
