"""Die Warteschlange und ihr Hintergrunddienst (ADR 40, #99).

Alle Arbeit außerhalb einer Anfrage ist ein **Auftrag** in einer Huey-Schlange:
der Lauf, der enge Lauf, der Steckbrief, das Erkennen in der Erstaufnahme. Die
Oberfläche stellt ein und liest den Stand; der **Hintergrunddienst** (`ebw
worker`) arbeitet ab. Im Webprozess läuft keine Arbeit mehr.

Die Schlange liegt in ``data/jobs.db``, nicht in der Hauptdatenbank: sie soll
nicht um deren Sperren konkurrieren. Gebaut wird sie erst bei Bedarf, je
Datenverzeichnis — `SqliteHuey` legt seine Datei schon beim Anlegen an, und
ein Import darf in kein Datenverzeichnis schreiben.

Was die Oberfläche zeigt, steht in Hueys Schlüsselablage (`put`/`get`), nicht in
seinen Ergebnissen; der Stand eines Laufs kommt ohnehin aus dem Laufjournal.

In Tests (``EBW_JOBS_INLINE``) arbeitet nach jedem Einstellen ein Faden genau
diesen einen Auftrag ab — durch dieselbe Schlange, mit derselben Serialisierung,
nur ohne eigenen Prozess.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
from collections.abc import Hashable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout
from huey import SqliteHuey, crontab
from huey.api import TaskWrapper

from . import paths
from .store import RunRow, Store

#: Gesetzt, arbeitet ein Faden jeden Auftrag gleich nach dem Einstellen ab.
INLINE_ENV = "EBW_JOBS_INLINE"

#: Wie oft der Dienst nachsieht, ob ein Lauf fällig ist (#100). Fest: wer
#: mehr will, stellt die Kadenz um, nicht das Prüfen.
CHECK_EVERY_MINUTES = 15

#: Der Dienst meldet sich jede Minute. Ist die letzte Meldung älter, läuft er
#: nicht — dann sagt die Oberfläche das, statt still einzustellen.
SERVICE_SILENT_AFTER = timedelta(minutes=3)

#: Ein Lauf ohne Ende, der älter ist, gilt als tot — keiner dauert Stunden.
ASSUME_DEAD_AFTER = timedelta(hours=6)

#: Ein Auftrag, der so lange „läuft“, ist mit seinem Dienst untergegangen:
#: Huey stellt höchstens einmal zu. Der Knopf darf dann wieder.
JOB_LOST_AFTER = timedelta(minutes=30)

_HEARTBEAT = "service:heartbeat"

_guard = threading.Lock()
_queues: dict[Path, tuple[SqliteHuey, dict[str, TaskWrapper]]] = {}

log = logging.getLogger("ebook_watchlist.jobs")


def _inline() -> bool:
    return bool(os.environ.get(INLINE_ENV))


def _queue_path() -> Path:
    """``data/jobs.db`` — im Testbetrieb ohne eigenes Datenverzeichnis ein
    Ordner je Prozess: sonst holte ein laufender Dienst die Aufträge der Tests
    ab, mit echten Quellen."""
    if _inline() and not os.environ.get("EBW_DATA_DIR"):
        return Path(tempfile.gettempdir()) / f"buchfink-test-jobs-{os.getpid()}" / "jobs.db"
    return paths.data_dir() / "jobs.db"


def _queue() -> tuple[SqliteHuey, dict[str, TaskWrapper]]:
    path = _queue_path()
    with _guard:
        built = _queues.get(path)
        if built is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            # `utc=False`: die Zeitpläne lesen sich in der Ortszeit, wie das
            # Laufjournal. `results=False`: niemand fragt Rückgabewerte ab.
            huey = SqliteHuey(name="buchfink", filename=str(path), utc=False, results=False)
            tasks = {
                "job": huey.task(name="job")(_job),
                "run": huey.task(name="run")(_run),
            }
            huey.periodic_task(crontab(minute=f"*/{CHECK_EVERY_MINUTES}"), name="catch_up")(
                catch_up
            )
            huey.periodic_task(crontab(), name="heartbeat")(heartbeat)
            built = _queues[path] = (huey, tasks)
    return built


def queue() -> SqliteHuey:
    """Die Schlange dieses Datenverzeichnisses."""
    return _queue()[0]


def put(key: str, value: Any) -> None:
    queue().put(key, value)


def get(key: str) -> Any:
    return queue().get(key, peek=True)


def forget(key: str) -> None:
    queue().delete(key)


def enqueue(task: str, *args: Any) -> None:
    """Einen Auftrag einstellen. Im Testbetrieb arbeitet ihn sofort ein Faden ab."""
    huey, tasks = _queue()
    tasks[task](*args)
    if _inline():
        threading.Thread(target=_work_one, args=(huey,), daemon=True).start()


def _work_one(huey: SqliteHuey) -> None:
    task = huey.dequeue()
    if task is not None:
        huey.execute(task)


# --- der Dienst lebt -----------------------------------------------------------


def heartbeat(now: datetime | None = None) -> None:
    """Der Dienst meldet sich. Jede Minute, und einmal beim Start."""
    put(_HEARTBEAT, now or datetime.now())


def service_alive(now: datetime | None = None) -> bool:
    """Arbeitet gerade ein Dienst diese Schlange ab?"""
    if _inline():
        return True
    seen = get(_HEARTBEAT)
    return isinstance(seen, datetime) and (now or datetime.now()) - seen < SERVICE_SILENT_AFTER


# --- Aufträge mit Stand ----------------------------------------------------------


def _state_key(kind: str, key: Hashable) -> str:
    return f"job:{kind}:{key!r}"


def job_started(kind: str, key: Hashable, at: datetime) -> None:
    """``at`` ist, was die Zeile anzeigt; ``queued`` die echte Uhrzeit, an der
    gemessen wird, ob der Auftrag verloren ist."""
    put(_state_key(kind, key),
        {"started_at": at, "queued": datetime.now(), "finished_at": None, "trouble": ""})


def job_lost(state: dict, now: datetime | None = None) -> bool:
    """Liegt der Auftrag so lange, dass sein Dienst mit ihm untergegangen ist?"""
    queued = state.get("queued") or state["started_at"]
    return state["finished_at"] is None and (now or datetime.now()) - queued > JOB_LOST_AFTER


def job_state(kind: str, key: Hashable) -> dict | None:
    return get(_state_key(kind, key))


def _job(kind: str, key: Hashable, options: dict) -> None:
    """Einen Auftrag mit Stand abarbeiten: enger Lauf, Steckbrief, Erkennen.

    Was getan wird, steht in `web.work.WORK` — dort, wo es die Oberfläche
    braucht, aber außerhalb des Webprozesses aufrufbar.
    """
    from .web import work

    # Die Schlange gleich festhalten: der Stand gehört dorthin, wo der Auftrag
    # herkam, auch wenn die Arbeit lange dauert.
    huey = queue()
    try:
        report = work.WORK[kind](key, **options)
        trouble = report.trouble
    except Exception as exc:  # noqa: BLE001 - ein Auftrag darf den Dienst nicht mitreißen
        trouble = f"{type(exc).__name__}: {exc}"
    state = huey.get(_state_key(kind, key), peek=True) or {"started_at": datetime.now()}
    huey.put(_state_key(kind, key), {**state, "finished_at": datetime.now(), "trouble": trouble})


def _run(only_watchlist: bool, trigger: str) -> None:
    from .web import runs

    runs.execute(only_watchlist=only_watchlist, trigger=trigger)


# --- Nachholen statt Termin --------------------------------------------------------


def _counts(run: RunRow) -> bool:
    return run.finished_at is not None and run.status != "abandoned"


def run_is_due(store: Store, profile_slug: str, *, hours: float, now: datetime) -> bool:
    """Ist der letzte *fertige* Lauf älter als die Kadenz? (ADR 40)

    Gezählt wird ab seinem Beginn, sonst wanderte der tägliche Lauf jeden Tag
    um seine eigene Dauer nach hinten. Ein abgebrochener Lauf zählt nicht —
    er ist beim nächsten Prüfen wieder fällig. Ein Lauf, der gerade läuft,
    macht keinen zweiten fällig. Enge Läufe zählen nicht (`recent_runs`).
    """
    recent = store.recent_runs(profile_slug, limit=20)
    if any(
        run.finished_at is None and run.status == "running"
        and now - run.started_at < ASSUME_DEAD_AFTER
        for run in recent
    ):
        return False
    last = next((run for run in recent if _counts(run)), None)
    return last is None or now - last.started_at >= timedelta(hours=hours)


def tidy() -> None:
    """Verwaiste Zeilen im Journal als abgebrochen kennzeichnen — wenn kein Lauf lebt.

    Ob einer lebt, sagt die Lauf-Sperre: ist sie frei, hält sie kein Prozess.
    Der Dienst darf sie dafür einen Augenblick nehmen, die Oberfläche nie.
    """
    from .config import ConfigError, load_settings

    try:
        settings = load_settings()
    except ConfigError:
        return
    lock = FileLock(str(paths.lock_path()), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        return
    try:
        if count := Store(paths.db_path()).abandon_unfinished(settings.slug):
            log.info("%d verwaiste Läufe als abgebrochen gekennzeichnet", count)
    finally:
        lock.release()


def catch_up(now: datetime | None = None) -> None:
    """Alle 15 Minuten: ist ein Lauf fällig, wird er eingestellt."""
    from .config import ConfigError, load_settings
    from .web.runs import RunLauncher

    try:
        settings = load_settings()
    except ConfigError as exc:
        log.warning("Einstellungen unlesbar, kein Lauf: %s", exc)
        return
    tidy()
    store = Store(paths.db_path())
    if run_is_due(store, settings.slug, hours=settings.run_every_hours, now=now or datetime.now()):
        RunLauncher().start(store, settings.slug, trigger="cron")


# --- `ebw worker` -------------------------------------------------------------------


#: Ein großer Lauf belegt einen Faden für Minuten; daneben sollen enge Läufe,
#: Steckbriefe und mehrere Erkennungen der Erstaufnahme weiterlaufen.
WORKERS = 4


def worker_main(argv: list[str] | None = None) -> int:
    """Der Hintergrunddienst: arbeitet die Schlange ab und holt nach.

    Thread-Worker, auch unter Linux: Prozess-Worker bräuchten `SIGALRM`, das es
    unter Windows nicht gibt, und eine Betriebsart reicht.
    """
    import argparse

    from .console import survive_a_narrow_console

    parser = argparse.ArgumentParser(prog="ebw worker", description="Der Hintergrunddienst.")
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.data_dir is not None:
        os.environ["EBW_DATA_DIR"] = str(args.data_dir)
    os.environ.pop(INLINE_ENV, None)

    survive_a_narrow_console()
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s: %(message)s"
    )
    print(f"data:   {paths.data_dir()}", file=sys.stderr)
    print(f"queue:  {paths.data_dir() / 'jobs.db'}", file=sys.stderr)
    heartbeat()
    tidy()
    consumer = queue().create_consumer(
        workers=WORKERS, worker_type="thread", periodic=True,
        # Höchstens eine Sekunde, bis ein Auftrag aufgenommen wird: der enge
        # Lauf dauert gemessen zwei, und Hueys Voreinstellung wartet bis zu zehn.
        max_delay=1.0,
    )
    consumer.run()
    return 0


__all__ = [
    "ASSUME_DEAD_AFTER", "CHECK_EVERY_MINUTES", "INLINE_ENV", "catch_up", "enqueue",
    "forget", "get", "heartbeat", "job_started", "job_state", "put", "queue", "run_is_due",
    "service_alive", "tidy", "worker_main",
]
