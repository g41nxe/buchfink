"""Titel und YAML-Listen gegen das Profil halten, ohne die Oberfläche (#67).

Der Weg für ``ebw judge`` und den Skill ``buch-bewerten``: der Code urteilt
(``judging``), das Modell beschreibt höchstens ein Buch, das noch keinen
Steckbrief hat — einmal, gespeichert (ADR 33). Was schon beschrieben ist,
kostet keinen Aufruf: der Steckbrief wird unter der Eingabe selbst gesucht,
unter dem Buch im Regal und unter den Funden im Stapel.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import yaml

from .judging import Judge, Verdict, readers_verdict
from .models import MatchReason, Observation
from .portrait import Portrait
from .ratings import BY_READER, book_subject, subject_of
from .store import Store
from .web.intake import intake_subject

#: Die Quelle, unter der ein genannter Titel dem ``Portrayer`` vorgelegt wird.
#: Kein Fund im Sinn des Snapshots — die Beobachtung existiert nur für die Anfrage.
SOURCE = "judge"

#: Woher das Urteil stammt: der Steckbrief war da (``vorhanden``), er wurde
#: eben angelegt (``neu``), es gibt keinen und niemand hat gefragt (``fehlt``),
#: oder das Modell kennt das Buch nicht (``unbekannt``).
PRESENT, NEW, MISSING, UNKNOWN = "vorhanden", "neu", "fehlt", "unbekannt"


class Portrays(Protocol):
    """Was ``judge_titles`` vom ``Portrayer`` braucht — und was ein Test nachstellt."""

    def portray_finds(
        self, observations: Sequence[Observation]
    ) -> dict[tuple[str, str], Portrait]: ...


@dataclass(frozen=True, slots=True)
class Entry:
    """Ein genannter Titel, mit oder ohne Autor:in."""

    title: str
    author: str | None = None


@dataclass(frozen=True, slots=True)
class Result:
    """Was aus einem genannten Titel geworden ist."""

    entry: Entry
    verdict: Verdict | None
    source: str
    #: Prozent und Marken in einer Zeile — was in die YAML-Datei geschrieben wird.
    why: str | None


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def _names(entry: Entry, title: str, author: str | None) -> bool:
    """Ob Buch oder Fund diesen Titel meint — Wort für Wort, nicht geraten:
    ohne Autor:in in der Eingabe reicht der Titel, mit ihr muss sie stimmen."""
    return _same(title, entry.title) and (entry.author is None or _same(author, entry.author))


def _subjects_of(entry: Entry, books: Sequence, finds: Sequence[Observation]) -> list[str]:
    """Woran ein Steckbrief zu diesem Titel hängen kann, in der Reihenfolge, in
    der er gilt: die Eingabe selbst, das Buch im Regal, der Fund im Stapel."""
    subjects = [intake_subject(entry.title, entry.author)]
    subjects += [book_subject(b.id) for b in books if _names(entry, b.title, b.author)]
    subjects += [subject_of(f) for f in finds if _names(entry, f.title, f.author)]
    return subjects


def _readers_stars(store: Store, subjects: Sequence[str]) -> int | None:
    """Die eigenen Sterne der Leserin zu diesem Buch — sie gehen der Rechnung vor."""
    for subject in subjects:
        if subject.startswith("book:"):
            row = store.rating(subject, origin=BY_READER)
            if row is not None:
                return round(row.stars)
    return None


def _result(entry: Entry, verdict: Verdict | None, source: str) -> Result:
    return Result(entry, verdict, source, verdict.why if verdict is not None else None)


def judge_titles(
    store: Store,
    entries: Sequence[Entry],
    judge: Judge,
    portrayer: Portrays | None,
    *,
    now: datetime,
    ask: bool = True,
) -> list[Result]:
    """Jeden Titel beurteilen; was keinen Steckbrief hat, in **einem** Aufruf
    beschreiben lassen und behalten.

    ``ask=False`` fragt nichts nach: ein Titel ohne Steckbrief bleibt ``fehlt``.
    Ohne Weg zum Modell (``portrayer`` ist ``None``) ebenso.
    """
    books, finds = store.books(), store.latest_discoveries(judge.slug)
    subjects = {entry: _subjects_of(entry, books, finds) for entry in entries}
    portraits = judge.portraits(store, [s for these in subjects.values() for s in these])

    results: dict[Entry, Result] = {}
    missing: list[Entry] = []
    for entry in entries:
        stars = _readers_stars(store, subjects[entry])
        if stars is not None:
            results[entry] = _result(entry, readers_verdict(stars), PRESENT)
            continue
        portrait = next((portraits[s] for s in subjects[entry] if s in portraits), None)
        if portrait is None:
            missing.append(entry)
            continue
        verdict = judge.verdict(portrait)
        results[entry] = _result(entry, verdict, PRESENT if verdict is not None else UNKNOWN)

    # Derselbe Titel zweimal genannt wird einmal beschrieben und einmal gespeichert.
    missing = list(dict.fromkeys(missing))
    described: dict[tuple[str, str], Portrait] = {}
    if missing and ask and portrayer is not None:
        observations = [
            Observation(
                source=SOURCE,
                source_item_id=intake_subject(entry.title, entry.author),
                title=entry.title,
                author=entry.author,
                match_reason=MatchReason.GENRE_CATEGORY,
            )
            for entry in missing
        ]
        described = portrayer.portray_finds(observations)
    for entry in missing:
        subject = intake_subject(entry.title, entry.author)
        portrait = described.get((SOURCE, subject))
        if portrait is None:
            results[entry] = _result(entry, None, MISSING)
            continue
        store.put_portrait(subject, portrait, now=now)
        verdict = judge.verdict(portrait)
        results[entry] = _result(entry, verdict, NEW if verdict is not None else UNKNOWN)

    return [results[entry] for entry in entries]


# --- die YAML-Datei ---------------------------------------------------------------


def read_entries(text: str) -> list[Entry]:
    """Die Einträge einer Liste — jeder braucht einen ``title``."""
    data = yaml.safe_load(text) or []
    if not isinstance(data, list):
        raise ValueError("die Datei muss eine Liste von Einträgen sein")
    entries = []
    for number, item in enumerate(data, start=1):
        if not isinstance(item, dict) or not item.get("title"):
            raise ValueError(f"Eintrag {number} hat keinen title")
        author = item.get("author")
        entries.append(Entry(str(item["title"]), str(author) if author else None))
    return entries


_ENTRY_START = re.compile(r"^- ")
_INDENTED = re.compile(r"^ {2,}\S")
_STARS = re.compile(r"^ {2,}stars:")
_WHY = re.compile(r"^ {2,}why:")


def _block_end(lines: list[str], start: int) -> int:
    """Wo der Eintrag ab ``start`` endet: nach der letzten eingerückten Zeile.
    Eine Leerzeile gehört noch dazu, wenn danach eingerückt weitergeht."""
    end = start + 1
    while end < len(lines):
        if _INDENTED.match(lines[end]):
            end += 1
            continue
        after = end
        while after < len(lines) and not lines[after].strip():
            after += 1
        if after < len(lines) and _INDENTED.match(lines[after]):
            end = after + 1
            continue
        break
    return end


def _blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Die Zeilenbereiche der Einträge: Beginn bei ``- ``, Ende vor der ersten
    Zeile, die nicht eingerückt ist. Kommentare und Leerzeilen dazwischen
    gehören keinem Eintrag und bleiben, wo sie sind."""
    found = []
    index = 0
    while index < len(lines):
        if _ENTRY_START.match(lines[index]):
            end = _block_end(lines, index)
            found.append((index, end))
            index = end
        else:
            index += 1
    return found


