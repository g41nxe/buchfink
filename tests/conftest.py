from __future__ import annotations

import functools
import shutil
import socket
import textwrap
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

SETTINGS_YAML = """
slug: test
name: Testprofil
sources:
  fake:
    fixture: fake-source.yaml
"""

# Leer, aber vorhanden: so sieht eine frische Installation aus. Wer
# Interessen braucht, schreibt sie in seinem Test hinein (#36).
SEED_YAML = """
reference_authors: []
"""

WATCHLIST_YAML = """
- title: Die sieben Schwestern
  author: Lucinda Riley
"""

FAKE_SOURCE_YAML = """
- id: fake-1
  title: Die sieben Schwestern
  author: Lucinda Riley
  availability: unavailable
  reservation_count: 3
- id: fake-2
  title: Der Schwarm
  author: Frank Schätzing
  price_cents: 1299
"""


# --- Schema einmal bauen, dann kopieren (Ticket 18) -------------------------
#
# ``create_all`` kostet 0,26 s — elf CREATE TABLE, jedes mit einem Schreibvorgang
# auf die Platte. Bei über hundert Testaufbauten sind das dreißig Sekunden für
# ein Schema, das sich zwischen zwei Tests nie unterscheidet. Eine fertige Datei
# zu kopieren kostet 0,009 s.


@pytest.fixture(scope="session")
def schema_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Eine leere, fertig migrierte Datenbank — einmal je Testlauf."""
    from ebook_watchlist.store import Store

    path = tmp_path_factory.mktemp("schema") / "template.db"
    Store(path)
    return path


@pytest.fixture
def store(tmp_path: Path, schema_template: Path):
    """Ein frischer Store, aus der Vorlage kopiert statt neu gebaut."""
    from ebook_watchlist.store import Store

    target = tmp_path / "snapshots.db"
    shutil.copy(schema_template, target)
    return Store(target)


# --- Fixtures einmal lesen und einmal parsen (Ticket 18) --------------------
#
# Die beam-Seiten sind 200 bis 700 KB. Ein lxml-Durchlauf ueber die
# Trefferseite kostet 0,70 s, und einunddreissig Tests holen sie sich. Die
# Dateien aendern sich nicht, also gehoert das einmal getan.


@functools.cache
def _read(area: str, name: str) -> str:
    return (FIXTURES / area / name).read_text(encoding="utf-8")


@functools.cache
def _tiles(name: str) -> tuple:
    from ebook_watchlist.sources.beam import parse

    return tuple(parse.parse_tiles(_read("beam", name)))


def beam_fixture(name: str) -> str:
    """Der rohe HTML-Text einer beam-Fixture."""
    return _read("beam", name)


def onleihe_fixture(name: str) -> str:
    return _read("onleihe", name)


def overdrive_fixture(name: str) -> str:
    """Ganze Antworten von Thunder, aufgezeichnet am 2026-09-11. Neu aufnehmen
    statt von Hand nachbessern, wenn sich die Schnittstelle aendert (ADR 14)."""
    return _read("overdrive", name)


@functools.cache
def beam_detail(name: str):
    """Die geparste beam-Detailseite. 720 KB, und mehrere Tests brauchen sie."""
    from ebook_watchlist.sources.beam import parse

    return parse.parse_detail(_read("beam", name))


@functools.cache
def onleihe_detail(name: str):
    from ebook_watchlist.sources.onleihe import parse

    return parse.parse_detail(_read("onleihe", name))


def beam_tiles(name: str) -> list:
    """Die geparsten Kacheln — als frische Liste, damit ein Test sie umsortieren
    darf, ohne die naechsten zu stoeren. Die Kacheln selbst sind unveraenderlich.
    """
    return list(_tiles(name))


@pytest.fixture
def unseeded_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Die YAML-Dateien, aber noch kein Import — eine frische Installation."""
    directory = tmp_path / "data"
    directory.mkdir()
    monkeypatch.setenv("EBW_DATA_DIR", str(directory))
    for name, body in (
        ("settings.yaml", SETTINGS_YAML),
        ("seed.yaml", SEED_YAML),
        ("watchlist.yaml", WATCHLIST_YAML),
        ("fake-source.yaml", FAKE_SOURCE_YAML),
    ):
        (directory / name).write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return directory


