"""Ein Lauf für einen Eintrag (Ticket 51).

Wer gerade etwas an einem Eintrag geändert hat, wartet nicht bis zum nächsten
großen Lauf, um das Ergebnis zu sehen. Am 6.9.2026 traf das dreimal
hintereinander: *Dark Matter* stand nach dem Bestätigen ohne Preis da, und die
sieben umbenannten Titel ebenso — Adresse gefunden, Betrag erst am nächsten
Tag.

Von Hand war es je **eine** Anfrage. Gemessen: 102 ms für die Zuordnung aus
dem Gedächtnis, 1980 ms für den Abruf.

Der Weg ist nicht neu, nur schmal: gesammelt wird über dieselbe
``Source.collect``, nur mit einer Watchlist aus genau einem Eintrag. Damit
gelten alle Regeln, die auch sonst gelten — ``restrict``, pausierte Quellen,
gemerkte Zuordnungen, die Wiederholungsfrist.

Und es gilt weiterhin: **zwei Läufe gleichzeitig gibt es nicht.** Ist die
Sperre belegt, wird gewartet, nicht aufgegeben — der große Lauf arbeitet die
Einträge der Reihe nach ab, und ist er an diesem Titel schon vorbei, sähe er
die Änderung nicht mehr.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from filelock import FileLock, Timeout

from . import paths
from .config import Settings, WatchlistEntry, load_settings
from .configuration import NotSeeded
from .configuration import load as load_configuration
from .covers import fetch_for_books, fetch_for_candidates
from .dnb import Dnb, OriginalTitles
from .http import HttpClient, build_user_agent
from .models import Observation
from .sources import build_sources
from .sources.base import RunContext
from .store import ENTRY_TRIGGER, Store

#: Wie lange ein enger Lauf auf einen großen wartet, bevor er aufgibt.
#: Gemessen an sechzehn Läufen: Median 135 s, längster 395 s. Zehn Minuten
#: liegen deutlich darüber — wer länger wartet, hat keinen langen Lauf,
#: sondern einen hängenden.
WAIT_FOR_LOCK = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class Report:
    """Was der enge Lauf zu diesem einen Eintrag gefunden hat."""

    #: Warum es nicht geklappt hat — sonst leer.
    trouble: str = ""
    observations: tuple[Observation, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.trouble


def _entry_for(book_id: int, store: Store, settings: Settings) -> WatchlistEntry | None:
    """Der Watchlist-Eintrag zu dieser Buch-Nummer.

    Über Titel und Autor:in gesucht und nicht über eine Spalte: ein Eintrag
    trägt in diesem Schnitt noch keine Buch-Nummer, seine Identität entsteht
    aus beidem (ADR 18). ``book_for`` legt dieselbe Zuordnung an.
    """
    book = store.book(book_id)
    if book is None:
        return None
    try:
        configured = load_configuration(store, settings)
    except NotSeeded:
        return None
    wanted = (book.title.strip().casefold(), (book.author or "").strip().casefold())
    for entry in configured.watchlist:
        if (entry.title.strip().casefold(), (entry.author or "").strip().casefold()) == wanted:
            return entry
    return None


def check_one(book_id: int, *, now: datetime | None = None) -> Report:
    """Genau diesen einen Eintrag prüfen — Zuordnung, Preis, Verfügbarkeit.

    Blockiert, solange ein großer Lauf die Sperre hält. Der Aufrufer ist
    deshalb ein Faden, kein Anfragebearbeiter (``web/recheck.py``).
    """
    now = now or datetime.now()
    store = Store(paths.db_path())
    settings = load_settings()

    entry = _entry_for(book_id, store, settings)
    if entry is None:
        return Report(trouble="kein Watchlist-Eintrag zu diesem Buch")
    if not entry.active:
        return Report(trouble="der Eintrag ist pausiert")

    # Mit Kontaktadresse, wie im Rundgang (``run.py``): ein Betreiber, der
    # wissen will, wer da fragt, soll es nicht davon abhaengig finden, ob die
    # Leserin den Knopf gedrueckt oder der Wirt gerufen hat.
    client = HttpClient(user_agent=build_user_agent(settings.contact))
    sources = build_sources(settings, client)
    enabled = [source for source in sources if store.is_enabled(source.name)]
    if not enabled:
        return Report(trouble="keine Quelle eingeschaltet")

    paths.data_dir().mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(paths.lock_path()), timeout=WAIT_FOR_LOCK.total_seconds())
    try:
        lock.acquire()
    except Timeout:
        return Report(trouble="ein Lauf blockiert seit über zehn Minuten")

    run_id: int | None = None
    found: list[Observation] = []
    stolperer: list[str] = []

    try:
        run_id = store.start_run(settings.slug, ENTRY_TRIGGER, now, pid=os.getpid())
        context = RunContext(
            profile_slug=settings.slug,
            store=store,
            now=now,
            # Wie im Rundgang: ein Titel in der Originalsprache findet die
            # uebersetzte Ausgabe ueber die DNB (#77). Mit demselben Budget —
            # der enge Lauf fragt ohnehin hoechstens die Karten eines Titels.
            original_titles=OriginalTitles(
                store, Dnb(client=client), budget=settings.dnb_budget, now=now
            ),
        )
        for source in enabled:
            try:
                found.extend(source.watch([entry], context))
            except Exception as exc:  # noqa: BLE001 - eine Quelle, nicht der Lauf
                # Eine stolpernde Quelle haelt die andere nicht auf — dieselbe
                # Regel wie im grossen Lauf (ADR 7). Vorher brach der ganze
                # enge Lauf ab, und eine hakende Onleihe verhinderte den
                # Shop-Preis.
                stolperer.append(f"{source.name}: {type(exc).__name__}")
        store.append(run_id, settings.slug, found, now)
        # Erst die Geschichte, dann das Beiwerk — dieselbe Reihenfolge wie im
        # Rundgang. Vorher holte der enge Lauf gar kein Bild, und ein Buch, das
        # ueber "Jetzt pruefen" hereinkam, stand bis zum naechsten Rundgang
        # ohne Titelbild da.
        fetch_for_books(store, client, found)
        # Und die Bilder der Ausgaben, zwischen denen die Leserin gleich
        # waehlen soll: die Frage kann dieser Lauf selbst aufgeworfen haben,
        # und ohne Bilder stand sie bis zum naechsten Rundgang als Reihe
        # gezeichneter Ruecken da (Ticket 41).
        fetch_for_candidates(store, settings.slug, client)
        return Report(observations=tuple(found), trouble="; ".join(stolperer))
    finally:
        # **Immer**, auch auf jedem Fehlerweg. Eine Zeile ohne Ende sieht fuer
        # `runs.py` aus wie ein laufender Lauf — und weil ihre Prozessnummer
        # die des Webservers ist, lebt der Prozess. Das Panel haette danach
        # fuer immer "Lauf laeuft …" gemeldet und den Knopf gesperrt.
        if run_id is not None:
            store.finish_run(
                run_id,
                status="ok" if not stolperer else "failed",
                delta_count=len(found),
                finished_at=datetime.now(),
            )
        lock.release()
