"""Titelbilder — einmal geholt, danach lokal (Ticket 15, ADR 20).

Nichts auf diesen Seiten laedt von einem Dritten nach. Ein verlinktes Bild
wuerde dem Shop bei jedem Seitenaufruf mitteilen, welches Buch die Leserin
gerade ansieht; ein einmal geholtes und lokal abgelegtes tut das nicht. Fuer
den Shop ist das ausserdem *weniger* Verkehr, nicht mehr.

Geholt wird nur, wo es sich lohnt: fuer Buecher mit einer ``book``-Zeile, also
solche, zu denen die Leserin eine Beziehung hat (ADR 18) — und fuer Entdeckungen
erst, wenn das Bewertungstor sie durchgelassen hat. Fuer jede Entdeckung ein
Bild zu ziehen waeren dreihundert Anfragen pro Lauf statt einer Handvoll; fuer
die zwanzig, die uebrig bleiben, sind es zwanzig.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from . import paths
from .http import FetchError, HttpClient, NotFound, RateLimited

if TYPE_CHECKING:  # pragma: no cover - nur fuer die Typpruefung
    from collections.abc import Sequence

    from .models import Observation
    from .store import Store

#: Bildformate, die ein Browser ohne Weiteres darstellt. Alles andere wird nicht
#: abgelegt: was wir nicht anzeigen koennen, muessen wir auch nicht speichern.
_SUFFIXES = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".webp": ".webp", ".gif": ".gif"}

#: Ein Bild unter dieser Groesse ist praktisch immer ein Platzhalter — Shopware
#: liefert ein 1x1-Pixel, solange das echte Bild fehlt.
MIN_BYTES = 1024


def _suffix(url: str) -> str:
    match = re.search(r"(\.[A-Za-z]{3,4})(?:$|[?#])", urlsplit(url).path)
    return _SUFFIXES.get((match.group(1) if match else "").lower(), ".jpg")


def file_name(url: str) -> str:
    """``3f9a2b4c.jpg`` — der Name ist die Adresse, gehasht.

    **Keine Buch-Id im Namen**, und das ist der Punkt: dasselbe Bild ist eine
    Datei, gleichgueltig ob es an einem Vorschlag oder an einer ``book``-Zeile
    haengt. Ein Vorschlag hat keine Buch-Id (ADR 18) — waere sie Teil des
    Namens, wuerde dasselbe Cover ein zweites Mal geholt, sobald aus dem
    Vorschlag ein Buch wird.

    Der Hash sorgt ausserdem dafuer, dass ein gewechseltes Cover eine neue
    Datei bekommt statt die alte still zu ueberschreiben — und dass ein alter
    Verweis nie auf ein anderes Bild zeigt.

    Und weil der Name sich allein aus der Adresse ergibt, kann die Oberflaeche
    ihn ausrechnen und nachsehen, ob die Datei daliegt, statt ihn fuer jede
    Beobachtung zu speichern.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{digest}{_suffix(url)}"


#: Die Startmarken der JPEG-Segmente, die Breite und Hoehe tragen: SOF0 bis
#: SOF15 ohne DHT (C4), JPG (C8) und DAC (CC), die dieselben Nummern teilen.
_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def pixels(data: bytes) -> int | None:
    """Wie viele Bildpunkte ein Titelbild hat — gelesen aus dem Dateikopf.

    Kein Pillow: das Projekt braucht die Groesse an genau einer Stelle, und
    fuer eine Zahl eine Bildbibliothek mitzuschleppen waere teurer als die
    zwanzig Zeilen hier. Gelesen werden die beiden Formate, die die Quellen
    liefern, JPEG und PNG. Alles andere heisst ``None``, und ein Bild, dessen
    Groesse niemand kennt, verdraengt kein anderes.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big") * int.from_bytes(data[20:24], "big")
    if not data.startswith(b"\xff\xd8"):
        return None
    stelle = 2
    while stelle + 9 <= len(data):
        if data[stelle] != 0xFF:
            return None
        marke = data[stelle + 1]
        if marke == 0xFF:  # Fuellbyte vor einer Marke
            stelle += 1
            continue
        laenge = int.from_bytes(data[stelle + 2 : stelle + 4], "big")
        if marke in _SOF:
            hoehe = int.from_bytes(data[stelle + 5 : stelle + 7], "big")
            breite = int.from_bytes(data[stelle + 7 : stelle + 9], "big")
            return breite * hoehe
        stelle += 2 + laenge
    return None


class CoverStore:
    """Der Ordner mit den Titelbildern."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, name: str) -> Path:
        return self.directory / name

    def has(self, name: str) -> bool:
        return self.path(name).is_file()

    def fetch(self, client: HttpClient, url: str) -> str | None:
        """Das Bild holen, falls es noch nicht daliegt. Gibt den Dateinamen zurueck.

        Ein fehlgeschlagener Bilddownload ist kein Grund, einen Lauf scheitern zu
        lassen — ein Buch ohne Bild ist ein Buch mit einem Platzhalter. Nur eine
        Drosselung wird durchgereicht: da hat der Shop ausdruecklich Halt gesagt,
        und das gilt fuer alles Weitere mit (ADR 7).
        """
        name = file_name(url)
        if self.has(name):
            return name
        try:
            data = client.get_bytes(url)
        except RateLimited:
            raise
        except (FetchError, NotFound):
            return None
        if len(data) < MIN_BYTES:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path(name).write_bytes(data)
        return name


