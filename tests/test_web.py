"""The Dashboard, driven through FastAPI's test client — no live server."""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.run import main as run_main
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_an_untouched_installation_says_so_instead_of_looking_broken(
    client: TestClient,
) -> None:
    response = client.get("/overview")
    assert response.status_code == 200
    assert "Noch kein Lauf verzeichnet" in response.text


def test_the_run_journal_is_shown(client: TestClient) -> None:
    run_main([])
    run_main([])

    body = client.get("/overview").text

    assert body.count("<tr") >= 3  # header plus two runs
    assert "cli" in body
    assert "ok" in body


def test_a_failing_source_is_named_on_the_dashboard(
    client: TestClient, data_dir: Path
) -> None:
    (data_dir / "fake-source.yaml").write_text("not: a list\n", encoding="utf-8")
    run_main([])

    body = client.get("/overview").text

    assert "schiefgegangen" in body
    assert "must be a list of items" in body


def test_digests_are_listed_and_servable(client: TestClient, data_dir: Path) -> None:
    run_main([])
    fixture = data_dir / "fake-source.yaml"
    fixture.write_text(
        fixture.read_text(encoding="utf-8").replace("price_cents: 1299", "price_cents: 499"),
        encoding="utf-8",
    )
    run_main([])

    name = f"digest-{datetime.now():%Y-%m-%d}.html"
    assert name in client.get("/overview").text

    digest = client.get(f"/digest/{name}")
    assert digest.status_code == 200
    assert "Der Schwarm" in digest.text


def test_the_digest_route_is_not_a_file_browser(client: TestClient, data_dir: Path) -> None:
    """The data directory holds the config and the database; only digests are public."""
    (data_dir / "digests").mkdir(exist_ok=True)

    for attempt in [
        "../profile.yaml",
        "..%2Fprofile.yaml",
        "digest-2026-09-04.html/../../snapshots.db",
        "snapshots.db",
        "digest-evil.html",
    ]:
        response = client.get(f"/digest/{attempt}")
        assert response.status_code == 404, attempt


def test_a_missing_digest_is_a_404_not_a_crash(client: TestClient) -> None:
    assert client.get("/digest/digest-2001-01-01.html").status_code == 404


def test_broken_configuration_is_reported_rather_than_a_stack_trace(
    client: TestClient, data_dir: Path
) -> None:
    (data_dir / "settings.yaml").unlink()

    response = client.get("/overview")

    assert response.status_code == 500
    assert "lässt sich nicht laden" in response.text
    assert "Traceback" not in response.text


def test_the_web_process_never_takes_the_run_lock(client: TestClient) -> None:
    """Killing the dashboard must never be able to strand a Run."""
    from filelock import FileLock

    held = FileLock(str(paths.lock_path()), timeout=0)
    held.acquire()
    try:
        assert client.get("/overview").status_code == 200
    finally:
        held.release()


# --- Quellen-Zustand (Ticket 03) -------------------------------------------


def test_each_source_gets_a_line_of_its_own(client: TestClient) -> None:
    """Bisher musste die Seite Gesundheit aus Laufergebnissen erraten."""
    run_main([])

    body = client.get("/overview").text

    assert "Quellen" in body
    assert "zuletzt geprüft" in body


def test_a_paused_source_says_so_rather_than_vanishing(
    client: TestClient, data_dir: Path
) -> None:
    run_main([])
    store = Store(data_dir / "snapshots.db")
    name = store.sources()[0].name
    store.set_enabled(name, False, now=datetime.now())

    body = client.get("/overview").text

    assert "pausiert" in body
    # Der interne Name steht bewusst nicht mehr da — die Leserin liest die Art
    # der Quelle (Ticket 14). Dass es *diese* ist, sagt der Zustand.
    assert name not in body


def test_a_source_broken_for_days_is_marked_as_such(
    client: TestClient, data_dir: Path
) -> None:
    run_main([])
    store = Store(data_dir / "snapshots.db")
    name = store.sources()[0].name
    for _ in range(3):
        store.record_probe(name, ok=False, error="kaputt", now=datetime.now())

    body = client.get("/overview").text

    assert "seit 3 Prüfungen" in body


