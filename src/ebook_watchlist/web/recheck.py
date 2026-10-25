"""Kleine Aufträge anstoßen und sagen, wo sie stehen (Ticket 51, ADR 40).

Der enge Lauf, der Steckbrief und das Erkennen in der Erstaufnahme sind
Aufträge in der Warteschlange (`jobs`); der Hintergrunddienst arbeitet sie ab.
Bis ADR 40 liefen sie als Fäden im Webprozess — gemessen, weil ein eigener
Prozess je engem Lauf rund eine Sekunde Hochlauf gekostet hätte. Der Dienst
läuft ohnehin, also kostet ein Auftrag nur noch seine Abholung (höchstens eine
Sekunde, `jobs.worker_main`).

Der Stand je Auftrag liegt in der Schlüsselablage der Schlange, damit
Oberfläche und Dienst getrennte Prozesse sein können. Nachgefragt wird über
htmx, genau wie beim großen Lauf (``_run_panel.html``): der Trigger steht nur
dran, solange etwas läuft. Kein Websocket (ADR 3).
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from datetime import datetime

from .. import jobs
from ..single import Report, check_one

__all__ = ["Check", "Rechecker", "check_one"]

#: Was ein Auftrag sagt, dessen Dienst nicht läuft.
NO_SERVICE = "Kein Hintergrunddienst — `ebw serve` starten"

#: Was ein Auftrag sagt, der mit seinem Dienst untergegangen ist.
LOST = "Abgebrochen — bitte noch einmal anstoßen"


@dataclass(frozen=True, slots=True)
class Check:
    """Wo ein Auftrag gerade steht — ein enger Lauf, ein Steckbrief, ein Erkennen.

    ``key`` ist, woran der Auftrag hängt: beim engen Lauf die Buchnummer, beim
    Steckbrief das, was beschrieben wird (#15).
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
    """Stößt Aufträge einer Art an — einen je Schlüssel — und liest ihren Stand.

    ``kind`` nennt die Arbeit (`web.work.WORK`): ``recheck`` für den engen
    Lauf, ``portrait`` für den Steckbrief, ``identify`` für die Erstaufnahme.
    Gebaut wird je Art eine Instanz; der Zustand liegt nicht in ihr, sondern
    in der Schlange.
    """

    def __init__(self, kind: str = "recheck") -> None:
        self.kind = kind

    def start(self, key: Hashable, *, now: datetime | None = None, **options) -> Check:
        """Anstossen, falls fuer diesen Schluessel nicht schon etwas laeuft.

        ``options`` gehen an die Arbeit mit (etwa ``again`` beim Steckbrief).
        Ohne laufenden Dienst wird nichts eingestellt — der Auftrag läge sonst
        still in der Schlange, und die Zeile sagte „wartet …“ für immer.
        """
        now = now or datetime.now()
        running = self.state(key, now=now)
        if running is not None and running.busy:
            return running
        if not jobs.service_alive():
            return Check(key=key, started_at=now, report=Report(trouble=NO_SERVICE),
                         finished_at=now)
        jobs.job_started(self.kind, key, now)
        jobs.enqueue("job", self.kind, key, options)
        return self.state(key, now=now) or Check(key=key, started_at=now)

    def state(self, key: Hashable, *, now: datetime | None = None) -> Check | None:
        """Wo dieser eine Auftrag steht — ``None``, wenn keiner bekannt ist."""
        raw = jobs.job_state(self.kind, key)
        if raw is None:
            return None
        started = raw["started_at"]
        if raw["finished_at"] is None:
            if jobs.job_lost(raw):
                return Check(key=key, started_at=started, report=Report(trouble=LOST),
                             finished_at=datetime.now())
            return Check(key=key, started_at=started)
        return Check(
            key=key,
            started_at=started,
            report=Report(trouble=raw["trouble"]),
            finished_at=raw["finished_at"],
        )