@pytest.fixture
def data_dir(unseeded_data_dir: Path, schema_template: Path) -> Path:
    """Wie oben, plus der einmalige Import.

    Seit Ticket 05 liest der Lauf seine Konfiguration aus der Datenbank; YAML
    ist Saatgut. Eine Installation ohne Import ist damit ein eigener Zustand,
    und den prüft ``unseeded_data_dir``.

    Das Schema liegt vorher schon da, damit der Import nicht noch einmal elf
    Tabellen anlegen muss.
    """
    from ebook_watchlist.run import main

    shutil.copy(schema_template, unseeded_data_dir / "snapshots.db")
    main(["seed"])
    return unseeded_data_dir


def _vocabulary_present() -> bool:
    from ebook_watchlist.portrait import PATTERNS_PATH, VOCABULARY_PATH

    return VOCABULARY_PATH.exists() and PATTERNS_PATH.exists()


#: Das Vokabular der Merkmale und Erzählmuster ist nicht in Git (#59). Wo es
#: fehlt — in einem frischen Klon —, werden die Tests übersprungen, die es
#: brauchen, statt zu scheitern.
needs_vocabulary = pytest.mark.skipif(
    not _vocabulary_present(),
    reason="vocabulary/ fehlt: das Vokabular liegt nicht in Git (#59)",
)


#: Welche Merkmale ein Steckbrief tragen muss, damit das Urteil aus
#: :func:`judging_profile` auf genau diese Sterne kommt (#48). Drei gemochte
#: Erzählmuster zählen je 0,3; die Facette "gezeichnete Figur · hart" 0,8.
STAR_TERMS = {
    1: ("leisurely",),
    2: ("quest",),
    3: ("quest", "adventure"),
    4: ("quest", "adventure", "pursuit"),
    5: ("brooding", "gritty", "quest"),
}


def judging_profile():
    """Ein Leseprofil, an dem sich Sterne von 1 bis 5 genau steuern lassen."""
    from ebook_watchlist.facets import Facet, Liked, ReadingProfile

    return ReadingProfile(
        facets=(Facet(("brooding", "harsh"), ("Leichenblässe", "Sharp Objects")),),
        counterweights=(),
        liked=(Liked("quest"), Liked("adventure"), Liked("pursuit")),
    )


def give_profile(db, slug: str = "test", profile=None) -> None:
    """Der Leserin ein Leseprofil in die Datenbank legen — ohne es urteilt niemand."""
    from datetime import datetime

    db.put_reading_profile(
        slug, profile or judging_profile(), cause="Test", now=datetime(2026, 9, 4, 20, 0)
    )


def describe(db, subject: str, stars: int, pitch: str | None = "Ein Buch.") -> None:
    """Zu einem Fund einen Steckbrief legen, der mit :func:`judging_profile` auf
    diese Sterne kommt."""
    from datetime import datetime

    from ebook_watchlist.portrait import Portrait, Trait, fingerprint, load_vocabulary

    db.put_portrait(
        subject,
        Portrait(
            known=True,
            fingerprint=fingerprint(load_vocabulary()),
            pitch=pitch,
            traits=tuple(Trait(t, f"Satz zu {t}", "wissen") for t in STAR_TERMS[stars]),
        ),
        now=datetime(2026, 9, 4, 20, 0),
    )


