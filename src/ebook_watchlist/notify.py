"""Der Tagesbericht als Benachrichtigung aufs Telefon (#98, ADR 40).

Das Versprechen ist „meldet sich, wenn sich etwas ändert“ — bis hierher lag
der Tagesbericht aber nur in ``data/digests/``. Jetzt geht eine kurze Nachricht
hinaus, und zwar genau dann, wenn der Tagesbericht etwas zu sagen hat: dieselbe
Bedingung, unter der er nicht schweigt. „Nichts Neues“ wird nie gemeldet.

Der Weg ist **Apprise**: eine Adresszeile wählt den Dienst (``ntfy://…``,
``tgram://…``, ``mailto://…``). Die Adresse ist ein Geheimnis und steht in
``data/secrets.env`` oder der Umgebung (`EBW_NOTIFY_URL`), nie in der
Datenbank. Ohne Adresse geht nichts hinaus.

Fehler werden gemeldet, aber erst wenn eine Quelle zweimal hintereinander
ausfällt — ein einzelner Ausfall ist oft ein Schluckauf des Servers — oder
wenn ein Lauf ganz abbricht.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from .config import Settings
from .credentials import secret
from .digest import SECTION_AUTHORS, SECTION_GENRE, SECTION_LIBRARY, SECTION_PRICES, Digest
from .models import SourceFailure
from .store import Store

ADDRESS_ENV = "EBW_NOTIFY_URL"

#: Höchstens so viele Treffer stehen in der Nachricht; der Rest hinter dem Link.
MAX_LINES = 3

#: Im Journal der Zustände: seit wann eine Quelle ausfällt.
_FAILING = "source_failing:"

_HITS = (SECTION_PRICES, SECTION_LIBRARY)
_NEW = (SECTION_AUTHORS, SECTION_GENRE)


@dataclass(frozen=True, slots=True)
class Message:
    title: str
    body: str


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _line(section: str, title: str, detail: str | None) -> str:
    """„Titel — 3,99 €“ oder „Titel — ausleihbar“: der eine Grund, hinzusehen."""
    if section == SECTION_LIBRARY:
        return f"{title} — ausleihbar"
    price = (detail or "").split("→")[-1].strip()
    return f"{title} — {price}" if price else title


def message(digest: Digest, *, public_url: str | None) -> Message | None:
    """Die Nachricht zu einem Tagesbericht — oder keine, wenn er nichts Neues hat.

    Überschrift mit Zahlen, darunter höchstens drei Watchlist-Treffer, am Ende
    der Link auf die Startseite. Vorschläge werden nur gezählt: ob einer passt,
    entscheidet man auf der Seite, nicht in einer Benachrichtigung.
    """
    by_title = {section.title: section.entries for section in digest.sections}
    hits = [(name, entry) for name in _HITS for entry in by_title.get(name, ())]
    new = sum(len(by_title.get(name, ())) for name in _NEW)
    if not hits and not new:
        return None
    parts = []
    if hits:
        parts.append(f"{len(hits)} jetzt zu haben")
    if new:
        parts.append(_plural(new, "neuer Vorschlag", "neue Vorschläge"))
    lines = [_line(name, entry.title, entry.detail) for name, entry in hits[:MAX_LINES]]
    if public_url:
        lines.append(f"{public_url}/")
    return Message(title=" · ".join(parts), body="\n".join(lines))


def deliver(address: str, title: str, body: str) -> None:
    """Hinaus damit. Ersetzt in Tests — dort geht nie etwas hinaus."""
    import apprise

    sender = apprise.Apprise()
    if not sender.add(address):
        raise ValueError("Apprise kennt diese Adresse nicht")
    if not sender.notify(title=title, body=body):
        raise OSError("Apprise hat nicht zugestellt")


def send(note: Message) -> bool:
    """Verschicken, falls eine Adresse da ist. Ein Fehler kostet nur die Nachricht.

    Die Adresse erscheint in keiner Meldung: sie enthält oft ein Token.
    """
    address = secret(ADDRESS_ENV)
    if not address:
        return False
    try:
        deliver(address, note.title, note.body)
    except Exception as exc:  # noqa: BLE001 - eine Nachricht ist nie wichtiger als der Lauf
        print(f"Benachrichtigung nicht verschickt: {type(exc).__name__}", file=sys.stderr)
        return False
    return True


def _failing_twice(
    store: Store, profile_slug: str, failures: Sequence[SourceFailure], ran: Iterable[str],
    now: datetime,
) -> list[SourceFailure]:
    """Welche Quellen schon beim letzten Lauf ausgefallen waren.

    Gemerkt wird je Quelle, seit wann sie ausfällt; ein Lauf, in dem sie
    funktioniert, vergisst es. Pausierte Quellen liefen nicht und bleiben,
    wie sie sind.
    """
    failed = {failure.source: failure for failure in failures}
    twice = []
    for name in set(ran) | set(failed):
        key = _FAILING + name
        if name in failed:
            if store.get_state(profile_slug, key) is not None:
                twice.append(failed[name])
            else:
                store.set_state(profile_slug, key, now)
        else:
            store.clear_state(profile_slug, key)
    return twice


def after_run(
    digest: Digest, settings: Settings, store: Store, *,
    failures: Sequence[SourceFailure], ran: Iterable[str], now: datetime,
) -> None:
    """Nach einem Lauf: Neues melden, und Quellen, die zum zweiten Mal ausfallen."""
    twice = _failing_twice(store, settings.slug, failures, ran, now)
    note = message(digest, public_url=settings.public_url)
    if note is not None:
        send(note)
    if twice:
        names = ", ".join(sorted(failure.source for failure in twice))
        send(Message(
            title=f"Quelle fällt wiederholt aus: {names}",
            body="\n".join(f"{failure.source}: {failure.message}" for failure in twice),
        ))


def run_broke(exc: BaseException) -> None:
    """Ein Lauf ist ganz abgebrochen — das wird sofort gemeldet."""
    send(Message(title="Buchfink: Lauf abgebrochen", body=f"{type(exc).__name__}: {exc}"))