def _better(covers: CoverStore, name: str, *, than: str | None) -> bool:
    """Ob ``name`` das vorhandene Titelbild ersetzen soll (#10).

    Bisher gewann das erste Bild fuer immer. Kam zuerst die Kachel aus der
    Suche, sass ein Buch auf 200 Pixeln fest, obwohl die Detailseite 600
    lieferte — gemessen vier von 24 Buechern mit Bild, darunter *Dark Matter*
    mit 134x200. Jetzt gewinnt, was mehr Bildpunkte hat; bei Gleichstand bleibt
    das vorhandene, damit zwei gleich grosse Fassungen nicht hin und her
    wechseln. Gemessen wird am Bild, nicht an der Adresse: das ``_600x600`` im
    Namen ist eine Gewohnheit des Shops, keine Regel.
    """
    if not than or not covers.has(than):
        return True
    neu = pixels(covers.path(name).read_bytes())
    alt = pixels(covers.path(than).read_bytes())
    return neu is not None and (alt is None or neu > alt)


def fetch_for_books(store: Store, client: HttpClient, observations: Sequence[Observation]) -> None:
    """Titelbilder holen — einmal pro Buch, und nur für Bücher (Ticket 15).

    Eine Entdeckung bekommt keins: das wären dreihundert Anfragen pro Lauf statt
    einer Handvoll, und für ein Buch, zu dem die Leserin keine Beziehung hat,
    gibt es ohnehin keine Zeile, an der ein Bild hängen könnte (ADR 18).

    Ein Bild ist Beiwerk. Schlägt es fehl, läuft der Rest weiter — nur eine
    Drosselung bricht ab, denn dann hat der Shop Halt gesagt.

    Steht hier und nicht im Rundgang, weil beide Läufe es brauchen: der enge
    holte vorher keins, und ein Buch, das über "Jetzt prüfen" hereinkam, stand
    bis zum nächsten Rundgang ohne Bild da.
    """
    covers = CoverStore(paths.covers_dir())
    # Je *Adresse* einmal, nicht je Buch: jede Quelle bekommt ihre Chance.
    # Vorher zaehlte nur die erste Beobachtung eines Buchs — bei *Dark Matter*
    # kommt OverDrive mit einem kleinen Bild vor dem Shop mit 600x600, und das
    # grosse wurde nie gefragt (#10).
    done: set[tuple[int, str]] = set()
    for observation in observations:
        book_id, url = observation.book_id, observation.cover_url
        if not book_id or not url or (book_id, url) in done:
            continue
        done.add((book_id, url))
        # Frisch gelesen: ein Bild weiter oben im selben Lauf hat es vielleicht
        # schon ersetzt, und verglichen wird gegen das, was jetzt gilt.
        book = store.book(book_id)
        # Dieselbe Adresse ist dasselbe Bild: der Name ist ihr Hash. Nur eine
        # *andere* Adresse ist die Frage wert, ob sie das bessere Bild hat.
        if book is None or book.cover_file == file_name(url):
            continue
        try:
            name = covers.fetch(client, url)
        except RateLimited:
            print("Titelbilder: der Shop drosselt — Rest übersprungen", file=sys.stderr)
            return
        except Exception as exc:  # noqa: BLE001 - bewusst: ein Bild ist Beiwerk
            # Dieselbe Ueberlegung wie bei einer einzelnen Quelle in _collect:
            # was hier schiefgeht, darf hoechstens dieses eine Bild kosten. Ein
            # Lauf, der an einem Titelbild stirbt, waere die teuerste denkbare
            # Art, ein Platzhalterbild zu vermeiden.
            print(f"Titelbild {book_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if name and _better(covers, name, than=book.cover_file):
            store.set_cover(book_id, name)
