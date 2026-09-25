"""``python -m ebook_watchlist.web`` — start the local web application.

Separate from the Run entrypoint on purpose (ADR 3): the web process reads and
displays, the Run scrapes. Neither can disturb the other.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from .. import paths

#: Bound to every interface so the page is reachable from a phone on the same
#: network. There is no authentication (ADR 3), so keep it off the open
#: internet — pass --host 127.0.0.1 to restrict it to this machine.
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - deliberate, see above
DEFAULT_PORT = 8437


def _safe_output() -> None:
    """Eine Ausgabe, auf die sich schreiben laesst — notfalls eine Datei.

    Im Autostart laeuft die Oberflaeche unter ``pythonw.exe``, damit kein
    Konsolenfenster stehenbleibt, das man versehentlich zuklickt. Dann gibt es
    keine gueltigen Ausgabe-Handles: ``sys.stderr`` ist entweder ``None`` oder
    zeigt ins Leere, und schon die zwei Startzeilen unten beenden den Prozess
    mit Rueckgabewert 1 — ohne eine Spur, weil die Fehlermeldung denselben Weg
    nimmt. Gemessen, nicht vermutet: mit Umleitung laeuft derselbe Aufruf.

    Statt dessen schreibt die Oberflaeche dann nach ``data/web.log``, neben die
    uebrigen Aufzeichnungen. Das gilt auch fuer uvicorn: seine Protokollierung
    greift ``sys.stderr`` erst in ``uvicorn.run()`` ab, also nach hier.
    """
    try:
        sys.stderr.write("")
        sys.stderr.flush()
    except (AttributeError, OSError, ValueError):
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        target = (paths.data_dir() / "web.log").open("a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ebw-web", description="Serve the local Buchfink dashboard."
    )
    parser.add_argument("--host", default=os.environ.get("EBW_WEB_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("EBW_WEB_PORT", DEFAULT_PORT))
    )
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--reload", action="store_true", help="restart on code changes")
    args = parser.parse_args(argv)

    if args.data_dir is not None:
        os.environ["EBW_DATA_DIR"] = str(args.data_dir)

    _safe_output()
    print(f"data:  {paths.data_dir()}", file=sys.stderr)
    print(f"serve: http://{args.host}:{args.port}/", file=sys.stderr)
    uvicorn.run(
        "ebook_watchlist.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
