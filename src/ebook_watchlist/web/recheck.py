"""Den engen Lauf anstoßen und sagen, wo er steht (Ticket 51).

Ein Faden, kein Prozess: gemessen dauert ein enger Lauf mit bekannter Adresse
**2,1 s**, und ein eigener Prozess käme mit rund einer Sekunde Python-Hochlauf
dazu — die Hälfte der Arbeit nochmal, für einen Vorgang, dessen ganzer Zweck
die sofortige Rückmeldung ist. ``uvicorn`` läuft ohne ``workers``, Zustand im
Speicher ist damit sicher.

Nebenläufiges Schreiben ist unkritisch: ``journal_mode=WAL`` und
``busy_timeout=15000`` stehen in :class:`~ebook_watchlist.store.Store` bereits.

Nachgefragt wird über htmx, genau wie beim großen Lauf (``_run_panel.html``):
der Trigger steht nur dran, solange etwas läuft, also hört die Seite von
selbst auf zu fragen. Kein Websocket (ADR 3).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import datetime

from ..single import Report, check_one

#: Nach so langer Ruhe wird ein fertiger Zustand vergessen. Lang genug, dass
#: die Seite ihn sicher einmal abgeholt hat, kurz genug, dass die Ablage nicht
#: unbegrenzt waechst.
FORGET_AFTER_SECONDS = 300


@dataclass(frozen=True, slots=True)
class Check:
    """Wo ein Hintergrundjob gerade steht — ein enger Lauf oder ein Urteil.

    ``key`` ist, woran der Job haengt: beim engen Lauf die Buchnummer, beim
    Urteil das, was beurteilt wird (#15).
    """

    key: Hashable
    started_at: datetime
    #: ``None``, solange er laeuft.
    report: Report | None = None
    finished_at: datetime | None = None

    @property
    def busy(self) -> bool:
        return self.report is None

    @property
    def trouble(self) -> str:
        return self.report.trouble if self.report else ""

    def label(self, *, now: datetime) -> str:
        """Was in der Zeile steht.

        Zwei Zustaende, nicht einer: ein enger Lauf, der auf einen grossen
        wartet, sieht sonst aus wie einer, der schon sucht — und wartet unter
        Umstaenden Minuten.
        """
        if self.report is not None:
            return self.report.trouble or "fertig"
        # Nach den gemessenen 2,1 s ist ein enger Lauf durch. Dauert es
        # laenger, haelt ein grosser Lauf die Sperre.
        return "sucht …" if (now - self.started_at).total_seconds() < 5 else "wartet …"


class Rechecker:
    """Haelt die laufenden Hintergrundjobs — einen je Schluessel.

    Gebaut fuer den engen Lauf (Ticket 51), inzwischen auch fuer das Urteil
    (#15): welche Arbeit getan wird, kommt herein, statt fest eingebaut zu
    sein. Zwei Instanzen derselben Klasse statt zweier Klassen, die dasselbe
    tun. Ohne ``work`` ist es der enge Lauf, wie bisher.

    Eine Instanz je Anwendung und kein Modul-Global, damit der Zustand eines
    Tests nicht in den naechsten leckt — dieselbe Ueberlegung wie bei
    :class:`~ebook_watchlist.web.runs.RunLauncher`.
    """

    def __init__(self, work: Callable[[Hashable], Report] | None = None) -> None:
        self._checks: dict[Hashable, Check] = {}
        self._guard = threading.Lock()
        self._arbeit = work

    def start(self, key: Hashable, *, now: datetime | None = None) -> Check:
        """Anstossen, falls fuer diesen Schluessel nicht schon etwas laeuft."""
        now = now or datetime.now()
        with self._guard:
            self._forget_old(now)
            laufend = self._checks.get(key)
            if laufend is not None and laufend.busy:
                return laufend
            self._checks[key] = Check(key=key, started_at=now)
        threading.Thread(target=self._work, args=(key,), daemon=True).start()
        return self._checks[key]

    def state(self, key: Hashable) -> Check | None:
        """Wo dieser eine Job steht — ``None``, wenn keiner bekannt ist."""
        with self._guard:
            return self._checks.get(key)

    def _work(self, key: Hashable) -> None:
        # Erst hier nachgeschlagen, nicht beim Bauen: Tests ersetzen
        # ``check_one`` auf dem Modul, und das soll auch dann greifen.
        arbeit = self._arbeit or check_one
        try:
            report = arbeit(key)
        except Exception as exc:  # noqa: BLE001 - ein Faden darf nichts mitreissen
            report = Report(trouble=f"{type(exc).__name__}: {exc}")
        with self._guard:
            vorher = self._checks.get(key)
            if vorher is not None:
                self._checks[key] = Check(
                    key=key,
                    started_at=vorher.started_at,
                    report=report,
                    finished_at=datetime.now(),
                )

    def _forget_old(self, now: datetime) -> None:
        self._checks = {
            key: check
            for key, check in self._checks.items()
            if check.busy
            or check.finished_at is None
            or (now - check.finished_at).total_seconds() < FORGET_AFTER_SECONDS
        }