def test_a_fresh_checkout_can_build_its_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Das Henne-Ei, das ein frischer Klon nicht auflösen konnte.

    ``app.py`` baut die Anwendung beim Import und verlangt dabei das gebaute
    Stylesheet. Solange ``ebook_watchlist.web`` das eifrig importierte, führte
    der Import des Bauwerkzeugs — das im selben Paket liegt — zuerst dorthin,
    und die Fehlermeldung nannte einen Befehl, der selbst nicht laufen konnte.
    """
    import importlib

    module = importlib.import_module("ebook_watchlist.web.build")

    assert hasattr(module, "main")


def test_a_broken_configuration_is_a_page_not_a_traceback_on_post(
    client: TestClient, data_dir: Path
) -> None:
    """Die Ansichtsseiten fingen das je einzeln ab, die Formulare gar nicht."""
    (data_dir / "settings.yaml").write_text("nicht: [eine, abbildung\n", encoding="utf-8")

    response = client.post("/watchlist/add", data={"title": "Irgendwas"})

    assert response.status_code == 500
    assert "settings.yaml" in response.text


# --- was die Gestaltung behauptet, und was pruefbar davon ist ---------------
#
# Abstaende und Hoehen prueft hier niemand: dafuer braeuchte es einen Browser,
# und was er messen wuerde, aendert sich mit jedem Entwurf. Pruefbar ist, was
# eine Aussage ist — welche Woerter dastehen und welches Element sich als das
# aktuelle ausgibt.


@pytest.mark.parametrize(
    ("pfad", "name"),
    [("/", "Home"), ("/watchlist", "Watchlist"), ("/suggestions", "Vorschläge"),
     ("/profile", "Profil"), ("/overview", "Übersicht")],
)
def test_the_navigation_marks_the_page_you_are_on(
    client: TestClient, pfad: str, name: str
) -> None:
    """Vier gleich aussehende Links sagten auch auf der offenen Seite nichts."""
    body = client.get(pfad).text

    assert body.count('aria-current="page"') == 1
    marker = body.index('aria-current="page"')
    assert name in body[marker : marker + 400]


@pytest.mark.parametrize("pfad", ["/", "/watchlist", "/suggestions", "/profile"])
def test_the_overview_is_reachable_from_every_page(client: TestClient, pfad: str) -> None:
    """Die Uebersicht hing bis #25 an zwei Verweisen der Startseite: wer auf der
    Watchlist stand und nachsehen wollte, wann zuletzt geprueft wurde, musste
    erst zurueck."""
    assert 'href="/overview"' in client.get(pfad).text


def test_a_digest_is_offered_as_a_report_not_as_a_file_name(
    client: TestClient, data_dir: Path
) -> None:
    """`Digest` ist das Codewort, "Tagesbericht" das Wort dafuer (ADR 22).

    Der Dateiname bleibt in der Adresse — er ist der Schluessel —, aber er ist
    nicht mehr das, was jemand anzuklicken bekommt.
    """
    digests = paths.digests_dir()
    digests.mkdir(parents=True, exist_ok=True)
    (digests / "digest-2026-09-07.html").write_text("<p>x</p>", encoding="utf-8")

    body = client.get("/overview").text

    assert ">Tagesbericht</a>" in body
    assert ">digest-2026-09-07.html</a>" not in body
    assert 'href="/digest/digest-2026-09-07.html"' in body


def test_a_digest_is_dated_by_the_day_it_reports_on(
    client: TestClient, data_dir: Path
) -> None:
    """Danebengestanden hatte die Dateizeit.

    Zwei Berichte verschiedener Tage, am selben Abend geschrieben, trugen
    damit dieselbe Zahl — zu unterscheiden waren sie nur am Dateinamen.
    """
    digests = paths.digests_dir()
    digests.mkdir(parents=True, exist_ok=True)
    for name in ("digest-2026-09-07.html", "digest-2026-09-08.html"):
        (digests / name).write_text("<p>x</p>", encoding="utf-8")

    body = client.get("/overview").text

    assert "07.09.2026" in body
    assert "08.09.2026" in body


def test_a_moment_is_written_the_same_way_everywhere(
    client: TestClient, data_dir: Path
) -> None:
    """Ein Format fuer Zeitpunkte, ohne Sekunden.

    Die Uebersicht zeigte drei: den Laufbeginn mit Jahr und Sekunden, die
    Lauf-Liste ohne beides, die Quellen wieder anders.
    """
    run_main([])

    body = client.get("/overview").text

    assert "seit " in body

    # Das Jahr gehoert ausdruecklich ins Muster, obwohl es verschwinden soll:
    # ohne es faende der Ausdruck genau die Schreibweise nicht, gegen die
    # dieser Test steht, und bliebe gruen, wenn sie zurueckkaeme. Nachgestellt.
    momente = re.findall(r"\d{2}\.\d{2}\.\d{0,4} \d{2}:\d{2}(?::\d{2})?", body)
    assert momente, "kein Zeitpunkt auf der Seite gefunden"

    mit_sekunden = [m for m in momente if m.count(":") > 1]
    mit_jahr = [m for m in momente if re.match(r"\d{2}\.\d{2}\.\d{4}", m)]
    assert not mit_sekunden, f"Sekunden in {mit_sekunden}"
    assert not mit_jahr, f"Jahr in einem Zeitpunkt: {mit_jahr}"


def test_the_interface_still_starts_without_a_usable_console(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der Autostart laeuft unter ``pythonw.exe``, damit kein Konsolenfenster
    stehenbleibt — und hat dann keine gueltige Ausgabe.

    Vorher genuegten die zwei Startzeilen der Oberflaeche, um den Prozess mit
    Rueckgabewert 1 zu beenden, ohne eine Spur: die Fehlermeldung nahm
    denselben kaputten Weg. Gemessen an der Aufgabenplanung, nicht vermutet.
    """
    import importlib

    class OhneHandle:
        """Was ``pythonw.exe`` ohne Konsole liefert: da, aber unbeschreibbar."""

        def write(self, _text: str) -> int:
            raise OSError("kein gueltiges Handle")

        def flush(self) -> None:
            raise OSError("kein gueltiges Handle")

    monkeypatch.setattr(sys, "stderr", OhneHandle())
    monkeypatch.setattr(sys, "stdout", OhneHandle())

    importlib.import_module("ebook_watchlist.web.__main__")._sichere_ausgabe()
    print("eine Zeile, die sonst niemand liest", file=sys.stderr)

    assert "eine Zeile" in (data_dir / "web.log").read_text(encoding="utf-8")


