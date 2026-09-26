"""Die Leseprobe — der Anfang des Buchs, für den `Portrayer` (#17, #76).

Seit #76 nur noch als zweite Stufe: kommt ein Buch trotz Klappentext als
„unbekannt" zurück, wird es genau einmal mit dem Anfang der Probe gefragt.

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
import sys
import zipfile
from collections.abc import Callable
from typing import Protocol

from bs4 import BeautifulSoup

from .http import FetchError, NotFound, RateLimited

#: So viele Wörter bekommt der `Portrayer` vom Anfang des Buchs: rund 5 000
#: Zeichen, gut 1 000 Tokens zu den rund 6 500 der Anweisung (#76). Genug für
#: Stimme und Ton des Einstiegs; mehr hieß früher 2 500 Wörter und machte die
#: Anfrage um die Hälfte teurer, für ein Buch, das nur als zweite Stufe fragt.
SAMPLE_WORDS = 800

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


def fetcher(client: _Client) -> Callable[[str], str | None]:
    """Ein Holer für den `Portrayer` (#76): Adresse hinein, Anfang heraus.

    Drosselt die Quelle (429), holt er nichts mehr, und der Lauf geht weiter:
    die Probe ist eine zweite Stufe, kein Grund, den Stapel anzuhalten (ADR 7).
    """
    stopped = False

    def fetch(url: str) -> str | None:
        nonlocal stopped
        if stopped:
            return None
        try:
            return fetch_opening(client, url)
        except RateLimited:
            stopped = True
            print("Leseproben: die Quelle drosselt — Rest übersprungen", file=sys.stderr)
            return None

    return fetch


def opening(epub: bytes) -> str | None:
    """Die ersten :data:`SAMPLE_WORDS` Wörter Erzähltext, oder ``None``."""
    try:
        with zipfile.ZipFile(io.BytesIO(epub)) as archive:
            words: list[str] = []
            in_story = False
            for page in _reading_order(archive):
                text = _page_text(archive, page)
                if text is None:
                    continue
                if not in_story:
                    # Vorne steht, was nicht erzählt; ab der ersten Seite mit
                    # Erzähltext zählt alles, auch ein kurzes Kapitel.
                    if len(text.split()) < MIN_PROSE_WORDS or _NOT_PROSE.match(text):
                        continue
                    in_story = True
                words += text.split()
                if len(words) >= SAMPLE_WORDS:
                    break
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        return None
    return " ".join(words[:SAMPLE_WORDS]) or None


def _reading_order(archive: zipfile.ZipFile) -> list[str]:
    """Die Seiten in Lesereihenfolge: ``container.xml`` → OPF → ``spine``.

    Die Reihenfolge im Archiv ist zufällig; die Probe von Fischer hat "Über
    John Scalzi" hinter den Kapiteln, ein anderer Verlag davor.
    """
    container = archive.read("META-INF/container.xml").decode("utf-8", "replace")
    hit = re.search(r'full-path="([^"]+)"', container)
    if hit is None:
        return []
    opf_path = hit.group(1)
    opf = archive.read(opf_path).decode("utf-8", "replace")
    base_dir = posixpath.dirname(opf_path)

    manifest: dict[str, str] = {}
    for tag in re.findall(r"<(?:\w+:)?item\b[^>]*>", opf):
        attribute = dict(_ATTR.findall(tag))
        if "id" in attribute and "href" in attribute:
            manifest[attribute["id"]] = attribute["href"]
    order = []
    for tag in re.findall(r"<(?:\w+:)?itemref\b[^>]*>", opf):
        idref = dict(_ATTR.findall(tag)).get("idref")
        if idref in manifest:
            order.append(posixpath.normpath(posixpath.join(base_dir, manifest[idref])))
    return order


def _page_text(archive: zipfile.ZipFile, path: str) -> str | None:
    try:
        info = archive.getinfo(path)
    except KeyError:
        return None
    if info.file_size > _MAX_PAGE_BYTES:
        return None
    page = BeautifulSoup(archive.read(info), "html.parser")
    for gone in page(["head", "script", "style"]):
        gone.decompose()
    return " ".join(page.get_text(" ").split())
