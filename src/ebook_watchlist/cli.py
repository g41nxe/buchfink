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


def _export(argv: Sequence[str]) -> int:
    """``ebw export [DATEI]`` — Einstellungen, Interessen, Watchlist, Besitz als YAML (#104)."""
    import yaml

    from . import paths, transfer
    from .config import load_settings
    from .store import Store

    data = transfer.export(Store(paths.db_path()), load_settings())
    text = "# Buchfink-Export — `ebw import DATEI` spielt ihn ein (#104).\n" + yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False
    )
    if argv and argv[0] != "-":
        Path(argv[0]).write_text(text, encoding="utf-8")
        print(f"geschrieben: {argv[0]}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def _import(argv: Sequence[str]) -> int:
    """``ebw import DATEI`` — einen Export einspielen; nichts doppelt (#104)."""
    from datetime import datetime

    import yaml

    from . import paths, transfer
    from .config import load_settings
    from .store import Store

    if not argv:
        print("ebw import DATEI", file=sys.stderr)
        return 2
    data = yaml.safe_load(Path(argv[0]).read_text(encoding="utf-8"))
    try:
        report = transfer.import_(Store(paths.db_path()), load_settings(), data,
                                  now=datetime.now())
    except transfer.ImportError_ as exc:
        print(f"nicht eingespielt: {exc}", file=sys.stderr)
        return 2
    print(f"  {report.books:>4}  Bücher neu angelegt")
    print(f"  {report.relations:>4}  Beziehungen")
    print(f"  {report.interests:>4}  Interessen")
    return 0


COMMANDS: dict[str, Callable[[Sequence[str]], int]] = {
    "serve": _serve,
    "web": _web,
    "worker": _worker,
    "export": _export,
    "import": _import,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in COMMANDS:
        return COMMANDS[args[0]](args[1:])
    return run_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
