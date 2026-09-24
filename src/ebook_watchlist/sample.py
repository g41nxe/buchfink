"""Die Leseprobe — der Anfang des Buchs, für den `Portrayer` (#17).

Der Klappentext ist Werbung: er verspricht Tempo und eine kaputte Hauptfigur,
ob das Buch sie hat oder nicht. Die Achsen des Leseprofils fragen aber, *wie*
ein Buch erzählt, und das zeigt nur der Text selbst. Shop und Bibliothek
verlinken auf der Detailseite, die der Lauf ohnehin holt, eine Probe als EPUB:
gemessen eine Datei von einem Megabyte, rund fünfzig Seiten Text.

Davon bekommt der `Portrayer` den Anfang — genug für Stimme, Figur und das Tempo
des Einstiegs, und nicht so viel, dass jedes Buch den Prompt verzehnfacht.

Kein EPUB-Paket: eine EPUB-Datei ist ein Zip mit XHTML-Seiten, und die
Lesereihenfolge steht in einer einzigen Liste. Das sind ein paar Zeilen
Standardbibliothek, keine Abhängigkeit.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from typing import Protocol

from bs4 import BeautifulSoup

from .http import FetchError, NotFound

#: So viele Wörter bekommt der `Portrayer` vom Anfang des Buchs. Rund zehn
#: Seiten: genug, um zu sehen, ob der Einstieg zieht und wer da erzählt.
SAMPLE_WORDS = 2500

#: Eine Seite mit weniger Wörtern ist Titelei, Impressum oder Widmung — noch
#: nicht das Buch. Gemessen an einer Probe von Fischer: Titelei 18, Impressum
#: 49, Inhalt 82 Wörter, das erste Kapitel 4330.
MIN_PROSE_WORDS = 200

#: Seiten, die auch lang sein koennen und trotzdem nicht erzählen.
_NOT_PROSE = re.compile(r"^(Über (das|dieses) Buch|Über (den|die) Autor|Inhalt\b|Impressum)")

#: Keine Seite einer Probe ist so groß; eine, die es ist, wird übergangen,
#: statt entpackt zu werden (ein Zip kann klein sein und riesig entpacken).
_MAX_PAGE_BYTES = 2_000_000

_ATTR = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')


class _Client(Protocol):
    def get_bytes(self, url: str) -> bytes: ...


def fetch_opening(client: _Client, url: str) -> str | None:
    """Die Probe holen und ihren Anfang lesen — oder ``None``.

    Eine fehlende oder kaputte Probe kostet das Buch die Probe, nicht das
    Urteil. Nur eine Drosselung geht durch: dann hat die Quelle Halt gesagt,
    und das gilt für alles Weitere (ADR 7).
    """
    try:
        data = client.get_bytes(url)
    except (FetchError, NotFound):
        return None
    return opening(data)


def opening(epub: bytes) -> str | None:
    """Die ersten :data:`SAMPLE_WORDS` Wörter Erzähltext, oder ``None``."""
    try:
        with zipfile.ZipFile(io.BytesIO(epub)) as archiv:
            woerter: list[str] = []
            erzaehlt = False
            for seite in _reading_order(archiv):
                text = _page_text(archiv, seite)
                if text is None:
                    continue
                if not erzaehlt:
                    # Vorne steht, was nicht erzählt; ab der ersten Seite mit
                    # Erzähltext zählt alles, auch ein kurzes Kapitel.
                    if len(text.split()) < MIN_PROSE_WORDS or _NOT_PROSE.match(text):
                        continue
                    erzaehlt = True
                woerter += text.split()
                if len(woerter) >= SAMPLE_WORDS:
                    break
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        return None
    return " ".join(woerter[:SAMPLE_WORDS]) or None


def _reading_order(archiv: zipfile.ZipFile) -> list[str]:
    """Die Seiten in Lesereihenfolge: ``container.xml`` → OPF → ``spine``.

    Die Reihenfolge im Archiv ist zufällig; die Probe von Fischer hat "Über
    John Scalzi" hinter den Kapiteln, ein anderer Verlag davor.
    """
    container = archiv.read("META-INF/container.xml").decode("utf-8", "replace")
    treffer = re.search(r'full-path="([^"]+)"', container)
    if treffer is None:
        return []
    opf_pfad = treffer.group(1)
    opf = archiv.read(opf_pfad).decode("utf-8", "replace")
    basis = posixpath.dirname(opf_pfad)

    manifest: dict[str, str] = {}
    for tag in re.findall(r"<(?:\w+:)?item\b[^>]*>", opf):
        attribute = dict(_ATTR.findall(tag))
        if "id" in attribute and "href" in attribute:
            manifest[attribute["id"]] = attribute["href"]
    reihenfolge = []
    for tag in re.findall(r"<(?:\w+:)?itemref\b[^>]*>", opf):
        idref = dict(_ATTR.findall(tag)).get("idref")
        if idref in manifest:
            reihenfolge.append(posixpath.normpath(posixpath.join(basis, manifest[idref])))
    return reihenfolge


def _page_text(archiv: zipfile.ZipFile, pfad: str) -> str | None:
    try:
        info = archiv.getinfo(pfad)
    except KeyError:
        return None
    if info.file_size > _MAX_PAGE_BYTES:
        return None
    seite = BeautifulSoup(archiv.read(info), "html.parser")
    for weg in seite(["head", "script", "style"]):
        weg.decompose()
    return " ".join(seite.get_text(" ").split())
