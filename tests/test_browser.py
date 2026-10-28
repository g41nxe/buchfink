"""Ein paar Abläufe im echten Browser (#105).

Die Fehler, die tatsächlich gekostet haben — Zeichen auf zwei Zeilen, falsches
Bild im Dunkelmodus —, waren Darstellungsfehler. Die sieht kein Test, der nur
HTML liest. Hier läuft die Oberfläche in einem Faden, ein Browser klickt, und
geprüft wird **Layout, nicht Pixel**: eine Zeile bleibt eine Zeile (gleiche
Oberkante), nichts ragt seitlich heraus, hell und dunkel sind, was sie sein
sollen. Keine Screenshot-Vergleiche.

Eigene Gruppe: ``pytest -m browser``. Im CI bei jedem Push, lokal auf Wunsch.
Lokal genügt ein installiertes Edge (``channel="msedge"``); im CI holt
``playwright install chromium`` den Browser.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from ebook_watchlist import paths  # noqa: E402
from ebook_watchlist.models import MatchReason, Observation  # noqa: E402
from ebook_watchlist.store import Store  # noqa: E402

pytestmark = pytest.mark.browser

NOW = datetime(2026, 10, 25, 12, 0)

#: Telefon und Schreibtisch — die beiden Breiten, für die die Seiten gebaut sind.
VIEWPORTS = {"telefon": (390, 844), "schreibtisch": (1280, 900)}


@pytest.fixture(scope="session")
def browser() -> Iterator:
    with playwright_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch()
        except playwright_api.Error:
            # Lokal ohne `playwright install`: das Edge, das ohnehin da ist.
            launched = p.chromium.launch(channel="msedge")
        yield launched
        launched.close()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def server(data_dir: Path) -> Iterator[str]:
    """Die echte Oberfläche in einem Faden, gegen das Datenverzeichnis des Tests."""
    import uvicorn

    from ebook_watchlist.web import create_app

    port = _free_port()
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    for _ in range(200):
        if running.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(params=list(VIEWPORTS))
def page(request, browser) -> Iterator:
    width, height = VIEWPORTS[request.param]
    context = browser.new_context(viewport={"width": width, "height": height})
    opened = context.new_page()
    yield opened
    context.close()


def _found(store: Store, item_id: str, title: str) -> None:
    observation = Observation(
        source="beam", source_item_id=item_id, title=title, author="Wer Auch Immer",
        match_reason=MatchReason.GENRE_CATEGORY, price_cents=399,
        category="belletristik/krimi-thriller/psychothriller",
        url=f"https://beam.invalid/{item_id}", blurb="Ein Schiff, allein im Dunkeln.",
    )
    run_id = store.start_run("test", "test", NOW)
    store.append(run_id, "test", [observation], NOW)
    # Fertig: vor dem ersten fertigen Lauf erklärt sich die Startseite nur.
    store.finish_run(run_id, status="ok", delta_count=1, finished_at=NOW)


def _no_sideways_scroll(page) -> None:
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    if overflow > 0:
        # Wer herausragt, mit Klasse und Textanfang: sonst bleibt im CI nur die Zahl.
        culprits = page.evaluate("""() => {
            const edge = document.documentElement.clientWidth;
            return [...document.querySelectorAll('body *')]
                .filter(el => el.getBoundingClientRect().right > edge + 1)
                .filter(el => ![...el.children].some(
                    child => child.getBoundingClientRect().right > edge + 1))
                .slice(0, 3)
                .map(el => `${el.tagName}.${el.className}: ${el.textContent.trim().slice(0, 80)}`);
        }""")
        raise AssertionError(f"die Seite ragt {overflow} px seitlich heraus — {culprits}")


def _one_line(buttons) -> None:
    """Alle Knöpfe einer Reihe auf derselben Oberkante — der Fehler aus #22."""
    tops = {round(box["y"]) for b in buttons if (box := b.bounding_box())}
    assert len(tops) == 1, f"die Zeichen stehen auf {len(tops)} Zeilen: {sorted(tops)}"


# --- 1. Einen Vorschlag entscheiden und zurücknehmen ---------------------------


def test_a_suggestion_is_decided_and_taken_back(server: str, page, data_dir: Path) -> None:
    _found(Store(paths.db_path()), "b1", "Der verschwundene Leuchtturm")

    page.goto(server + "/")
    row = page.locator("li", has_text="Der verschwundene Leuchtturm").first
    row.wait_for()
    _no_sideways_scroll(page)
    _one_line(row.locator("button[name=kind]").all())

    row.locator("button[name=kind][value=dismissed]").click()
    page.get_by_role("button", name="Rückgängig").wait_for()
    assert page.locator("li", has_text="Der verschwundene Leuchtturm").count() == 0

    page.get_by_role("button", name="Rückgängig").click()
    page.locator("li", has_text="Der verschwundene Leuchtturm").first.wait_for()
    _no_sideways_scroll(page)


# --- 2. Einen Watchlist-Titel anlegen und „Nur Watchlist“ ------------------------