@pytest.fixture(autouse=True)
def kein_netz(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kein Test greift nach draußen — außer den ausdrücklich als ``live``
    markierten.

    Anlass ist Ticket 51: seit die Oberfläche einen engen Lauf in einem Faden
    anstoßen kann, würde ein Test, der einen Eintrag aufnimmt oder bestätigt,
    **wirklich** beim Shop anfragen. Das fällt nicht auf — der Faden ist
    ``daemon``, der Test ist längst grün —, und es steht der stehenden Vorgabe
    entgegen, sparsam mit den echten Quellen zu sein.

    Geblockt wird an der Steckdose und nicht an einer Bibliothek: was auch
    immer jemand künftig zum Holen benutzt, kommt hier vorbei. Nur die eigene
    Maschine bleibt offen — `pytest-xdist` redet über Sockets mit seinen
    Arbeitern, und der Testklient von FastAPI tut es auch.
    """
    if request.node.get_closest_marker("live"):
        return

    echt = socket.socket.connect

    def nur_hierhin(self: socket.socket, adresse: object, *rest: object) -> object:
        host = adresse[0] if isinstance(adresse, tuple) else ""
        if host in ("127.0.0.1", "::1", "localhost", ""):
            return echt(self, adresse, *rest)
        raise RuntimeError(
            f"Dieser Test wollte zu {host!r}. Entweder fehlt eine Attrappe, "
            "oder er gehoert mit @pytest.mark.live markiert."
        )

    monkeypatch.setattr(socket.socket, "connect", nur_hierhin)


@pytest.fixture(autouse=True)
def kein_bewerter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kein Test ruft das Modell.

    Die Socket-Sperre oben reicht dafuer nicht: ohne API-Schluessel laeuft der
    Bewerter ueber die angemeldete Claude-Code-Installation, also ueber einen
    **Unterprozess** — und der geht an `socket.connect` vorbei. Aufgefallen ist
    es, als das Hinzufuegen eines Watchlist-Titels ein Urteil anstiess (#38):
    der Testlauf dauerte danach zwanzig Minuten statt siebzig Sekunden, und
    jede dieser Minuten war ein echter Aufruf.

    Voreingestellt gibt es also keinen Bewerter — derselbe Zustand wie auf
    einem Rechner ohne Schluessel, und er ist ausdruecklich erlaubt. Wer das
    Urteilen pruefen will, setzt seine eigene Attrappe; sie kommt nach dieser
    Fixture und gewinnt.

    Abgeschaltet wird in **jedem** Modul, das ``build_rater`` importiert hat,
    nicht in einer festen Liste: die Erstaufnahme (#47) kam als drittes Modul
    dazu, stand nicht in der Liste, und ihr erster Test rief das Modell
    wirklich.
    """
    import sys

    from ebook_watchlist import rating, run  # noqa: F401 - laden, damit sie erfasst werden
    from ebook_watchlist.web import book, intake  # noqa: F401

    echt = rating.build_rater
    for name, modul in list(sys.modules.items()):
        if name.startswith("ebook_watchlist") and getattr(modul, "build_rater", None) is echt:
            monkeypatch.setattr(modul, "build_rater", lambda model=None: None)


@pytest.fixture(autouse=True)
def keine_belege_von_draussen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Der Knopf "neu beurteilen" holt Detailseite und Leseprobe (#17). In
    Tests ohne Quellen — wer sie prüfen will, setzt seine eigenen ein."""
    from ebook_watchlist.web import book

    monkeypatch.setattr(book, "evidence_sources", lambda settings, store: [])


@pytest.fixture(autouse=True)
def kein_enger_lauf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Der enge Lauf aus Ticket 51 tut in Tests nichts.

    Er laeuft in einem ``daemon``-Faden, und der ueberlebt den Test, der ihn
    angestossen hat. Danach greift er auf ``paths.db_path()`` zu — also auf
    das Datenverzeichnis des **naechsten** Tests — und nimmt unterwegs die
    Lauf-Sperre. Genau das hat einmal einen Test ueber den Lauf-Knopf
    umgeworfen, der damit nichts zu tun hatte.

    Wer den engen Lauf pruefen will, setzt hier seine eigene Attrappe ein.
    """
    from ebook_watchlist.single import Report
    from ebook_watchlist.web import recheck

    monkeypatch.setattr(recheck, "check_one", lambda book_id: Report())
