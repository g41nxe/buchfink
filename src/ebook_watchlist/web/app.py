"""The local web application (ADR 3).

Deliberately small: server-rendered Jinja, no build step, no websocket, no
scheduler. It reads the Snapshot and serves the Digests a Run has already
written — it never scrapes and never holds the Run lock, so restarting or
killing it cannot disturb a Run in progress.

No authentication. It is meant to be bound to a trusted home network; put a
password in front of it before exposing it anywhere else.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from .. import paths
from ..config import ConfigError, load_settings
from ..facets import GENERAL
from ..models import LinkOutcome
from ..relations import RelationKind
from ..single import Report
from ..sources import registry
from ..store import RunRow, Store
from . import (
    assignments,
    book,
    discovery,
    home,
    intake,
    owned,
    profile_page,
    sharpening,
    sorting,
    symbols,
    triage,
    watchlist,
)
from .recheck import Rechecker
from .runs import RunLauncher, journal_status

STATIC = Path(__file__).parent / "static"


def _link(path: str, **params: str) -> str:
    """Eine Adresse mit den Parametern, die etwas sagen.

    Filter und Sortierung stehen beide in der Abfrage und duerfen einander
    nicht abwerfen: wer im Stapel auf "Themen" klickt, behaelt seine
    Reihenfolge (#37). Leere Werte fallen weg — `?reason=` ist dasselbe wie
    nichts und liest sich nur schlechter.

    Hier und nicht in der Vorlage: die rechnet nichts.
    """
    given = {name: value for name, value in params.items() if value}
    return f"{path}?{urlencode(given)}" if given else path


def asset_version() -> str:
    """Der Zeitstempel des gebauten Stylesheets.

    Haengt an der Adresse, damit ein Browser nach einem Neubau nicht seine
    alte Kopie behaelt. Ohne das sieht jede CSS-Aenderung kaputt aus, und
    zwar so ueberzeugend, dass man den Fehler im Template sucht.
    """
    try:
        return str(int((STATIC / "app.css").stat().st_mtime))
    except OSError:  # pragma: no cover - fehlt nur ohne Build
        return "0"
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

#: Adresse einer Calibre-Web-Automated-Installation, falls daneben eine laeuft.
#: Gesetzt erscheint der Punkt in der Kopfzeile, leer nicht — die Adresse gilt
#: nur auf dem Rechner, auf dem beides laeuft, und fest verdrahtet waere sie
#: fuer jeden anderen ein toter Link (ADR 12).
#:
#: Als Jinja-Global und nicht im Kontext jeder Route: der Wert ist auf jeder
#: Seite derselbe, und ihn durch fuenfzehn Kontextwoerterbuecher zu reichen
#: waere fuenfzehnmal dieselbe Zeile.
TEMPLATES.env.globals["cwa_url"] = os.environ.get("EBW_CWA_URL", "").strip()


def _sum_chars(text: str) -> int:
    """Quersumme eines Titels — der Farbton des Platzhalter-Covers.

    Deterministisch, damit dasselbe Buch immer gleich aussieht und zwei
    nebeneinander sich unterscheiden.
    """
    return sum(ord(char) for char in text or "")


def _stars(value: float | None) -> str:
    """Sterne so schreiben, wie man sie sagt.

    Die Spalte traegt seit Ticket 54 Nachkommastellen, weil fremde Stimmen sie
    mitbringen — die Onleihe nennt 2.8. Eigene Urteile sind ganzzahlig, und
    "4.0 von 5" waere fuer sie eine Genauigkeit, die es nicht gibt.
    """
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}".replace(".", ",")


TEMPLATES.env.filters["sum_chars"] = _sum_chars
TEMPLATES.env.filters["stars"] = _stars

#: Digest files are named by the Run that wrote them. Serving anything else
#: from the data directory would turn a read-only page into a file browser.
DIGEST_NAME = re.compile(r"^digest-\d{4}-\d{2}-\d{2}(?:-\d{4})?\.html$")

#: Alte deutsche Adressen, die noch als Lesezeichen existieren koennen.
OLD_ADDRESSES: dict[str, str] = {
    "/uebersicht": "/overview",
    "/vorschlaege": "/suggestions",
    "/profil": "/profile",
}

#: FastAPI liest Formularfelder ueber diese Marker. Als Modulkonstante,
#: damit im Funktionskopf kein Aufruf steht (ruff B008).
_SELECTED = Form(default=[])


@dataclass(frozen=True, slots=True)
class DigestFile:
    name: str

    @property
    def label(self) -> str:
        """Der Tag, den der Bericht meint — aus dem Namen, nicht aus der
        Dateizeit.

        Beide standen bisher nebeneinander auf der Uebersicht: links wann die
        Datei geschrieben wurde, rechts als Linktext ihr Name, und darin das
        Datum des Berichts. Zwei aehnlich aussehende Daten, von denen nur eines
        jemanden interessiert. Die Dateizeit ist jetzt weg.
        """
        stamp = self.name[len("digest-") : -len(".html")]
        try:
            if len(stamp) > len("2026-09-08"):
                return f"{datetime.strptime(stamp, '%Y-%m-%d-%H%M'):%d.%m.%Y %H:%M}"
            return f"{datetime.strptime(stamp, '%Y-%m-%d'):%d.%m.%Y}"
        except ValueError:  # pragma: no cover - DIGEST_NAME laesst nichts anderes durch
            return self.name


def digest_files(limit: int = 30) -> list[DigestFile]:
    directory = paths.digests_dir()
    if not directory.exists():
        return []
    found = [
        DigestFile(path.name)
        for path in directory.glob("digest-*.html")
        if DIGEST_NAME.match(path.name)
    ]
    return sorted(found, key=lambda digest: digest.name, reverse=True)[:limit]


@lru_cache(maxsize=4)
def _store_for(path: Path) -> Store:
    """One Store per database file.

    Building it runs the schema migration, so creating one per request would
    re-check the schema on every page load.
    """
    return Store(path)


@dataclass(frozen=True, slots=True)
class SourceHealth:
    """One Source as the Dashboard shows it (Ticket 03)."""

    name: str
    #: Wie die Quelle der Leserin gegenueber heisst. "voebb" war nie ein Wort
    #: fuer sie (Ticket 14) — und welche Quelle eine Bibliothek ist, sagt die
    #: Registry, nicht eine Liste in der Vorlage.
    display: str
    enabled: bool
    ok: bool | None
    last_probe_at: datetime | None
    error: str | None
    consecutive_failures: int

    @property
    def state(self) -> str:
        if not self.enabled:
            return "pausiert"
        if self.ok is None:
            return "ungeprüft"
        return "ok" if self.ok else "Fehler"

    @property
    def note(self) -> str | None:
        """A Source failing for days is a different problem from one that just
        broke: the first needs a human, the second may be a redesign in flight."""
        if self.consecutive_failures > 1:
            return f"seit {self.consecutive_failures} Prüfungen"
        return None

    @property
    def seen(self) -> str:
        return f"{self.last_probe_at:%d.%m. %H:%M}" if self.last_probe_at else "nie"


def source_health(store: Store, settings) -> list[SourceHealth]:
    return [
        SourceHealth(
            name=row.name,
            display=registry.label(settings, row.name),
            enabled=row.enabled,
            ok=row.last_probe_ok,
            last_probe_at=row.last_probe_at,
            error=row.last_error,
            consecutive_failures=row.consecutive_failures or 0,
        )
        for row in store.sources()
    ]


def source_trouble(runs: list[RunRow]) -> list[str]:
    """What the most recent Run complained about.

    Kept alongside the per-Source health: a Source can parse fine and still
    fail mid-collect, and that failure is recorded only on the Run.
    """
    for run in runs:
        if run.finished_at is None:
            continue
        return [part.strip() for part in (run.error or "").split(";") if part.strip()]
    return []


def create_app() -> FastAPI:
    app = FastAPI(title="Buchfink", docs_url=None, redoc_url=None)
    # Build output is not in the repository (ADR 20), so say so plainly rather
    # than serving an unstyled page that looks like a CSS bug.
    if not (STATIC / "app.css").is_file():
        raise RuntimeError(
            "web assets are missing — run: uv run python -m ebook_watchlist.web.build"
        )
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    # Titelbilder liegen im Datenverzeichnis, nicht im Paket (Ticket 15).
    # StaticFiles verweigert Pfade ausserhalb des Wurzelordners, also kann
    # ein Dateiname von aussen nicht in das Datenverzeichnis greifen.
    covers = paths.covers_dir()
    covers.mkdir(parents=True, exist_ok=True)
    app.mount("/covers", StaticFiles(directory=covers), name="covers")

    # Ein Starter je Anwendung. Er haelt nur, was ein Neustart vergessen darf:
    # das Kind, das wir gestartet und noch nicht im Journal gesehen haben
    # (Ticket 10).
    launcher = RunLauncher()
    rechecker = Rechecker()

    #: Wer ausdrücklich um einen neuen Steckbrief gebeten hat (Knopf „neu
    #: beschreiben"): die Schlüssel der Jobs, die dann auch fragen sollen, wenn
    #: schon einer steht. Der Job holt sich sein Zeichen beim Start ab.
    portrait_again: set = set()

    def _portray_work(key) -> Report:
        """Die Arbeit des zweiten Verwalters: einen Steckbrief anlegen (#45, #48).

        Derselbe Verwalter wie beim engen Lauf, nur mit anderer Arbeit. Der
        Schlüssel sagt, was beschrieben wird: ``("book", 39)`` für die
        Buchseite, ``("item", "beam", "7")`` für einen Fund.
        """
        store, settings, now = _store_for(paths.db_path()), load_settings(), datetime.now()
        again = key in portrait_again
        portrait_again.discard(key)
        if key[0] == "book":
            return Report(trouble=book.portray(store, settings, key[1], now=now, again=again))
        return Report(
            trouble=discovery.portray(store, settings, key[1], key[2], now=now, again=again)
        )

    portrait_jobs = Rechecker(work=_portray_work)

    def _start_portrait(key, again: str) -> None:
        """Den Job anstoßen; mit ``again=1`` auch, wenn schon ein Steckbrief steht.

        Das Zeichen wird nur gesetzt, wenn nichts läuft: sonst bliebe es bis zur
        nächsten Arbeit liegen und machte einen gewöhnlichen Klick teuer.
        """
        running = portrait_jobs.state(key)
        if again == "1" and not (running is not None and running.busy):
            portrait_again.add(key)
        portrait_jobs.start(key)

    def _portrait_status(request: Request, key, url: str) -> Response:
        """Das Fragment neben *Steckbrief*, solange einer entsteht.

        Ist der Job fertig, kommt keine Zeile zurück, sondern die Bitte, die
        Seite neu zu laden: danach hat sich nicht eine Zeile geändert, sondern
        der ganze Abschnitt. Solange er läuft, fragt die Seite alle zwei
        Sekunden nach (ADR 3, kein Websocket).
        """
        job = portrait_jobs.state(key)
        if job is None or not job.busy:
            return Response(status_code=204, headers={"HX-Refresh": "true"})
        return TEMPLATES.TemplateResponse(
            request, "_portrait_status.html", {"url": url, "job": job, "present": False}
        )

    def _run_in_progress(store: Store, settings) -> bool:
        """Ob gerade ein grosser Lauf jedes Buch anfasst — fuer den Kopf der Seite."""
        return launcher.state(store, settings.slug).busy

    @app.exception_handler(ConfigError)
    def broken_configuration(request: Request, exc: ConfigError) -> HTMLResponse:
        """Eine unlesbare ``settings.yaml`` ist eine Auskunft, kein Absturz.

        Die Ansichtsseiten fingen das je einzeln ab, die Formulare gar nicht —
        dort gab es einen Traceback statt der Seite, die den Grund nennt. Hier
        gilt es für jede Route, auch für die, die es noch nicht gibt.
        """
        return TEMPLATES.TemplateResponse(
            request,
            "error.html",
            {"message": str(exc), "asset_version": asset_version()},
            status_code=500,
        )

    @app.get("/", response_class=HTMLResponse)
    def start_page(
        request: Request,
        rueckgaengig: str = "",
        art: str = "",
        undo: int | None = None,
        kind: str = "",
    ) -> HTMLResponse:
        """Was heute zählt — nicht der Zustand des Werkzeugs, der steht auf
        der Übersicht (Issue #5).

        Zwei Arten von Rücknahme, weil die Seite zwei Arten von Zeilen zeigt:
        ``rueckgaengig``/``art`` nennen einen entschiedenen Fund,
        ``undo``/``kind`` einen abgeschlossenen Watchlist-Eintrag (#22).
        """
        settings = load_settings()
        store = _store_for(paths.db_path())
        return TEMPLATES.TemplateResponse(
            request,
            "home.html",
            {
                "settings": settings,
                "asset_version": asset_version(),
                "view": home.build(store, settings, now=datetime.now()),
                "undo": home.undo_for(store, rueckgaengig, art) if rueckgaengig else None,
                "undo_entry": watchlist.undo_for(store, undo, kind) if undo else None,
                "closings": watchlist.CLOSINGS,
                # Der juengste Tagesbericht ist der Weg hinter "N Aenderungen";
                # der Lauf-Knopf ist derselbe wie auf der Uebersicht.
                "digest": next(iter(digest_files(limit=1)), None),
                "run_state": launcher.state(store, settings.slug),
                "actions": triage.ACTIONS,
                "icons": symbols.RELATION_ICONS,
                "arguments": home.ARGUMENTS,
            },
        )

    @app.get("/overview", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        try:
            settings = load_settings()
        except ConfigError as exc:
            return TEMPLATES.TemplateResponse(
                request,
                "error.html",
                {"message": str(exc), "asset_version": asset_version()},
                status_code=500,
            )

        store = _store_for(paths.db_path())
        runs = store.recent_runs(settings.slug)
        return TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            {
                "settings": settings,
                "asset_version": asset_version(),
                "runs": runs,
                "run_state": launcher.state(store, settings.slug),
                # Nicht run.status: ein abgeschossener Lauf steht dort fuer
                # immer als "running", weil der Prozess, der das haette
                # richtigstellen sollen, eben weg ist (Ticket 10).
                "run_status": journal_status(runs),
                "digests": digest_files(),
                "sources": source_health(store, settings),
                "trouble": source_trouble(runs),
            },
        )

    # --- Watchlist (Ticket 06) ---------------------------------------------

    def _watchlist_page(
        request: Request,
        message: str | None = None,
        nur: str = "",
        undo: int | None = None,
        kind: str = "",
        sortiert: str = "",
        existing: int | None = None,
        already: str = "",
    ) -> HTMLResponse:
        settings = load_settings()
        store = _store_for(paths.db_path())
        # Der aufgeloeste Schluessel, nicht der aus der Adresse: die Seite soll
        # auch bei einem Tippfehler die Reihenfolge anzeigen, die sie benutzt.
        order, chosen = sorting.chosen(sorting.WATCHLIST, sortiert)
        rows = watchlist.entries(store, settings, sort=order.slug)
        open_count = sum(1 for entry in rows if entry.needs_choice)
        only_unsure = nur == "unklar"
        return TEMPLATES.TemplateResponse(
            request,
            "watchlist.html",
            {
                "settings": settings,
                "asset_version": asset_version(),
                "entries": [e for e in rows if e.needs_choice] if only_unsure else rows,
                "message": message,
                "open_choices": open_count,
                "only_unsure": only_unsure,
                "closings": watchlist.CLOSINGS,
                "icons": symbols.RELATION_ICONS,
                "undo": watchlist.undo_for(store, undo, kind) if undo else None,
                "existing": watchlist.existing_notice(
                    store, settings.slug, existing, already_watched=already == "1"
                ),
                "orders": sorting.WATCHLIST,
                "sort": order.slug,
                "links": {
                    "all": _link("/watchlist", sortiert=chosen),
                    "unsure": _link("/watchlist", nur="unklar", sortiert=chosen),
                },
            },
        )

    @app.get("/watchlist", response_class=HTMLResponse)
    def watchlist_page(
        request: Request,
        nur: str = "",
        undo: int | None = None,
        kind: str = "",
        sortiert: str = "",
        existing: int | None = None,
        already: str = "",
    ) -> HTMLResponse:
        try:
            return _watchlist_page(
                request, nur=nur, undo=undo, kind=kind, sortiert=sortiert,
                existing=existing, already=already,
            )
        except ConfigError as exc:
            return TEMPLATES.TemplateResponse(
                request,
                "error.html",
                {"message": str(exc), "asset_version": asset_version()},
                status_code=500,
            )

    @app.post("/watchlist/add")
    def watchlist_add(title: str = Form(...), author: str = Form("")) -> RedirectResponse:
        # Die Anfrage selbst sucht nichts (ADR 3) — sie stoesst einen engen
        # Lauf an, und der sucht im Hintergrund. "Gesucht wird beim naechsten
        # Lauf" war die ehrliche Auskunft, solange es nur den grossen gab
        # (Ticket 51).
        if not title.strip():
            return RedirectResponse("/watchlist", status_code=303)
        settings = load_settings()
        added = watchlist.add(
            _store_for(paths.db_path()),
            settings.slug,
            title=title,
            author=author,
            now=datetime.now(),
        )
        book_id = added.book_id
        rechecker.start(book_id)
        # Und gleich ein Steckbrief dazu (#38, #48): das Tor beschreibt nur
        # Funde, und ein Watchlist-Titel ist keiner. Er ruht auf Titel und
        # Autor:in, denn mehr gibt es in dieser Sekunde nicht.
        portrait_jobs.start(("book", book_id))
        # Gab es das Buch schon, sagt die Liste es: sonst hält die Leserin es für
        # neu und wundert sich, dass es zugleich im Besitz ist.
        if added.existed:
            target = _link(
                "/watchlist",
                existing=str(book_id),
                already="1" if added.already_watched else "",
            )
            return RedirectResponse(target, status_code=303)
        return RedirectResponse("/watchlist", status_code=303)

    @app.post("/watchlist/{book_id}/active")
    def watchlist_active(
        book_id: int, active: str = Form(""), back: str = Form("/watchlist")
    ) -> RedirectResponse:
        """Pausieren und fortsetzen — nie loeschen (ADR 18)."""
        settings = load_settings()
        store = _store_for(paths.db_path())
        wanted = active == "1"
        if wanted:
            store.put_relation(
                settings.slug, book_id, str(RelationKind.WATCHING), now=datetime.now()
            )
        else:
            store.deactivate_relation(
                settings.slug, book_id, str(RelationKind.WATCHING), now=datetime.now()
            )
        return RedirectResponse(_page_back(back), status_code=303)

    @app.post("/book/{book_id}/restrict")
    def book_restrict(book_id: int, restrict: str = Form("")) -> RedirectResponse:
        """An welchen Quellen dieses Buch geprueft wird.

        Auf der Buchseite und nicht mehr in der Watchlist-Zeile: das ist eine
        **Einstellung**, keine Handlung, und sie stand dort im selben Menue
        wie die Abschluesse — was aus dem Menue eine Resterampe machte
        (docs/research/row-actions-and-overflow-menus.md, Ticket 48).
        """
        settings = load_settings()
        # Leer heisst "alle eingeschalteten Quellen", nicht "keine". Ein
        # unbekannter Wert scheitert in der Validierung des Ladens (Ticket 05).
        watchlist.set_restriction(
            _store_for(paths.db_path()),
            settings.slug,
            book_id,
            restrict or None,
            now=datetime.now(),
        )
        return RedirectResponse(f"/book/{book_id}", status_code=303)

    @app.post("/watchlist/{book_id}/recheck")
    def watchlist_recheck(
        request: Request, book_id: int, back: str = "/watchlist"
    ) -> HTMLResponse:
        """Genau diesen einen Eintrag jetzt pruefen (Ticket 51).

        Wer gerade bestaetigt, berichtigt oder aufgenommen hat, wartet sonst
        bis zum naechsten grossen Lauf — und der kann an diesem Titel schon
        vorbei sein.
        """
        rechecker.start(book_id)
        return _entry_row(request, book_id, back=back)

    @app.get("/watchlist/{book_id}/recheck")
    def watchlist_recheck_status(
        request: Request, book_id: int, back: str = "/watchlist"
    ) -> HTMLResponse:
        """Dasselbe Fragment, das der POST liefert — htmx fragt hier nach."""
        return _entry_row(request, book_id, back=back)

    def _entry_row(request: Request, book_id: int, back: str = "/watchlist") -> HTMLResponse:
        """Die eine Zeile, frisch gelesen, mit dem Stand ihres engen Laufs.

        Beide Routen liefern genau dieses Fragment, damit Knopf und Anzeige
        nicht auseinanderlaufen koennen — dieselbe Regel wie beim grossen Lauf.
        """
        settings = load_settings()
        store = _store_for(paths.db_path())
        entry = next(
            (e for e in watchlist.entries(store, settings) if e.book_id == book_id), None
        )
        if entry is None:
            raise HTTPException(status_code=404, detail="kein solcher Eintrag")
        return TEMPLATES.TemplateResponse(
            request,
            "_watchlist_row.html",
            {
                "entry": entry,
                "check": rechecker.state(book_id),
                "now": datetime.now(),
                "settings": settings,
                "closings": watchlist.CLOSINGS,
                "icons": symbols.RELATION_ICONS,
                # Die nachgeladene Zeile muss wissen, auf welcher Seite sie steht:
                # sonst fuehrt der Weg zurueck von der Startseite auf die
                # Watchlist (#22).
                "back": _page_back(back),
            },
        )

    def _page_back(target: str) -> str:
        """Startseite oder Watchlist — ein Formularfeld ist kein Ziel.

        Beide Seiten zeigen dieselbe Zeile mit denselben Zeichen (#22), und nach
        einer Entscheidung soll man dort stehen, wo man sie getroffen hat.
        """
        return "/" if target == "/" else "/watchlist"

    @app.post("/watchlist/{book_id}/finish")
    def watchlist_finish(
        book_id: int, kind: str = Form(...), back: str = Form("/watchlist")
    ) -> RedirectResponse:
        """Gekauft, oder nicht mehr interessant — und damit von der Liste.

        Setzt die Beziehung **und** legt das Beobachten still. Beides einzeln
        zu tun war der Mangel: ``owned`` stand neben einem aktiven
        ``watching``, und das Buch wurde weiter gemeldet (Ticket 48).
        """
        watchlist.finish(
            _store_for(paths.db_path()),
            load_settings().slug,
            book_id,
            kind,
            now=datetime.now(),
        )
        # Der Weg zurueck steht danach ueber der Liste: die zwei Zeichen stehen
        # jetzt offen in der Zeile statt hinter einem Menue, und eine Handlung
        # ohne Nachfrage braucht einen Weg zurueck (ADR 30, #22).
        target = _page_back(back)
        return RedirectResponse(f"{target}?undo={book_id}&kind={kind}", status_code=303)

    @app.post("/watchlist/undo")
    def watchlist_undo(
        book_id: int = Form(...), kind: str = Form(...), back: str = Form("/watchlist")
    ) -> RedirectResponse:
        """Einen Abschluss zuruecknehmen — der Eintrag steht wieder auf der Liste.

        Stillgelegt, nicht geloescht (ADR 18): ``owned`` bleibt als Zeile
        stehen und ruht, ``watching`` gilt wieder.
        """
        watchlist.unfinish(
            _store_for(paths.db_path()),
            load_settings().slug,
            book_id,
            kind,
            now=datetime.now(),
        )
        return RedirectResponse(_page_back(back), status_code=303)

    @app.post("/watchlist/{book_id}/confirm")
    def watchlist_confirm(
        book_id: int, source: str = Form(...), url: str = Form(...)
    ) -> RedirectResponse:
        """Eine unklare Zuordnung von Hand festmachen.

        Das ist der Vorgang, der im Texteditor und im Gespraech gleichermassen
        schlecht ist: eine URL suchen und in eine YAML kleben. Hier ist es ein
        Klick, und das Ergebnis heisst ``confirmed`` statt ``linked`` — ein
        Mensch hat entschieden, keine Heuristik.
        """
        _store_for(paths.db_path()).put_book_source(
            book_id,
            source,
            outcome=str(LinkOutcome.CONFIRMED),
            url=url,
            resolved_at=datetime.now(),
            reason="von Hand bestätigt",
        )
        return RedirectResponse("/watchlist", status_code=303)

    def _back(target: str) -> str:
        """Nur zurueck auf die Watchlist — ein Formularfeld ist kein Ziel.

        Ohne die Pruefung liesse sich ueber ein untergeschobenes Feld auf eine
        fremde Adresse umleiten.
        """
        return target if target in ("/watchlist", "/watchlist?nur=unklar") else "/watchlist"

    @app.post("/watchlist/{book_id}/rename")
    def watchlist_rename(
        book_id: int, title: str = Form(...), author: str = Form("")
    ) -> RedirectResponse:
        """Den Titel berichtigen, unter dem ein Buch gefuehrt wird (ADR 27).

        Die erste Bearbeitungsmoeglichkeit, die die Watchlist ueberhaupt hat.
        Sieben Titel mussten am 6.9. korrigiert werden, und jede einzelne
        Korrektur lief ueber SQL von Hand — ein Hinweis ohne Abhilfe waere
        nur ein Vorwurf gewesen.
        """
        store = _store_for(paths.db_path())
        if store.rename_book(book_id, title=title, author=author or None):
            # Der Sinn der Berichtigung ist, dass gesucht wird — und zwar
            # jetzt, nicht beim naechsten grossen Lauf (Ticket 51).
            rechecker.start(book_id)
        return RedirectResponse("/watchlist", status_code=303)

    @app.post("/watchlist/{book_id}/missing")
    def watchlist_missing(book_id: int, title: str = Form(...)) -> RedirectResponse:
        """„Kenne ich" — und das haelt.

        Gemerkt wird der Titel, nicht das Buch: nach einer Umbenennung ist es
        eine neue Behauptung ueber eine neue Eingabe, und der Hinweis kommt
        wieder (ADR 27).
        """
        store = _store_for(paths.db_path())
        settings = load_settings()
        kind = str(RelationKind.WATCHING)
        existing = next(
            (
                relation
                for relation in store.relations_of(settings.slug, book_id)
                if relation.kind == kind
            ),
            None,
        )
        details = json.loads(existing.details or "{}") if existing else {}
        details["known_missing"] = title
        store.set_relation_details(settings.slug, book_id, kind, details, now=datetime.now())
        return RedirectResponse("/watchlist", status_code=303)

    @app.post("/watchlist/{book_id}/assign")
    def watchlist_assign(
        book_id: int,
        source: str = Form(...),
        url: str = Form(""),
        action: str = Form(...),
        back: str = Form("/watchlist"),
    ) -> RedirectResponse:
        """Bestaetigen, ablehnen, oder eine Ablehnung zuruecknehmen.

        Auf der Watchlist und nicht auf einer eigenen Seite: der Titel, wie die
        Leserin ihn geschrieben hat, steht beim Entscheiden direkt darueber
        (Ticket 41).
        """
        store = _store_for(paths.db_path())
        now = datetime.now()
        if action == "confirm" and url:
            assignments.confirm(store, book_id, source, url, now)
            # Bestaetigt heisst: die Adresse steht. Der Preis dazu soll nicht
            # bis zum naechsten grossen Lauf warten (Ticket 51).
            rechecker.start(book_id)
        elif action == "none":
            assignments.reject_all(store, book_id, source, now)
        elif action == "restore":
            assignments.restore(store, book_id, source, now)
        # Dorthin zurueck, wo entschieden wurde. Vorher stand hier fest
        # ``?nur=unklar``: wer aus der vollen Liste heraus bestaetigte, landete
        # danach in der gefilterten — und sah seinen Eintrag nicht mehr.
        target = _back(back)
        # War es die letzte offene Frage, fuehrt der Filter in eine leere
        # Liste. Das ist kein Fehler, aber eine Sackgasse: die Seite sagt
        # "Nichts offen" und verlangt einen weiteren Klick, um wieder etwas
        # zu sehen. Dann lieber gleich die ganze Liste.
        if target.endswith("?nur=unklar") and not any(
            entry.needs_choice for entry in watchlist.entries(store, load_settings())
        ):
            target = "/watchlist"
        return RedirectResponse(target, status_code=303)


    # --- Buchseite (Ticket 07) ---------------------------------------------

    @app.get("/book/{book_id}", response_class=HTMLResponse)
    def book_page(request: Request, book_id: int) -> HTMLResponse:
        try:
            settings = load_settings()
        except ConfigError as exc:
            return TEMPLATES.TemplateResponse(
                request,
                "error.html",
                {"message": str(exc), "asset_version": asset_version()},
                status_code=500,
            )
        store = _store_for(paths.db_path())
        page = book.build(store, settings, book_id)
        if page is None:
            raise HTTPException(status_code=404, detail="kein solches Buch")
        return TEMPLATES.TemplateResponse(
            request,
            "book.html",
            {
                "settings": settings,
                "asset_version": asset_version(),
                "page": page,
                "kinds": book.KINDS,
                "icons": symbols.RELATION_ICONS,
                "restrictions": watchlist.RESTRICTIONS,
                "price_points": book.price_points(page.history),
                "portrait_job": portrait_jobs.state(("book", book_id)),
                "run_in_progress": _run_in_progress(store, settings),
                "sharpening": sharpening.build(store, settings, book_id),
            },
        )

    @app.post("/book/{book_id}/portrait")
    def book_portray(request: Request, book_id: int, again: str = "") -> Response:
        """Den Steckbrief dieses Buchs anlegen lassen (#45).

        Im Hintergrund wie das Urteil. Gibt es schon einen, kostet der Klick
        keinen Aufruf: dasselbe Buch trägt immer denselben Steckbrief — es sei
        denn, die Leserin bittet mit ``again=1`` ausdrücklich um einen neuen.
        """
        _start_portrait(("book", book_id), again)
        return _portrait_status(request, ("book", book_id), f"/book/{book_id}/portrait")

    @app.get("/book/{book_id}/portrait")
    def book_portray_status(request: Request, book_id: int) -> Response:
        """Hier fragt die Seite nach, solange der Steckbrief entsteht."""
        return _portrait_status(request, ("book", book_id), f"/book/{book_id}/portrait")

    @app.post("/book/{book_id}/edit")
    def book_edit(
        book_id: int,
        title: str = Form(...),
        author: str = Form(""),
    ) -> RedirectResponse:
        """Titel und Autor:in von der Buchseite aus aendern (ADR 27).

        Bisher gab es das Umbenennen nur auf der Watchlist, und dort nur,
        wenn keine Quelle den Titel fand. Es ist aber eine Eigenschaft
        *dieses Buchs*.

        Aendert sich der Titel, fallen die Zuordnungen weg und der enge Lauf
        sucht sofort neu (Ticket 51). Die Notiz bleibt unberuehrt: sie kommt
        aus der Watchlist-Datei und geht in keine Entscheidung ein.
        """
        store = _store_for(paths.db_path())
        if store.rename_book(book_id, title=title, author=author or None):
            rechecker.start(book_id)
        return RedirectResponse(f"/book/{book_id}", status_code=303)

    @app.post("/book/{book_id}/recheck")
    def book_recheck(request: Request, book_id: int) -> HTMLResponse:
        """Diesen einen Eintrag jetzt pruefen — von seiner eigenen Seite aus.

        Den engen Lauf gab es bisher nur im Menue der Watchlist-Zeile
        (Ticket 51). Gebraucht wird er hier: wer gerade einen Titel berichtigt
        oder eine Zuordnung bestaetigt hat, steht auf der Buchseite.
        """
        rechecker.start(book_id)
        return _book_status(request, book_id)

    @app.get("/book/{book_id}/recheck")
    def book_recheck_status(request: Request, book_id: int) -> HTMLResponse:
        """Dasselbe Fragment, das der POST liefert — htmx fragt hier nach."""
        return _book_status(request, book_id)

    def _book_status(request: Request, book_id: int) -> HTMLResponse:
        settings = load_settings()
        page = book.build(_store_for(paths.db_path()), settings, book_id)
        if page is None:
            raise HTTPException(status_code=404, detail="kein solches Buch")
        return TEMPLATES.TemplateResponse(
            request,
            "_book_status.html",
            {
                "page": page,
                "check": rechecker.state(book_id),
                "now": datetime.now(),
                "settings": settings,
            },
        )

    @app.post("/book/{book_id}/relation")
    def book_relation(
        book_id: int, kind: str = Form(...), active: str = Form("")
    ) -> RedirectResponse:
        """Eine Beziehung setzen oder stilllegen.

        Stilllegen statt loeschen: dass ein Buch einmal beobachtet wurde, ist
        selbst eine Auskunft (ADR 18).
        """
        store, settings = _store_for(paths.db_path()), load_settings()
        book.set_relation(store, settings, book_id, kind, active=active == "1",
                          now=datetime.now())
        # Nachschärfen braucht den Steckbrief (#51). Wer *Mag ich* oder *Doof*
        # sagt und ein Profil hat, bekommt ihn im Hintergrund; gibt es ihn
        # schon, kostet das nichts.
        if (
            active == "1"
            and kind in (str(RelationKind.LIKED), str(RelationKind.DISLIKED))
            and store.reading_profile(settings.slug) is not None
        ):
            portrait_jobs.start(("book", book_id))
        return RedirectResponse(f"/book/{book_id}", status_code=303)

    # --- Nachschärfen (#51) --------------------------------------------------

    def _sharpen(book_id: int, action) -> RedirectResponse:
        try:
            action(_store_for(paths.db_path()), load_settings())
        except intake.IntakeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(f"/book/{book_id}#sharpening", status_code=303)

    @app.post("/book/{book_id}/sharpen/liked")
    def sharpen_liked(
        book_id: int, family: str = Form(...), on: str = Form("")
    ) -> RedirectResponse:
        """Ein Merkmal oder Erzählmuster dieses Buchs antippen — oder lösen."""
        return _sharpen(book_id, lambda store, settings: sharpening.set_liked(
            store, settings, book_id, family, on=on == "1", now=datetime.now()))

    @app.post("/book/{book_id}/sharpen/boost")
    def sharpen_boost(
        book_id: int, family: str = Form(...), on: str = Form("")
    ) -> RedirectResponse:
        """Ein gemochtes Merkmal verstärken — oder die Verstärkung zurücknehmen."""
        return _sharpen(book_id, lambda store, settings: sharpening.set_boosted(
            store, settings, book_id, family, on=on == "1", now=datetime.now()))

    @app.post("/book/{book_id}/sharpen/counterweight")
    async def sharpen_counterweight(request: Request, book_id: int) -> RedirectResponse:
        """Gegengewichte aus einem *Doof*-Buch; je Familie ihr Umfang.

        Asynchron nur, um die Felder `scope-<familie>` zu lesen, deren Namen
        vorher niemand kennt. Die Arbeit selbst läuft im Threadpool wie in jeder
        anderen Route — sonst hielte der Zugriff auf SQLite alle Anfragen an.
        """
        form_data = await request.form()
        scopes = {
            str(f): str(form_data.get(f"scope-{f}") or GENERAL)
            for f in form_data.getlist("family")
        }
        return await run_in_threadpool(
            _sharpen, book_id, lambda store, settings: sharpening.add_counterweights(
                store, settings, book_id, scopes, now=datetime.now()))

    @app.post("/book/{book_id}/sharpen/reasons")
    async def sharpen_reasons(request: Request, book_id: int) -> RedirectResponse:
        """Deine Sicht auf ein gelesenes Buch: was nicht stimmt, was fehlte (#79).

        Asynchron nur, um die mehrfachen Felder zu lesen, wie beim Gegengewicht.
        """
        form_data = await request.form()
        drop = [str(f) for f in form_data.getlist("drop")]
        add = [str(f) for f in form_data.getlist("add")]
        return await run_in_threadpool(
            _sharpen, book_id, lambda store, settings: sharpening.set_reasons(
                store, settings, book_id, drop, add, now=datetime.now()))

    @app.post("/book/{book_id}/stars")
    def book_stars(book_id: int, stars: str = Form("")) -> RedirectResponse:
        """Die eigenen Sterne der Leserin setzen — oder zurücknehmen.

        Ein leeres Feld nimmt zurück und schreibt keine Null: "nicht bewertet"
        und "passt überhaupt nicht" sind zwei verschiedene Auskünfte.
        """
        try:
            value = int(stars) if stars else None
        except ValueError:
            raise HTTPException(status_code=400, detail="keine Sternzahl") from None
        try:
            book.set_stars(
                _store_for(paths.db_path()), load_settings(), book_id, value, now=datetime.now()
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(f"/book/{book_id}", status_code=303)

    # --- Die Seite zu einem Fund (Issue #9) ---------------------------------

    @app.get("/discovery/{source}/{item_id}", response_class=HTMLResponse)
    def discovery_page(request: Request, source: str, item_id: str) -> HTMLResponse:
        """Die Buchseite ohne das, was es vor einer Entscheidung nicht gibt.

        Sobald der Fund eine Buch-Zeile mit einer *geltenden* Beziehung hat,
        ist die Buchseite die reichere Ansicht — dann fuehrt diese Adresse
        dorthin, statt eine aermere Fassung desselben Buchs zu zeigen.

        Auf die Beziehung kommt es an, nicht auf die Zeile: eine
        zurueckgenommene Entscheidung legt sie stumm und laesst Buch und
        Verknuepfung stehen (ADR 18). Der Fund steht danach wieder im Stapel,
        und sein Titel muss dorthin fuehren, wo ueber ihn entschieden wird —
        nicht auf eine Buchseite, auf der nichts mehr gilt. Die Frage nach der
        Beziehung bindet die Weiterleitung ausserdem ans Profil; die
        Nummernsuche allein tut das nicht.
        """
        settings = load_settings()
        store = _store_for(paths.db_path())
        book_id = store.book_by_source_item(source, item_id)
        if book_id is not None and any(
            row.active for row in store.relations_of(settings.slug, book_id)
        ):
            return RedirectResponse(f"/book/{book_id}", status_code=303)
        page = discovery.build(store, settings, source, item_id)
        if page is None:
            raise HTTPException(status_code=404, detail="kein solcher Fund")
        return TEMPLATES.TemplateResponse(
            request,
            "discovery.html",
            {
                "settings": settings,
                "asset_version": asset_version(),
                "page": page,
                "actions": triage.ACTIONS,
                "icons": symbols.RELATION_ICONS,
                "portrait_job": portrait_jobs.state(("item", source, item_id)),
                "run_in_progress": _run_in_progress(store, settings),
            },
        )

    @app.post("/discovery/{source}/{item_id}/portrait")
    def discovery_portray(
        request: Request, source: str, item_id: str, again: str = ""
    ) -> Response:
        """Einen Fund beschreiben lassen — derselbe Weg wie auf der Buchseite (#48)."""
        key = ("item", source, item_id)
        _start_portrait(key, again)
        return _portrait_status(request, key, f"/discovery/{source}/{item_id}/portrait")

    @app.get("/discovery/{source}/{item_id}/portrait")
    def discovery_portray_status(request: Request, source: str, item_id: str) -> Response:
        key = ("item", source, item_id)
        return _portrait_status(request, key, f"/discovery/{source}/{item_id}/portrait")

    # --- Triage (Ticket 08) -------------------------------------------------

    @app.get("/suggestions", response_class=HTMLResponse)
    def triage_page(
        request: Request, reason: str = "", anlass: str = "", sortiert: str = ""
    ) -> HTMLResponse:
        # `anlass` ist der alte Name des Filters (#57); eine Adresse als
        # Lesezeichen führt weiter zum selben Stapel.
        reason = reason or anlass
        try:
            settings = load_settings()
        except ConfigError as exc:
            return TEMPLATES.TemplateResponse(
                request,
                "error.html",
                {"message": str(exc), "asset_version": asset_version()},
                status_code=500,
            )
        order, chosen = sorting.chosen(sorting.SUGGESTIONS, sortiert)
        pile = triage.pending(
            _store_for(paths.db_path()),
            settings,
            reason=reason or None,
            sort=order.slug,
        )
        return TEMPLATES.TemplateResponse(
            request,
            "triage.html",
            {
                "settings": settings,
                "asset_version": asset_version(),
                "pile": pile,
                "actions": triage.ACTIONS,
                "icons": symbols.RELATION_ICONS,
                "reason": reason,
                "orders": sorting.SUGGESTIONS,
                "sort": order.slug,
                # Das Formular schickt es mit, damit die Entscheidung in
                # derselben Reihenfolge endet, in der sie getroffen wurde.
                "chosen": chosen,
                # Ein Filter wirft die Sortierung nicht weg und umgekehrt.
                "links": {
                    "all": _link("/suggestions", sortiert=chosen),
                    "profile_author": _link(
                        "/suggestions", reason="profile_author", sortiert=chosen
                    ),
                    "genre_category": _link(
                        "/suggestions", reason="genre_category", sortiert=chosen
                    ),
                },
            },
        )

    @app.post("/suggestions/decide")
    def triage_decide(
        kind: str = Form(...),
        keys: list[str] = _SELECTED,
        reason: str = Form(""),
        sortiert: str = Form(""),
        back: str = Form("/suggestions"),
    ) -> RedirectResponse:
        """Eine Entscheidung auf die Auswahl anwenden.

        Alle drei schreiben eine Beziehung auf Buchebene — "verworfen" ist
        keine Loeschung, sondern eine Aussage ueber das Buch, und sie gilt
        dadurch bei *jeder* Quelle statt nur fuer eine Produktnummer (ADR 18).

        Zurueck dorthin, wo entschieden wurde: von der Startseite aus auf die
        Startseite, mit dem Angebot, es rueckgaengig zu machen — ein Klick
        ohne Nachfrage braucht einen Weg zurueck (ADR 30). Von der Fundseite
        aus auf die Buchseite: der Fund *ist* jetzt ein Buch (ADR 18), und in
        den Stapel zurueckzuspringen hiesse, die eigene Entscheidung dort zu
        suchen, wo sie gerade verschwunden ist. Ein Formularfeld ist kein Ziel;
        was nicht zu diesen beiden Faellen passt, fuehrt in den Stapel.
        """
        store = _store_for(paths.db_path())
        try:
            triage.decide(store, load_settings(), keys, kind, now=datetime.now())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if back == "buch" and len(keys) == 1:
            source, _, item_id = keys[0].partition(":")
            book_id = store.book_by_source_item(source, item_id)
            if book_id is not None:
                return RedirectResponse(f"/book/{book_id}", status_code=303)
        if back == "/":
            if len(keys) == 1:
                return RedirectResponse(
                    "/?" + urlencode({"rueckgaengig": keys[0], "art": kind}), status_code=303
                )
            return RedirectResponse("/", status_code=303)
        # Filter *und* Reihenfolge ueberleben die Entscheidung: nach dem
        # Ausschliessen von drei Funden steht man sonst in einer anders
        # geordneten Liste als der, aus der man sie gewaehlt hat (#37).
        return RedirectResponse(
            _link("/suggestions", reason=reason, sortiert=sortiert), status_code=303
        )

    @app.post("/suggestions/{source}/{item_id}/decide", response_class=HTMLResponse)
    def triage_decide_one(source: str, item_id: str, kind: str = Form(...)) -> HTMLResponse:
        """Genau diesen einen Fund entscheiden (Issue #9).

        Eine eigene Route statt eines Knopfes im grossen Formular: die Seite
        ist *ein* Formular, ein Absende-Knopf darin schickte die angehakte
        Auswahl statt seiner Zeile — und ein Knopf kann nicht gleichzeitig
        `kind` und `keys` senden. Also htmx, wie beim Lauf-Panel.

        Die Antwort ist leer: htmx tauscht die Zeile dagegen aus, und damit
        ist sie weg. Die Auswahl der uebrigen Zeilen bleibt unberuehrt.
        """
        try:
            decided = triage.decide(
                _store_for(paths.db_path()),
                load_settings(),
                [f"{source}:{item_id}"],
                kind,
                now=datetime.now(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not decided:
            raise HTTPException(status_code=404, detail="kein solcher Fund")
        return HTMLResponse("")

    @app.post("/suggestions/undo")
    def triage_undo(
        key: str = Form(...), kind: str = Form(...), back: str = Form("/")
    ) -> RedirectResponse:
        """Eine Entscheidung zuruecknehmen: die Beziehung wird stillgelegt,
        nicht geloescht (ADR 18) — und der Fund steht wieder im Stapel."""
        home.undo(
            _store_for(paths.db_path()), load_settings(), key, kind, now=datetime.now()
        )
        return RedirectResponse("/" if back == "/" else "/suggestions", status_code=303)

    # --- Meine Bücher (#71) --------------------------------------------------

    @app.get("/owned", response_class=HTMLResponse)
    def owned_page(request: Request, sortiert: str = "") -> HTMLResponse:
        """Alles, was die Leserin als *Hab ich* führt — nur zum Ansehen."""
        try:
            settings = load_settings()
        except ConfigError as exc:
            return TEMPLATES.TemplateResponse(
                request,
                "error.html",
                {"message": str(exc), "asset_version": asset_version()},
                status_code=500,
            )
        order, _ = sorting.chosen(sorting.OWNED, sortiert)
        return TEMPLATES.TemplateResponse(
            request,
            "owned.html",
            {
                "settings": settings,
                "asset_version": asset_version(),
                "books": owned.build(_store_for(paths.db_path()), settings, order.slug),
                "orders": sorting.OWNED,
                "sort": order.slug,
            },
        )

    # --- Profiluebersicht (Ticket 09) ---------------------------------------

    @app.get("/profile", response_class=HTMLResponse)
    def profile_overview(request: Request) -> HTMLResponse:
        """Nur lesend, und das ist die Entscheidung.

        Der Massstab hat ein eigenes Aenderungsverfahren mit asymmetrischer
        Beweislast (ADR 17). Ein Formular hier wuerde es umgehen — deshalb gibt
        es zu dieser Seite keine schreibende Route.
        """
        try:
            settings = load_settings()
        except ConfigError as exc:
            return TEMPLATES.TemplateResponse(
                request,
                "error.html",
                {"message": str(exc), "asset_version": asset_version()},
                status_code=500,
            )
        return TEMPLATES.TemplateResponse(
            request,
            "profile.html",
            {
                "settings": settings,
                "asset_version": asset_version(),
                "view": profile_page.build(_store_for(paths.db_path()), settings),
            },
        )

    # --- Erstaufnahme (#47) --------------------------------------------------

    def _identify_work(key) -> Report:
        """Die Arbeit des vierten Verwalters: erkennen, welches Buch gemeint ist.

        Ein eigener Verwalter: während die Leserin das dritte Buch tippt,
        arbeiten die ersten beiden noch, jedes unter seinem Schlüssel.
        """
        store, settings, now = _store_for(paths.db_path()), load_settings(), datetime.now()
        return Report(trouble=intake.identify(store, settings, key[1], now=now))

    identifier = Rechecker(work=_identify_work)

    def _intake_jobs(entries) -> dict:
        """Der Stand je Eintrag — und wer noch keinen Steckbrief hat und nicht
        gefragt wird, wird jetzt gefragt. So holt die Seite nach einem Abbruch
        oder einem Neustart des Servers nach, was offen war. Ein Fehler wird
        nicht von selbst wiederholt; dafür steht "Nochmal" da."""
        jobs = {}
        for e in entries:
            if e.state != "asking":
                continue
            job = identifier.state(("intake", e.id))
            jobs[e.id] = job if job is not None else identifier.start(("intake", e.id))
        return jobs

    def _intake_side(request: Request, kind: str, error: str | None = None) -> Response:
        """Eine Seite der Erstaufnahme als Bruchstück, nach jeder Handlung."""
        page = intake.build(_store_for(paths.db_path()), load_settings())
        side = page.liked if kind == str(RelationKind.LIKED) else page.disliked
        return TEMPLATES.TemplateResponse(
            request,
            "_intake_side.html",
            {"side": side, "page": page, "jobs": _intake_jobs(side.entries),
             "error": error, "oob": True},
        )

    def _intake_answer(request: Request, kind: str, error: str | None = None) -> Response:
        """Mit htmx das Bruchstück, ohne die ganze Seite neu."""
        if request.headers.get("HX-Request"):
            return _intake_side(request, kind, error)
        return RedirectResponse("/intake", status_code=303)

    @app.get("/intake", response_class=HTMLResponse)
    def intake_page(request: Request) -> HTMLResponse:
        """Bücher nennen und bestätigen — die ersten Schritte zum Leseprofil."""
        page = intake.build(_store_for(paths.db_path()), load_settings())
        return TEMPLATES.TemplateResponse(
            request,
            "intake.html",
            {
                "page": page,
                "jobs": _intake_jobs((*page.liked.entries, *page.disliked.entries)),
                "asset_version": asset_version(),
            },
        )

    @app.post("/intake/entry")
    def intake_add(
        request: Request, side: str = Form(...), title: str = Form(""), author: str = Form("")
    ) -> Response:
        try:
            entry = intake.add(
                _store_for(paths.db_path()), load_settings(), side, title, author,
                now=datetime.now(),
            )
        except intake.IntakeError as exc:
            if side not in intake.SIDES:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return _intake_answer(request, side, str(exc))
        identifier.start(("intake", entry))
        return _intake_answer(request, side)

    def _intake_row(entry_id: int):
        row = _store_for(paths.db_path()).intake_entry(entry_id)
        if row is None:
            raise HTTPException(status_code=404)
        return row

    @app.get("/intake/entry/{entry_id}")
    def intake_entry_state(request: Request, entry_id: int) -> Response:
        """Hier fragt ein Eintrag nach, solange das Modell arbeitet (ADR 3)."""
        e = intake.entry(_store_for(paths.db_path()), _intake_row(entry_id))
        return TEMPLATES.TemplateResponse(
            request, "_intake_entry.html", {"e": e, "jobs": _intake_jobs((e,))}
        )

    @app.post("/intake/entry/{entry_id}/confirm")
    def intake_confirm(request: Request, entry_id: int) -> Response:
        row = _intake_row(entry_id)
        try:
            intake.confirm(_store_for(paths.db_path()), load_settings(), entry_id,
                           now=datetime.now())
        except intake.IntakeError as exc:
            return _intake_answer(request, row.side, str(exc))
        return _intake_answer(request, row.side)

    @app.post("/intake/entry/{entry_id}/retype")
    def intake_retype(
        request: Request, entry_id: int, title: str = Form(""), author: str = Form("")
    ) -> Response:
        row = _intake_row(entry_id)
        try:
            intake.retype(_store_for(paths.db_path()), entry_id, title, author)
        except intake.IntakeError as exc:
            return _intake_answer(request, row.side, str(exc))
        identifier.start(("intake", entry_id))
        return _intake_answer(request, row.side)

    @app.post("/intake/entry/{entry_id}/retry")
    def intake_retry(request: Request, entry_id: int) -> Response:
        row = _intake_row(entry_id)
        identifier.start(("intake", entry_id))
        return _intake_answer(request, row.side)

    @app.post("/intake/entry/{entry_id}/remove")
    def intake_remove(request: Request, entry_id: int) -> Response:
        row = _intake_row(entry_id)
        intake.remove(_store_for(paths.db_path()), load_settings(), entry_id, now=datetime.now())
        return _intake_answer(request, row.side)

    # --- Erstaufnahme, Bildschirme 3 bis 5 (#50) ------------------------------

    #: Die Schritte nach dem Nennen, mit ihrer Adresse.
    _STEPS = {3: "/intake/common", 4: "/intake/lost",
                 5: "/intake/profile"}

    def _choosing(request: Request, step: int, *, fragment: bool) -> Response:
        """Bildschirm 3 oder 4 — ganz, oder als Bruchstück nach einem Tipp."""
        choice = intake.choosing(_store_for(paths.db_path()), load_settings())
        context = {"choice": choice, "step": step}
        if fragment:
            return TEMPLATES.TemplateResponse(request, "_intake_choices.html", context)
        return TEMPLATES.TemplateResponse(
            request, "intake_choice.html", {**context, "asset_version": asset_version()}
        )

    @app.get("/intake/common", response_class=HTMLResponse)
    def intake_common(request: Request) -> Response:
        """Bildschirm 3: was deine Bücher gemeinsam haben."""
        return _choosing(request, 3, fragment=False)

    @app.get("/intake/lost", response_class=HTMLResponse)
    def intake_lost(request: Request) -> Response:
        """Bildschirm 4: was dich an den enttäuschenden Büchern verloren hat."""
        return _choosing(request, 4, fragment=False)

    def _after_choice(request: Request, step: int) -> Response:
        if request.headers.get("HX-Request"):
            return _choosing(request, step, fragment=True)
        return RedirectResponse(_STEPS.get(step, "/intake/common"),
                                status_code=303)

    @app.post("/intake/choice")
    def intake_choose(
        request: Request,
        side: str = Form(...),
        family: str = Form(...),
        on: str = Form(""),
        step: int = Form(3),
    ) -> Response:
        """Eine Familie antippen oder wieder lösen — sofort gespeichert."""
        try:
            intake.choose(
                _store_for(paths.db_path()), load_settings(), side, family, on=bool(on),
            )
        except (intake.IntakeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _after_choice(request, step)

    @app.post("/intake/scope")
    def intake_scope(
        request: Request, family: str = Form(...), scope: str = Form(...),
    ) -> Response:
        """Die Nachfrage beim Gegengewicht: nur hier, überall, oder mit dem Genre."""
        try:
            intake.set_scope(_store_for(paths.db_path()), load_settings(), family, scope)
        except intake.IntakeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _after_choice(request, 4)

    @app.get("/intake/profile", response_class=HTMLResponse)
    def intake_profile(request: Request) -> Response:
        """Bildschirm 5: dein Profil — bestätigen."""
        choice = intake.choosing(_store_for(paths.db_path()), load_settings())
        return TEMPLATES.TemplateResponse(
            request, "intake_profile.html",
            {"choice": choice, "step": 5, "asset_version": asset_version()},
        )

    @app.post("/intake/profile")
    def intake_adopt() -> RedirectResponse:
        """Bestätigt wird die erste Fassung; nichts gemocht heißt neu anfangen.

        Facetten wählt niemand aus: das Werkzeug bildet sie aus dem, was
        angetippt ist (24.09.2026). Auch Gegengewichte werden hier nicht mehr
        gewählt — was auf Schritt 4 angetippt ist, wird übernommen.
        """
        adopted = intake.adopt(
            _store_for(paths.db_path()), load_settings(), now=datetime.now(),
        )
        return RedirectResponse("/profile" if adopted else "/intake", status_code=303)

    # --- Jetzt laufen (Ticket 10) -------------------------------------------

    def _run_panel(request: Request, decide, refresh_when_over: bool = False) -> HTMLResponse:
        try:
            settings = load_settings()
        except ConfigError as exc:
            return TEMPLATES.TemplateResponse(
                request,
                "error.html",
                {"message": str(exc), "asset_version": asset_version()},
                status_code=500,
            )
        store = _store_for(paths.db_path())
        state = decide(store, settings.slug)
        headers = {"HX-Refresh": "true"} if refresh_when_over and not state.busy else None
        return TEMPLATES.TemplateResponse(
            request, "_run_panel.html", {"run_state": state}, headers=headers
        )

    @app.post("/run", response_class=HTMLResponse)
    def start_run(request: Request) -> HTMLResponse:
        """Einen Lauf starten — als eigener Prozess, nie hier drin (ADR 3).

        Antwortet mit demselben Bruchstueck, das auch die Abfrage liefert: so
        koennen der Knopf und der Zustand, den er erzeugt, sich nicht
        widersprechen.
        """
        return _run_panel(request, lambda store, slug: launcher.start(store, slug))

    @app.get("/run/status", response_class=HTMLResponse)
    def run_status(request: Request) -> HTMLResponse:
        """Was der laufende Lauf gerade tut. Abgefragt, nicht geschoben (ADR 3).

        Nur ein Panel, das abfragt, fragt hier — und es fragt nur, solange ein
        Lauf laeuft. Eine Antwort "laeuft nicht mehr" heisst also: dieser Lauf
        ist eben zu Ende, und der Rest der Seite ist veraltet. Einmal neu zu
        laden ist billiger, als vier Abschnitten das Abfragen beizubringen.
        """
        return _run_panel(
            request, lambda store, slug: launcher.state(store, slug), refresh_when_over=True
        )

    @app.get("/digest/{name}", response_class=HTMLResponse)
    def digest(name: str) -> HTMLResponse:
        # The Run already rendered this through the HTML renderer; serving the
        # file is what keeps there from being a second implementation.
        if not DIGEST_NAME.match(name):
            raise HTTPException(status_code=404, detail="no such digest")
        path = paths.digests_dir() / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="no such digest")
        return HTMLResponse(path.read_text(encoding="utf-8"))

    # Die Routen hießen bis zum 24.09.2026 deutsch; seitdem englisch wie jeder
    # Bezeichner (ADR 22). Die drei Seiten, die jemand als Lesezeichen haben
    # kann, leiten dauerhaft weiter — mit ihrer Abfrage, damit Filter und
    # Sortierung mitkommen.
    def _redirect_to(new: str):
        def redirect(request: Request) -> RedirectResponse:
            query = request.url.query
            return RedirectResponse(new + (f"?{query}" if query else ""), status_code=301)

        return redirect

    for old, new in OLD_ADDRESSES.items():
        app.add_api_route(old, _redirect_to(new), methods=["GET"], include_in_schema=False)

    return app


app = create_app()
