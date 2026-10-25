"""Der Befehl ``ebw`` (#103, ADR 40).

Drei Wörter starten Prozesse, die bleiben: ``serve`` (Oberfläche und
Hintergrunddienst zusammen), ``web`` und ``worker`` (je einzeln, für Docker
oder zwei systemd-Dienste). Alles andere ist der Lauf mit seinen
Unterbefehlen, wie bisher (``ebw run``, ``ebw doctor``, ``ebw judge`` …).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from .run import main as run_main


def _web(argv: Sequence[str]) -> int:
    from .web.__main__ import main

    return main(list(argv))


def _worker(argv: Sequence[str]) -> int:
    from .jobs import worker_main

    return worker_main(list(argv))


def _serve(argv: Sequence[str]) -> int:
    """Oberfläche und Dienst, gestartet und beendet als eins.

    Zwei Prozesse, nicht zwei Fäden: so bleibt die Oberfläche frei von Arbeit
    (ADR 3), und der Dienst schreibt in ``data/worker.log``, statt die Ausgabe
    der Oberfläche zu durchmischen. Endet die Oberfläche, endet der Dienst.
    Ein Lauf, den er gerade begleitet, ist ein eigener Prozess und läuft zu
    Ende.
    """
    from . import paths
    from .web.__main__ import _safe_output

    data_dir = _data_dir(argv)
    if data_dir is not None:
        os.environ["EBW_DATA_DIR"] = str(data_dir)
    # Unter `pythonw.exe` (Autostart ohne Konsole) gibt es kein stderr; schon
    # die Zeile unten beendete sonst den Prozess (docs/betrieb.md).
    _safe_output()
    log = paths.data_dir() / "worker.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    extra: dict = {}
    if sys.platform == "win32":  # pragma: no cover - the other branch on Linux
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW
    with log.open("ab") as sink:
        worker = subprocess.Popen(  # noqa: S603 - fixed argv, no user input
            [sys.executable, "-m", "ebook_watchlist", "worker"],
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=subprocess.STDOUT,
            env=dict(os.environ, EBW_DATA_DIR=str(paths.data_dir())),
            **extra,
        )
    print(f"worker: pid {worker.pid}, Ausgabe in {log}", file=sys.stderr)
    try:
        return _web(argv)
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()


def _data_dir(argv: Sequence[str]) -> Path | None:
    for index, word in enumerate(argv):
        if word == "--data-dir" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if word.startswith("--data-dir="):
            return Path(word.split("=", 1)[1])
    return None


COMMANDS: dict[str, Callable[[Sequence[str]], int]] = {
    "serve": _serve,
    "web": _web,
    "worker": _worker,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in COMMANDS:
        return COMMANDS[args[0]](args[1:])
    return run_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
