"""Baut die statischen Dateien der Oberfläche (ADR 20).

``uv run python -m ebook_watchlist.web.build``

Alles unter ``web/static/`` ist Bauergebnis und liegt nicht im Repository:
eingecheckte Bauartefakte laufen still auseinander, sobald jemand die Quelle
ändert und den Build vergisst.

Die Bibliotheken werden **einmal geholt und dann lokal ausgeliefert**, nicht bei
jedem Seitenaufruf von einem CDN. Sonst erführe ein Dritter bei jedem Aufruf,
dass diese Seite geöffnet wurde — dieselbe Überlegung wie bei den Covern. Als
Nebenwirkung funktioniert die Oberfläche in einem Netz ohne Außenverbindung.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

WEB = Path(__file__).parent
ASSETS = WEB / "assets"
STATIC = WEB / "static"
VENDOR = STATIC / "vendor"

#: Feste Versionen, keine "latest"-URL: ein Build muss zweimal dasselbe
#: ergeben, und eine stillschweigend gewechselte Bibliothek ist genau die Art
#: Änderung, die niemand bemerkt, bis die Oberfläche kaputt ist.
ALPINE_VERSION = "3.17.1"
HTMX_VERSION = "2.0.10"


@dataclass(frozen=True, slots=True)
class Library:
    name: str
    url: str
    #: Erwarteter SHA-256. Beim ersten Holen leer lassen; der Build schreibt
    #: ihn dann in die Ausgabe und er wird hier eingetragen.
    sha256: str = ""

    @property
    def target(self) -> Path:
        return VENDOR / self.name


#: Fertige Dateien, die nur an ihren Platz muessen.
#:
#: Zwei Zeichen, nicht eins: der Buchfink traegt die Kopfzeile bei 40 px, das
#: gezeichnete Zeichen den Browser-Tab bei 16 — dort zerfaellt der Vogel zu
#: einem Kruemel, waehrend Rechteck und Abzeichen noch unterscheidbar sind.
ICONS = (
    "favicon.svg",
    "buchfink.png",
    "buchfink-tag.png",
    # Das Titelbild des Leerzustands, 197 KB: es steht auf genau einer Seite,
    # und zwar auf der, die eine Leserin einmal sieht und danach nie wieder.
    "hero-mit-titel.jpg",
)

LIBRARIES = (
    Library(
        name="alpine.min.js",
        url=f"https://cdn.jsdelivr.net/npm/alpinejs@{ALPINE_VERSION}/dist/cdn.min.js",
        sha256="b30997fc126d808b1a9b20ab3f504ded88df957818c02d6249bba3ec114eb0ec",
    ),
    Library(
        name="htmx.min.js",
        url=f"https://cdn.jsdelivr.net/npm/htmx.org@{HTMX_VERSION}/dist/htmx.min.js",
        sha256="71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de",
    ),
)


def fetch(library: Library) -> str:
    response = requests.get(library.url, timeout=60)
    response.raise_for_status()
    digest = hashlib.sha256(response.content).hexdigest()
    if library.sha256 and digest != library.sha256:
        raise SystemExit(
            f"{library.name}: erwartet {library.sha256}, bekommen {digest} — "
            "die Datei hinter der URL hat sich geändert"
        )
    library.target.parent.mkdir(parents=True, exist_ok=True)
    library.target.write_bytes(response.content)
    return digest


def build_css() -> None:
    """Tailwind über die Standalone-Binärdatei, die ``pytailwindcss`` mitbringt."""
    binary = shutil.which("tailwindcss")
    if binary is None:
        raise SystemExit(
            "tailwindcss nicht gefunden — 'uv sync' installiert pytailwindcss, "
            "'uv run tailwindcss_install' holt die Binärdatei"
        )
    STATIC.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603 - fester Befehl, keine Nutzereingabe
        [binary, "-i", str(ASSETS / "app.css"), "-o", str(STATIC / "app.css"), "--minify"],
        check=True,
    )


def copy_icons() -> None:
    """Was schon fertig ist, wird nur kopiert.

    Es liegt trotzdem unter ``assets/``: ``static/`` ist Bauergebnis und nicht
    im Repository, eine Datei dort waere also beim naechsten Klon weg.
    """
    STATIC.mkdir(parents=True, exist_ok=True)
    for name in ICONS:
        shutil.copyfile(ASSETS / name, STATIC / name)


def main() -> int:
    build_css()
    copy_icons()
    for library in LIBRARIES:
        digest = fetch(library)
        marker = "" if library.sha256 else "  (sha256 in build.py eintragen)"
        print(f"{library.name}  {digest}{marker}", file=sys.stderr)
    print(f"fertig -> {STATIC}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