def _entry_of(block: list[str]) -> Entry | None:
    data = yaml.safe_load("\n".join(block))
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        return None
    item = data[0]
    if not item.get("title"):
        return None
    author = item.get("author")
    return Entry(str(item["title"]), str(author) if author else None)


def _quoted(text: str) -> str:
    """Doppelt angeführt: Doppelpunkte, Anführungszeichen und Gedankenstriche in
    der Begründung lesen sich so unverändert zurück."""
    return json.dumps(text, ensure_ascii=False)


def _rewritten(block: list[str], verdict: Verdict, why: str) -> list[str]:
    """``stars`` und ``why`` ersetzen oder anfügen; alles andere bleibt."""
    stars_line = f"  stars: {verdict.stars}"
    why_line = f"  why: {_quoted(why)}"
    lines = list(block)
    stars_at = next((i for i, line in enumerate(lines) if _STARS.match(line)), None)
    why_at = next((i for i, line in enumerate(lines) if _WHY.match(line)), None)
    if stars_at is not None:
        lines[stars_at] = stars_line
    if why_at is not None:
        lines[why_at] = why_line
    if stars_at is None and why_at is None:
        lines += [stars_line, why_line]
    elif stars_at is None:
        lines.insert(why_at, stars_line)
    elif why_at is None:
        lines.insert(stars_at + 1, why_line)
    return lines


def update_yaml(text: str, results: Sequence[Result]) -> str:
    """``stars`` und ``why`` in die Datei schreiben — Kommentare, Reihenfolge und
    fremde Felder bleiben; ein Eintrag ohne Urteil bleibt, wie er war.

    Zeilenweise statt über einen YAML-Schreiber, denn der verlöre die
    Kommentare. Die Einträge werden über Titel und Autor:in wiedererkannt.
    """
    by_entry = {r.entry: r for r in results if r.verdict is not None and r.why is not None}
    lines = text.split("\n")
    for start, end in reversed(_blocks(lines)):
        entry = _entry_of(lines[start:end])
        result = by_entry.get(entry) if entry is not None else None
        if result is None:
            continue
        lines[start:end] = _rewritten(lines[start:end], result.verdict, result.why)
    return "\n".join(lines)