def test_a_watchlist_title_is_added_and_checked(server: str, page) -> None:
    page.goto(server + "/watchlist")
    form = page.locator("form[action='/watchlist/add']")
    form.locator("input[name=title]").fill("Kugelblitz")
    if form.locator("input[name=author]").count():
        form.locator("input[name=author]").fill("Cixin Liu")
    form.locator("button[type=submit]").click()

    page.locator("text=Kugelblitz").first.wait_for()
    _no_sideways_scroll(page)

    page.get_by_role("button", name="Nur Watchlist").first.click()
    # Durch die echte Schlange und einen echten Lauf gegen die Attrappe.
    page.locator("#run-slot, #run-panel").filter(has_text="Lauf").first.wait_for(timeout=30_000)
    _no_sideways_scroll(page)


# --- 3. Der Hammer auf einer Zeile -------------------------------------------------


def test_the_hammer_stays_in_its_row(server: str, page, monkeypatch) -> None:
    """Der Hammer stößt einen Steckbrief an, und die Zeile bleibt eine Zeile."""
    from ebook_watchlist.web import discovery

    monkeypatch.setattr(
        discovery, "portray", lambda *a, **k: "Kein Modell im Test", raising=True
    )
    _found(Store(paths.db_path()), "h1", "Ein Fund ohne Steckbrief")

    page.goto(server + "/suggestions")
    row = page.locator("li", has_text="Ein Fund ohne Steckbrief").first
    row.wait_for()
    hammer = row.locator("button[hx-post$='/portrait'], button[hx-post*='/portrait?']").first
    _one_line([*row.locator("button[hx-post*='/decide']").all(), hammer])

    hammer.click()
    page.wait_for_load_state("networkidle")
    row = page.locator("li", has_text="Ein Fund ohne Steckbrief").first
    _one_line([*row.locator("button[hx-post*='/decide']").all(),
               row.locator("button[hx-post*='/portrait']").first])
    _no_sideways_scroll(page)


# --- hell und dunkel -------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_light_and_dark_are_what_they_say(server: str, browser, scheme: str) -> None:
    context = browser.new_context(color_scheme=scheme, viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(server + "/")

    # Über eine Canvas: der Browser nennt die Farbe als oklch(), und deren
    # Zahlen als RGB zu lesen ergäbe Unsinn.
    lightness = page.evaluate("""() => {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 1;
        const pen = canvas.getContext("2d");
        pen.fillStyle = getComputedStyle(document.body).backgroundColor;
        pen.fillRect(0, 0, 1, 1);
        const [r, g, b] = pen.getImageData(0, 0, 1, 1).data;
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    }""")
    logo_loaded = page.evaluate(
        "[...document.images].every(img => img.complete && img.naturalWidth > 0)"
    )
    context.close()

    assert logo_loaded
    assert (lightness > 0.6) if scheme == "light" else (lightness < 0.3), lightness


def test_the_checks_notice_a_break(server: str, browser) -> None:
    """Gegenprobe: eine Prüfung, die nie anschlägt, prüft nichts."""
    _found(Store(paths.db_path()), "g1", "Gegenprobe")
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(server + "/")
    row = page.locator("li", has_text="Gegenprobe").first
    row.wait_for()
    page.add_style_tag(content="form[action='/suggestions/decide'] * { display: block !important;"
                               " width: 100% !important } body { min-width: 900px }")

    with pytest.raises(AssertionError, match="Zeilen"):
        _one_line(row.locator("button[name=kind]").all())
    with pytest.raises(AssertionError, match="seitlich"):
        _no_sideways_scroll(page)
    context.close()


def test_a_long_run_message_does_not_widen_the_page(server: str, page) -> None:
    """Ein Traceback trägt Pfade ohne Leerzeichen; im CI schob einer die
    Watchlist um 355 px breit (#105)."""
    page.goto(server + "/_design")
    page.locator("text=Lauf mit Fehlern beendet").first.wait_for()

    _no_sideways_scroll(page)


def test_the_header_stays_one_row_on_a_small_phone(server: str, browser) -> None:
    """Bei 360 px brach die Kopfzeile auf drei Reihen um, 109 px hoch — ein
    Siebtel des Bildschirms für Zeichen und fünf Verweise (Review, #118)."""
    context = browser.new_context(viewport={"width": 360, "height": 780})
    page = context.new_page()
    page.goto(server + "/watchlist")

    links = page.locator("header nav > a").all()
    _one_line(links)
    context.close()


def test_a_double_click_decides_only_one_find(server: str, browser) -> None:
    """Nach einer Entscheidung rückt die nächste Zeile nach, und ihre Knöpfe
    liegen dann unter dem Mauszeiger. Ein Doppelklick darf trotzdem nur das
    eine Buch entscheiden (Nebenbefund der Bewegungssuche, 28.10.2026)."""
    store = Store(paths.db_path())
    _found(store, "d1", "Das erste Buch")
    _found(store, "d2", "Das zweite Buch")
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.goto(server + "/suggestions")
    first = page.locator("li", has_text="Das erste Buch").first
    first.wait_for()

    # Der zweite Klick kommt kurz nach dem Austausch, auf dieselbe Stelle — dort
    # liegt jetzt der Knopf des nächsten Buchs (gemessen: dieselbe Höhe).
    box = first.get_by_role("button", name="Ausschließen").bounding_box()
    assert box is not None
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.click(x, y)
    page.locator("li", has_text="Das erste Buch").first.wait_for(state="detached")
    page.mouse.click(x, y)
    page.wait_for_timeout(800)
    page.reload()

    assert page.locator("li", has_text="Das zweite Buch").count() >= 1
    context.close()
