"""Quellen parallel, je Server eine Anfrage zur Zeit (#101)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import requests

from ebook_watchlist import run
from ebook_watchlist.http import HttpClient
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.sources import registry


def _found(source: str, item_id: str) -> Observation:
    return Observation(
        source=source, source_item_id=item_id, title=f"Titel {item_id}", author="Wer",
        match_reason=MatchReason.WATCHLIST, price_cents=399,
    )


@dataclass
class Waits:
    """Eine Quelle, die erst antwortet, wenn alle anderen auch angefangen haben."""

    name: str
    barrier: threading.Barrier
    delay: float = 0.0
    fails: bool = False
    calls: list[str] = field(default_factory=list)

    def collect(self, settings, watchlist, context):
        self.barrier.wait(timeout=5)
        time.sleep(self.delay)
        if self.fails:
            raise RuntimeError("kaputt")
        return [_found(self.name, "1")]


def test_the_sources_ask_at_the_same_time() -> None:
    """Gingen sie nacheinander, wartete die erste ewig auf die zweite."""
    barrier = threading.Barrier(3)
    sources = [Waits("a", barrier), Waits("b", barrier), Waits("c", barrier)]

    observations, failures = run._collect(sources, None, None, None)  # type: ignore[arg-type]

    assert failures == []
    assert {o.source for o in observations} == {"a", "b", "c"}


def test_the_order_follows_the_sources_not_the_clock() -> None:
    """Die erste Quelle braucht am längsten; ihre Funde stehen trotzdem vorn."""
    barrier = threading.Barrier(2)
    sources = [Waits("slow", barrier, delay=0.3), Waits("fast", barrier)]

    observations, _ = run._collect(sources, None, None, None)  # type: ignore[arg-type]

    assert [o.source for o in observations] == ["slow", "fast"]


def test_one_failing_source_costs_only_itself() -> None:
    barrier = threading.Barrier(2)
    sources = [Waits("broken", barrier, fails=True), Waits("fine", barrier)]

    observations, failures = run._collect(sources, None, None, None)  # type: ignore[arg-type]

    assert [o.source for o in observations] == ["fine"]
    assert [f.source for f in failures] == ["broken"]
    assert "kaputt" in failures[0].message


def test_every_source_gets_its_own_client(monkeypatch) -> None:
    """Die Pause gilt je Server: ein gemeinsamer Client hielte alle in einer Schlange."""
    clients: list[HttpClient] = []
    monkeypatch.setitem(
        registry._BUILDERS, "probe", lambda name, options, client: clients.append(client)
    )
    shared = HttpClient()
    settings = type("S", (), {"sources": {"eins": {"kind": "probe"}, "zwei": {"kind": "probe"}}})()

    registry.build_sources(settings, shared)  # type: ignore[arg-type]

    assert clients[0] is not clients[1]
    assert shared not in clients
    assert clients[0].user_agent == shared.user_agent
    assert clients[0].session is not clients[1].session


def test_a_given_session_is_kept_for_every_source() -> None:
    """Wer eine Sitzung hineinreicht (Tests, Aufzeichnungen), bekommt sie überall."""
    session = requests.Session()
    shared = HttpClient(session=session)

    sibling = shared.for_another_server()

    assert sibling.session is session
    assert sibling is not shared


class _Clock:
    def __init__(self) -> None:
        self.at: list[float] = []
        self.headers: dict[str, str] = {}

    def get(self, url, params=None, timeout=None):
        self.at.append(time.perf_counter())
        response = requests.Response()
        response.status_code = 200
        response._content = b"ok"
        return response


def test_one_client_still_asks_one_at_a_time_from_two_threads() -> None:
    """Teilen sich zwei Quellen doch einen Server (die DNB), bleibt die Pause."""
    clock = _Clock()
    client = HttpClient(session=clock, min_delay=0.2, max_delay=0.2)  # type: ignore[arg-type]

    threads = [threading.Thread(target=client.get, args=("http://x.invalid",)) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    gaps = [b - a for a, b in zip(clock.at, clock.at[1:], strict=False)]
    assert len(clock.at) == 3
    assert all(gap >= 0.19 for gap in gaps), gaps


class _SlowFirstClock(_Clock):
    """Die erste Anfrage trödelt, bevor sie ankommt — wie ein Faden, der unter
    Last zwischen Zeitstempel und Absenden ins Stocken gerät."""

    def get(self, url, params=None, timeout=None):
        if not self.at:
            time.sleep(0.05)
        return super().get(url, params=params, timeout=timeout)


def test_the_pause_counts_from_the_end_of_the_last_request() -> None:
    """Gemessen ab dem Zeitstempel *vor* der Anfrage lagen zwei echte Anfragen
    unter Last enger als die Pause (der Test darüber flackerte, 29.10.2026)."""
    clock = _SlowFirstClock()
    client = HttpClient(session=clock, min_delay=0.2, max_delay=0.2)  # type: ignore[arg-type]

    client.get("http://x.invalid")
    client.get("http://x.invalid")

    assert clock.at[1] - clock.at[0] >= 0.19, clock.at
