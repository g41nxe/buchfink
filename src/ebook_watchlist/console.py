"""Die Ausgabe auf der Konsole, für jeden Einstieg gleich (#106)."""

from __future__ import annotations

import sys


def survive_a_narrow_console() -> None:
    """Never lose a whole Run's Digest to a console that cannot render an arrow.

    Windows still hands us a cp1252 stdout, which raises on "→" and on the
    warning sign in the error heading. UTF-8, not just ``replace``: into a pipe,
    a log or Docker cp1252 turned the stars into ``?????`` and the umlauts into
    bytes nobody reading UTF-8 could decode (#106). A real console window renders
    either way.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - stream not reconfigurable
            pass