def test_the_cwa_link_appears_only_when_an_address_is_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein Verweis auf eine fremde Anwendung, die es nur hier gibt.

    Fest verdrahtet waere `books.localhost` fuer jeden anderen ein toter Link
    (ADR 12). Die Adresse steht deshalb in der Umgebung, und ohne sie bleibt
    die Kopfzeile, wie sie war.
    """
    from ebook_watchlist.web.app import TEMPLATES

    ohne = client.get("/watchlist").text
    assert "CWA" not in ohne

    monkeypatch.setitem(TEMPLATES.env.globals, "cwa_url", "http://books.example/")
    mit = client.get("/watchlist").text

    assert 'href="http://books.example/"' in mit
    # Eine fremde Anwendung oeffnet in einem neuen Tab, und `noopener` gehoert
    # dazu, damit sie kein `window.opener` auf Buchfink bekommt.
    assert 'target="_blank" rel="noopener"' in mit


# --- Hell und Dunkel (#19) ---------------------------------------------------


@pytest.mark.parametrize("pfad", ["/", "/watchlist", "/suggestions", "/profile", "/overview"])
def test_every_page_carries_the_colour_switch(client: TestClient, pfad: str) -> None:
    """Der Schalter steht im Fussbereich, und den traegt `base.html` — also
    jede Seite. Eine Einstellung, die nur an einer Stelle erreichbar ist, muss
    man suchen."""
    body = client.get(pfad).text

    assert "<footer" in body
    for wort in ("System", "Hell", "Dunkel"):
        assert f">{wort}</button>" in body


def test_the_colour_is_set_before_the_first_paint(client: TestClient) -> None:
    """Sonst blitzt die falsche Farbe auf.

    Das Skript steht im Kopf und ohne `defer` — die beiden Bibliotheken laden
    mit `defer` und sind dafuer zu spaet. Wer das aendert, sieht beim naechsten
    Aufruf eine weisse Seite, bevor die dunkle kommt.
    """
    kopf = client.get("/").text.split("</head>")[0]
    # Der eine Skriptblock ohne Quelle: die beiden Bibliotheken stehen als
    # `<script src=... defer>` daneben.
    inline = kopf[kopf.index("<script>") : kopf.index("</script>", kopf.index("<script>"))]

    assert 'localStorage.getItem("theme")' in inline
    assert "dataset.theme" in inline
    assert "defer" not in inline


def test_the_server_never_decides_the_colour(client: TestClient) -> None:
    """Ein Farbschema geht den Server nichts an (ADR 20): kein Feld im Profil,
    keine Route, kein Attribut im ausgelieferten HTML."""
    body = client.get("/").text

    assert "<html lang=\"de\">" in body
    assert "data-theme=" not in body


@pytest.mark.parametrize(
    ("alt", "neu"),
    [("/uebersicht", "/overview"), ("/vorschlaege?anlass=thema", "/suggestions?anlass=thema"),
     ("/profil", "/profile")],
)
def test_old_german_addresses_still_lead_home(data_dir: Path, alt: str, neu: str) -> None:
    """Die Routen sind seit dem 24.09.2026 englisch (ADR 22); ein altes
    Lesezeichen führt dauerhaft weiter, mit seiner Abfrage."""
    antwort = TestClient(create_app(), follow_redirects=False).get(alt)

    assert antwort.status_code == 301
    assert antwort.headers["location"] == neu
