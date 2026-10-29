"""Starting a Run from the Dashboard, and saying what became of it (Ticket 10).

The Run does not happen in the web process (ADR 3). Since ADR 40 the button
puts a job into the queue (`jobs`), and the background service starts
``python -m ebook_watchlist.run`` as a child of its own and waits for it. This
module answers one question for the page: *what is that Run doing right now?*

Three pieces of evidence, each for a different part of the answer:

- **Is a Run already going?** The file lock is the only authority, and only Run
  processes ever touch it (the web process must never hold it). The child
  bounces off it by exiting 0 without writing a run row.
- **Did the Run get off the ground at all?** Bad settings make the Run exit
  before it writes anything to the journal. The service remembers the
  *launch* in the queue's key store, and what became of it if the journal
  cannot tell.
- **Is a Run that never finished still alive?** Whoever holds the lock marks
  older unfinished rows as abandoned (`Store.abandon_unfinished`); the service
  does it when it starts and every time it checks for a due Run. Until then,
  an unfinished row younger than :data:`ASSUME_DEAD_AFTER` is taken to be
  running. The pid this used to rest on did not reach across containers.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .. import jobs, paths
from ..jobs import ASSUME_DEAD_AFTER
from ..store import RunRow, Store

#: The child's console output. The Digest itself is written as HTML by the Run;
#: this is here so a Run that fell over before that has left something to read.
LOG_NAME = "run-ui.log"

#: How much of that output to put on the page. Enough for a traceback's point,
#: not so much that the Dashboard becomes a log viewer.
LOG_TAIL_BYTES = 2000

#: Where the launch is remembered, between the button and the journal.
LAUNCH_KEY = "run:launch"

#: A launch the journal never confirmed, older than this, was lost with its
#: service (Huey delivers at most once). The button may then offer itself again.
LAUNCH_LOST_AFTER = timedelta(minutes=10)

#: So lange darf ein Lauf brauchen, bis er seine Zeile ins Journal schreibt.
#: Ein gesunder braucht Sekunden; am 29.10.2026 stand einer fünf Stunden beim
#: Laden von ``_ssl``, bevor er überhaupt etwas tat. Danach wartet der Dienst
#: ohne Frist: ein Lauf darf eine halbe Stunde brauchen.
START_DEADLINE = timedelta(minutes=3)

#: Wie oft der Dienst bis dahin nachsieht.
START_POLL_SECONDS = 1.0

NO_SERVICE_DETAIL = (
    "Der Hintergrunddienst läuft nicht — Läufe, enge Läufe und Steckbriefe "
    "bleiben liegen. Starten mit `ebw serve` (Oberfläche und Dienst) oder "
    "`ebw worker`."
)


@dataclass(frozen=True, slots=True)
class RunState:
    """What the "Run now" panel says, and whether it keeps asking.

    ``kind`` drives the wording and the colour; ``busy`` drives both the button
    and the polling, so a page can never keep polling something it is also
    telling the reader has stopped.
    """

    kind: str
    headline: str
    detail: str | None = None
    run: RunRow | None = None
    #: The technical text — exception, traceback, log tail — for whoever
    #: reports the problem. The panel keeps it folded away; ``detail`` is the
    #: German sentence a reader sees (#118).
    trace: str | None = None

    @property
    def busy(self) -> bool:
        """A Run is in progress — keep polling, and do not offer to start one.

        ``already-running`` belongs here: the Run is somebody else's (cron, the
        CLI), but it is a Run, and the next poll will pick it up out of the
        journal and follow it to its end.
        """
        return self.kind in {"starting", "running", "already-running"}

    @property
    def trouble(self) -> bool:
        return self.kind in {"failed", "abandoned", "no-service"}

    @property
    def started_label(self) -> str | None:
        """Dasselbe Format wie in der Lauf-Liste und bei den Quellen.

        Vorher standen auf einer Seite drei: hier mit Jahr und Sekunden, in
        der Liste ohne beides, bei den Tagesberichten wieder anders. Sekunden
        beantworten keine Frage, die jemand an einen taeglichen Lauf hat.
        """
        if self.run is None:
            return None
        return self.run.started_at.strftime("%d.%m. %H:%M")


def _log_path() -> Path:
    return paths.data_dir() / LOG_NAME


def _log_tail() -> str | None:
    path = _log_path()
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - LOG_TAIL_BYTES))
        text = handle.read().decode("utf-8", errors="replace").strip()
    return text or None


@dataclass(frozen=True, slots=True)
class Launch:
    """A Run the button asked for and the journal has not shown yet."""

    at: datetime
    only_watchlist: bool = False
    trigger: str = "ui"
    #: A verdict worth repeating on every poll and page load until something
    #: better comes along. Only failure is kept for good: it is the end of that
    #: Run's story and nothing else records it.
    outcome: RunState | None = None


def _no_service() -> RunState:
    return RunState("no-service", "Kein Hintergrunddienst", NO_SERVICE_DETAIL)


class RunLauncher:
    """Owns the "Run now" button's side of things.

    Holds no state of its own any more: the launch lives in the queue's key
    store, where the service can answer it (ADR 40).
    """

    # -- starting ----------------------------------------------------------

    def start(
        self,
        store: Store,
        profile_slug: str,
        *,
        only_watchlist: bool = False,
        trigger: str = "ui",
    ) -> RunState:
        """Start a Run, unless one is already going.

        ``only_watchlist``: die Übersicht bietet neben dem vollen Lauf einen
        zweiten Knopf an, der nur prüft, was auf der Watchlist steht — ohne
        nach Autor:innen, Themen oder Bibliothekslisten zu fegen (``ebw run
        --watchlist``). Derselbe Prozess, dieselbe Dateisperre.

        ``trigger``: ``ui`` für den Knopf, ``cron`` für das Nachholen des
        Dienstes — der Lauf achtet dann selbst noch einmal auf die Kadenz.

        Ohne laufenden Dienst wird nichts eingestellt: ein Knopf, der still in
        eine Schlange legt, die niemand abarbeitet, wäre kaputt.
        """
        state = self.state(store, profile_slug)
        if state.busy:
            return state
        if not jobs.service_alive():
            return _no_service()
        jobs.put(LAUNCH_KEY, Launch(datetime.now(), only_watchlist, trigger))
        jobs.enqueue("run", only_watchlist, trigger)
        return self.state(store, profile_slug)

    # -- reporting ---------------------------------------------------------

    def state(self, store: Store, profile_slug: str) -> RunState:
        latest = store.latest_run(profile_slug)
        pending = _pending(latest)
        if pending is not None:
            return pending
        return _from_journal(latest)


def _pending(latest: RunRow | None, now: datetime | None = None) -> RunState | None:
    """What the requested Run is doing, while the journal cannot say yet.

    Returns ``None`` once a run row exists that this launch produced — from
    then on the journal is the better witness and the launch is forgotten.
    """
    launch = jobs.get(LAUNCH_KEY)
    if not isinstance(launch, Launch):
        return None
    if latest is not None and latest.started_at >= launch.at:
        jobs.forget(LAUNCH_KEY)
        return None
    if launch.outcome is not None:
        if launch.outcome.kind == "already-running":
            # Not remembered, unlike a failure: the Run that is holding the
            # lock has a row of its own, and from the next poll on that row
            # is the better witness.
            jobs.forget(LAUNCH_KEY)
        return launch.outcome
    if (now or datetime.now()) - launch.at > LAUNCH_LOST_AFTER:
        jobs.forget(LAUNCH_KEY)
        return None
    if not jobs.service_alive():
        return _no_service()
    return RunState("starting", "Lauf wird gestartet …")


def execute(*, only_watchlist: bool, trigger: str) -> None:
    """The service's half: start the Run as a process of its own and wait.

    A process, not a call: the Run owns its console output, the lock and its
    exit code, and a crash in it cannot take the service down.

    Queue, database and profile are fixed before the wait: the Run takes
    minutes, and what the data directory is must not change underneath.
    """
    from ..config import ConfigError, load_settings

    queue, db = jobs.queue(), paths.db_path()
    try:
        slug: str | None = load_settings().slug
    except ConfigError:
        slug = None
    launch = queue.get(LAUNCH_KEY, peek=True)
    at = launch.at if isinstance(launch, Launch) else datetime.now()

    def journaled() -> bool:
        latest = Store(db).latest_run(slug) if slug else None
        return latest is not None and latest.started_at >= at

    process = _spawn(only_watchlist=only_watchlist, trigger=trigger)
    code = _await_start(process, journaled if slug else None)

    if journaled():
        return  # the journal tells the rest
    if code is None:
        outcome = RunState(
            "failed",
            "Der Lauf hing beim Start",
            f"Er hat sich nach {START_DEADLINE.seconds // 60} Minuten noch nicht "
            "gemeldet und wurde beendet. Einfach noch einmal starten.",
            trace=_log_tail() or None,
        )
    elif code == 0:
        # Exited cleanly without ever writing a run row: bouncing off the lock
        # (run.EXIT_ALREADY_RUNNING), or the cadence said not yet.
        outcome = RunState(
            "already-running",
            "Es läuft bereits ein Lauf",
            "Angestoßen von cron oder der Kommandozeile. Dieser Knopf hat "
            "keinen zweiten gestartet.",
        )
    else:
        outcome = RunState(
            "failed",
            "Der Lauf ist gar nicht erst angelaufen",
            "Buchfink konnte den Lauf nicht starten.",
            trace=_log_tail() or f"Der Prozess endete mit Rückgabecode {code}.",
        )
    if isinstance(launch, Launch):
        queue.put(LAUNCH_KEY, replace(launch, outcome=outcome))


def _await_start(process: subprocess.Popen, journaled) -> int | None:
    """Der Rückgabecode des Laufs — oder ``None``, wenn er beim Start hing
    und beendet wurde.

    Bis zur Frist sieht der Dienst nach, ob der Lauf seine Zeile geschrieben
    hat; danach wartet er ohne Frist. Ohne Profil (``journaled`` ist ``None``)
    lässt sich das nicht sehen, und es wird nur gewartet.
    """
    if journaled is None:
        return process.wait()
    deadline = datetime.now() + START_DEADLINE
    while datetime.now() < deadline:
        try:
            return process.wait(timeout=START_POLL_SECONDS)
        except subprocess.TimeoutExpired:
            if journaled():
                return process.wait()
    _end_tree(process)
    return None


def _end_tree(process: subprocess.Popen) -> None:
    """Den Lauf samt Kindern beenden.

    Unter Windows ist ``sys.executable`` im venv ein Shim, der den
    eigentlichen Python-Prozess als Kind startet: ``kill`` träfe nur den Shim,
    und der hängende Lauf bliebe als Waise (29.10.2026). ``taskkill /T``
    nimmt den Baum; anderswo die eigene Sitzung, die ``_spawn`` ihm gibt.
    """
    if sys.platform == "win32":  # pragma: no cover - the other branch on Linux
        subprocess.run(  # noqa: S603 - fixed argv
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],  # noqa: S607
            capture_output=True,
            check=False,
        )
    else:
        import signal

        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def _spawn(*, only_watchlist: bool = False, trigger: str = "ui") -> subprocess.Popen:
    log = _log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, EBW_DATA_DIR=str(paths.data_dir()))
    environment.pop(jobs.INLINE_ENV, None)
    # Eigene Prozessgruppe, und die Ausgabe geht in eine Datei statt in
    # unsere Leitungen: eine Leitung, die niemand liest, laeuft voll und
    # haelt den Lauf an, und ein Kind in unserer Gruppe ginge mit dem Dienst
    # unter, sobald jemand dort Strg-C drueckt.
    #
    # ``CREATE_NO_WINDOW`` statt ``DETACHED_PROCESS``: abgekoppelt bekommt
    # ein Konsolenprogramm unter Windows sein *eigenes* Fenster, und das
    # sprang bei jedem Lauf auf dem Schreibtisch auf. Losgeloest genug ist
    # der Lauf schon durch die eigene Prozessgruppe.
    extra: dict[str, Any]
    if sys.platform == "win32":  # pragma: no cover - the other branch on Linux
        extra = {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        }
    else:
        extra = {"start_new_session": True}
    # ``--trigger`` ist hier nicht nur eine Notiz fuer das Journal: die
    # Kadenz (``run_every_hours``) gilt nur ``cron``. Beim Knopf hat ein
    # Mensch gedrueckt, und der meint es.
    argv = [sys.executable, "-m", "ebook_watchlist.run", "--trigger", trigger]
    if only_watchlist:
        argv.append("--watchlist")
    with log.open("wb") as sink:
        return subprocess.Popen(  # noqa: S603 - fixed argv, no user input
            argv,
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=subprocess.STDOUT,
            env=environment,
            **extra,
        )


def _from_journal(latest: RunRow | None) -> RunState:
    if latest is None:
        return RunState("idle", "Noch kein Lauf")

    if latest.finished_at is None:
        if _still_working(latest):
            return RunState("running", "Lauf läuft …", run=latest)
        # Started, never wrote an ending, and nobody works on it. Saying
        # "läuft" forever would be the one answer that is certainly wrong.
        return RunState(
            "abandoned",
            "Der Lauf wurde abgebrochen",
            "Der Prozess ist beendet, ohne ein Ergebnis zu hinterlassen — "
            "vermutlich abgeschossen oder der Rechner ging aus.",
            run=latest,
        )

    if latest.status == "ok":
        changes = latest.delta_count or 0
        detail = (
            f"{changes} {'Änderung' if changes == 1 else 'Änderungen'}"
            if changes
            else "Nichts hat sich geändert."
        )
        return RunState("done", "Lauf abgeschlossen", detail, run=latest)
    return RunState(
        "failed",
        "Lauf mit Fehlern beendet",
        "Ein Schritt ist auf einen Fehler gestoßen.",
        run=latest,
        trace=latest.error,
    )


def journal_status(runs: list[RunRow]) -> dict[int, str]:
    """How each Run reads in the journal list, keyed by run id.

    The stored ``status`` of an unfinished Run is "running" until whoever holds
    the lock next marks it abandoned. Until then, its age decides.
    """
    now = datetime.now()
    lines: dict[int, str] = {}
    for run in runs:
        if run.finished_at is not None:
            lines[run.id] = run.status
        else:
            lines[run.id] = "läuft" if _still_working(run, now) else "abgebrochen"
    return lines


def _still_working(run: RunRow, now: datetime | None = None) -> bool:
    if run.status == "abandoned":
        return False
    return (now or datetime.now()) - run.started_at <= ASSUME_DEAD_AFTER


__all__ = [
    "ASSUME_DEAD_AFTER", "LOG_NAME", "Launch", "RunLauncher", "RunState", "execute",
    "journal_status",
]
