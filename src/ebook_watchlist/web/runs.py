"""Starting a Run from the Dashboard, and saying what became of it (Ticket 10).

The Run does not happen in the web process (ADR 3). This module spawns
``python -m ebook_watchlist.run --trigger ui`` as a detached child and then
answers one question for the page: *what is that Run doing right now?*

Three things make that question harder than it looks, and each is answered by a
different piece of evidence:

- **Is a Run already going?** The file lock is the only authority, and only Run
  processes ever touch it (the web process must never hold it). So we do not
  ask: we start the child and let it bounce off the lock itself, which it does
  by exiting 0 without writing a run row. That is race-free by construction.
- **Did the Run get off the ground at all?** Bad settings make the Run exit
  before it writes anything to the journal. The journal therefore cannot report
  it; the child's own exit code and output can, so a launch is remembered until
  a run row supersedes it.
- **Is a Run that never finished still alive?** An unfinished row looks the
  same whether the Run is working or was killed. The Run signs its row with its
  pid, so the answer is whether that process still exists.

The remembered launch lives in this process and nowhere else. Restarting the
web app forgets it and falls back to the journal — which is correct: the Run is
a separate process and carries on regardless (ADR 3).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .. import paths
from ..store import RunRow, Store

#: A Run this old that still has not finished is treated as gone, whatever its
#: pid says. Two reasons: rows written before pids were recorded have none, and
#: an operating system reuses pids, so a very old row can point at an unrelated
#: process that happens to be alive. No Run of this tool takes hours.
ASSUME_DEAD_AFTER = timedelta(hours=6)

#: The child's console output. The Digest itself is written as HTML by the Run;
#: this is here so a Run that fell over before that has left something to read.
LOG_NAME = "run-ui.log"

#: How much of that output to put on the page. Enough for a traceback's point,
#: not so much that the Dashboard becomes a log viewer.
LOG_TAIL_BYTES = 2000


def _alive(pid: int) -> bool:
    """Does a process with this id exist?

    Deliberately no ``psutil``: one cross-platform question does not justify a
    dependency (ADR 12), and both platforms answer it in a few lines.
    """
    if sys.platform == "win32":  # pragma: no cover - the other branch on Linux
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)  # signal 0 checks for existence without delivering one
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # somebody else's process, but it is there
    return True


def _alive_windows(pid: int) -> bool:  # pragma: no cover - platform-specific
    import ctypes

    query_limited_information = 0x1000
    still_active = 259

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


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
        return self.kind in {"failed", "abandoned"}

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


@dataclass(slots=True)
class _Launch:
    """A child we started and have not yet seen appear in the journal."""

    process: subprocess.Popen
    at: datetime
    #: A verdict worth repeating on every poll and page load until something
    #: better comes along. Only failure is kept: it is the end of that Run's
    #: story and nothing else records it, so forgetting it after one poll would
    #: make a failed click look like a click that did nothing.
    outcome: RunState | None = None


class RunLauncher:
    """Owns the "Run now" button's side of things.

    One per application instance rather than a module-level global, so that the
    state of one test's launcher cannot leak into the next.
    """

    def __init__(self) -> None:
        self._launch: _Launch | None = None

    # -- starting ----------------------------------------------------------

    def start(self, store: Store, profile_slug: str) -> RunState:
        """Start a Run, unless one is already going.

        The check below is for the *message*, not for correctness: between
        asking and spawning, a cron Run could take the lock. That is harmless —
        the child bounces off the lock and reports it — so this is allowed to
        be a fraction of a second out of date.
        """
        state = self.state(store, profile_slug)
        if state.busy:
            return state
        self._launch = _Launch(process=self._spawn(), at=datetime.now())
        return self.state(store, profile_slug)

    def _spawn(self) -> subprocess.Popen:
        log = _log_path()
        log.parent.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, EBW_DATA_DIR=str(paths.data_dir()))
        # Eigene Prozessgruppe, und die Ausgabe geht in eine Datei statt in
        # unsere Leitungen: eine Leitung, die niemand liest, laeuft voll und
        # haelt den Lauf an, und ein Kind in unserer Gruppe ginge mit der
        # Oberflaeche unter, sobald jemand dort Strg-C drueckt.
        #
        # ``CREATE_NO_WINDOW`` statt ``DETACHED_PROCESS``: abgekoppelt bekommt
        # ein Konsolenprogramm unter Windows sein *eigenes* Fenster, und das
        # sprang bei jedem Lauf auf dem Schreibtisch auf. Losgeloest genug ist
        # der Lauf schon durch die eigene Prozessgruppe.
        if sys.platform == "win32":  # pragma: no cover - the other branch on Linux
            extra = {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            }
        else:
            extra = {"start_new_session": True}
        with log.open("wb") as sink:
            return subprocess.Popen(  # noqa: S603 - fixed argv, no user input
                # ``--trigger ui`` ist hier nicht nur eine Notiz fuer das
                # Journal: der Mindestabstand zwischen zwei Rundgaengen
                # (``run.MIN_RUN_GAP``) gilt nur ``cron``. Hier hat ein Mensch
                # gedrueckt, und der meint es.
                [sys.executable, "-m", "ebook_watchlist.run", "--trigger", "ui"],
                stdin=subprocess.DEVNULL,
                stdout=sink,
                stderr=subprocess.STDOUT,
                env=environment,
                **extra,
            )

    # -- reporting ---------------------------------------------------------

    def state(self, store: Store, profile_slug: str) -> RunState:
        latest = store.latest_run(profile_slug)
        pending = self._pending(latest)
        if pending is not None:
            return pending
        return _from_journal(latest)

    def _pending(self, latest: RunRow | None) -> RunState | None:
        """What our own child is doing, while the journal cannot say yet.

        Returns ``None`` once a run row exists that this launch produced — from
        then on the journal is the better witness and the launch is forgotten.
        """
        launch = self._launch
        if launch is None:
            return None
        if latest is not None and latest.started_at >= launch.at:
            self._launch = None
            return None
        if launch.outcome is not None:
            return launch.outcome

        code = launch.process.poll()
        if code is None:
            return RunState("starting", "Lauf wird gestartet …")

        if code == 0:
            # Exited cleanly without ever writing a run row: the only way that
            # happens is bouncing off the lock (run.EXIT_ALREADY_RUNNING).
            #
            # Not remembered, unlike a failure: the Run that is holding the
            # lock has a row of its own, and from the next poll on that row is
            # the better witness — it can also say when the thing finishes.
            self._launch = None
            return RunState(
                "already-running",
                "Es läuft bereits ein Lauf",
                "Angestoßen von cron oder der Kommandozeile. Dieser Knopf hat "
                "keinen zweiten gestartet.",
            )
        launch.outcome = RunState(
            "failed",
            "Der Lauf ist gar nicht erst angelaufen",
            _log_tail() or f"Der Prozess endete mit Rückgabecode {code}.",
        )
        return launch.outcome


def _from_journal(latest: RunRow | None) -> RunState:
    if latest is None:
        return RunState("idle", "Noch kein Lauf")

    if latest.finished_at is None:
        if _still_working(latest):
            return RunState("running", "Lauf läuft …", run=latest)
        # Started, never wrote an ending, and its process is gone. Saying
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
        detail = f"{changes} Änderung(en)" if changes else "Nichts hat sich geändert."
        return RunState("done", "Lauf abgeschlossen", detail, run=latest)
    return RunState("failed", "Lauf mit Fehlern beendet", latest.error, run=latest)


def journal_status(runs: list[RunRow]) -> dict[int, str]:
    """How each Run reads in the journal list, keyed by run id.

    The stored ``status`` of an unfinished Run is "running" and stays that way
    for good, because the process that would have corrected it is gone. The
    list would otherwise show a Run killed weeks ago as still going.
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
    at = now or datetime.now()
    if at - run.started_at > ASSUME_DEAD_AFTER:
        return False
    if run.pid is None:
        # Written before Runs signed their rows; age is all we have.
        return True
    return _alive(run.pid)


__all__ = ["ASSUME_DEAD_AFTER", "LOG_NAME", "RunLauncher", "RunState", "journal_status"]
