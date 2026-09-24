"""Wer den Stapel erreicht — und wer nicht (ADR 19, Ticket 12).

Das Tor sitzt zwischen der Meldelogik und dem Digest. Es läuft **nach** dem
Snapshot: ein Ausfall kostet damit ein Urteil, nie Geschichte. Und es läuft
**nach** der Preisregel, weil ein Buch zu bewerten, das ohnehin niemand zu
sehen bekommt, Verschwendung wäre.

Seit #48 urteilt der **Code**: das Modell legt zu einem neuen Fund einmal den
Steckbrief an, alles Weitere rechnet :func:`judging.judge` aus Steckbrief und
Leseprofil. Ein Fund ohne Urteil — kein Profil, kein Steckbrief, ein Buch, das
das Modell nicht kennt — wird gezeigt und nie zurückgehalten (ADR 7).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .facets import ReadingProfile, Weights
from .judging import Verdict, judge, readers_verdict
from .models import Delta, DeltaKind, MatchReason, Observation
from .portrait import Portrait, Vocabulary, fingerprint
from .rating import RatingUnavailable
from .ratings import BY_READER, book_subject, subject_of
from .store import Store


@dataclass(slots=True)
class GateReport:
    """Was das Tor getan hat.

    Der Digest nennt die Zahlen, damit ein zu scharf gesetzter Schwellwert und
    ein aufgebrauchtes Budget sichtbar sind statt still zu wirken (ADR 19).
    """

    held_back: int = 0
    #: Die Schwelle, gegen die entschieden wurde — der Tagesbericht nennt sie.
    threshold: int = 0
    #: Steckbriefe, die dieser Lauf angelegt hat.
    rated: int = 0
    #: Urteile, die ein schon vorhandener Steckbrief oder die eigenen Sterne
    #: der Leserin ohne Aufruf lieferten.
    reused: int = 0
    #: Kein Urteil möglich — der Bewerter kam nicht durch, das Buch ist dem
    #: Modell unbekannt, oder es ist keiner eingerichtet — und deshalb gezeigt.
    unrated: int = 0
    #: Über dem Budget und deshalb ungefragt durchgelassen — unbewertet und
    #: gezeigt, nie verworfen.
    over_budget: int = 0
    #: Es gibt kein Leseprofil, und der Lauf hatte Funde: nichts wurde
    #: geurteilt, und das soll dastehen (ADR 33, Punkt 8).
    no_profile: bool = False
    #: Das Urteil zu jedem durchgelassenen Fund, am Schlüssel der Beobachtung.
    #: Der Digest zeigt es: die Begründung ist der Grund, den ein Vorschlag
    #: mitbringt (ADR 19, Ticket 14).
    judgements: dict[tuple[str, str], Verdict] = field(default_factory=dict)

    @property
    def calls(self) -> int:
        return self.rated


def _readers_verdict(store: Store, observation: Observation, version: int) -> Verdict | None:
    """Was die Leserin selbst gesagt hat, schlägt jede Rechnung (ADR 17)."""
    if observation.book_id is None:
        return None
    stored = store.rating(book_subject(observation.book_id), version, origin=BY_READER)
    return readers_verdict(stored.stars) if stored is not None else None


def _decide(
    verdict: Verdict, delta: Delta, threshold: int, kept: list[Delta], report: GateReport
) -> None:
    """Ob dieses Urteil den Fund durchlässt — die **einzige** Stelle dafür.

    Erstsichtung und Preissturz haben das eine Weile getrennt entschieden, und
    genau so entstand die offene Hintertür, die dieses Modul schon einmal
    hatte. Ein zweites Mal ist es dieselbe Funktion.
    """
    if verdict.withholds(threshold):
        report.held_back += 1
        return
    report.judgements[delta.current.key] = verdict
    kept.append(delta)


def apply(
    deltas: list[Delta],
    *,
    store: Store,
    profile: ReadingProfile | None,
    vocabulary: Vocabulary,
    weights: Weights,
    portrayer: Callable[[Observation], Portrait] | None,
    threshold: int,
    budget: int,
    now: datetime,
    evidence: Callable[[list[Observation]], list[Observation]] | None = None,
) -> tuple[list[Delta], GateReport]:
    """Entdeckungen unter dem Schwellwert aussortieren.

    Ohne Profil wird nicht geurteilt: alles bleibt, und der Bericht sagt es.
    Ohne ``portrayer`` (kein Schlüssel, keine Anmeldung) urteilt das Tor über
    die Funde, die schon einen Steckbrief haben; der Rest wird gezeigt.

    ``budget`` begrenzt die *Steckbriefe* eines Laufs. Der erste Lauf trifft
    einen Rückstand von dreihundert Entdeckungen, und die alle am Stück
    abzufeuern widerspräche derselben Zurückhaltung, die jede andere
    ausgehende Anfrage in diesem Projekt bindet (ADR 7). Ein vorhandener
    Steckbrief kostet nichts und zählt nicht mit.

    ``evidence`` holt den ganzen Klappentext für genau die Bücher, die
    gleich beschrieben werden: die Kachel einer Trefferliste ist im Median
    197 Zeichen lang und zu 85 % abgeschnitten, ein Steckbrief daraus bliebe
    für immer dünn. Die Quellen reicht der Lauf herein, das Tor kennt keine.
    """
    if profile is None:
        return deltas, GateReport(
            threshold=threshold, no_profile=any(_is_discovery(d) for d in deltas)
        )

    report = GateReport(threshold=threshold)
    stamp = fingerprint(vocabulary)
    portraits: dict[tuple[str, str], Portrait] = {}
    created: set[tuple[str, str]] = set()
    attempted: set[tuple[str, str]] = set()

    # Erst sammeln, wer einen Steckbrief braucht, dann fragen — je Buch einmal.
    wanted: list[Observation] = []
    for delta in deltas:
        if not _is_discovery(delta):
            continue
        observation = delta.current
        if _readers_verdict(store, observation, profile.version) is not None:
            continue
        existing = store.portrait(subject_of(observation), stamp)
        if existing is not None:
            portraits[observation.key] = existing
        elif observation.key not in {o.key for o in wanted}:
            wanted.append(observation)

    if portrayer is not None:
        wanted = wanted[:budget]
        attempted = {observation.key for observation in wanted}
        described = wanted
        if wanted and evidence is not None:
            # Der Schlüssel bleibt der der Sichtung: nachgeladen wird der Text,
            # nicht die Nummer. Zugeordnet wird über den Schlüssel, nicht über
            # die Reihenfolge — ein Rückruf, der filtert oder umsortiert,
            # verschöbe sonst die Antworten gegen die Bücher.
            fuller = {o.key: o for o in evidence(wanted)}
            described = [fuller.get(o.key, o) for o in wanted]
        for observation, full in zip(wanted, described, strict=True):
            try:
                portrait = portrayer(full)
            except RatingUnavailable:
                continue
            store.put_portrait(subject_of(observation), portrait, now=now)
            portraits[observation.key] = portrait
            created.add(observation.key)
            report.rated += 1

    kept: list[Delta] = []
    for delta in deltas:
        if delta.current.match_reason is MatchReason.WATCHLIST:
            # Von der Leserin selbst gewählt; sie gegen ihr eigenes Profil
            # abzulehnen wäre anmaßend.
            kept.append(delta)
            continue

        observation = delta.current
        verdict = _readers_verdict(store, observation, profile.version)
        if verdict is None:
            portrait = portraits.get(observation.key)
            if portrait is None and delta.kind is not DeltaKind.FIRST_SEEN:
                portrait = store.portrait(subject_of(observation), stamp)
            verdict = judge(portrait, profile, vocabulary, weights)

        if verdict is None:
            if delta.kind is DeltaKind.FIRST_SEEN:
                if (
                    observation.key in portraits
                    or observation.key in attempted
                    or portrayer is None
                ):
                    # Gefragt, aber ohne Antwort (kein Netz, unlesbare Antwort),
                    # dem Modell unbekannt, oder es ist kein Bewerter
                    # eingerichtet: unbewertet und trotzdem gezeigt — ein Tor,
                    # das im Zweifel schließt, verschluckt Neuzugänge.
                    report.unrated += 1
                else:
                    # Über dem Budget und deshalb gar nicht erst gefragt: der
                    # Rest wartet auf den nächsten Lauf und wird solange
                    # gezeigt.
                    report.over_budget += 1
            # Ein Preissturz ohne Urteil bleibt, wie er ist: er kostet nie
            # einen neuen Steckbrief.
            kept.append(delta)
            continue

        # Ein Preissturz wird am vorhandenen Urteil gemessen. Vorher lief er am
        # Tor vorbei, und ein Buch, das zurückgehalten worden war, meldete sich
        # beim nächsten Nachlass doch: streng an der Vordertür, offen an der
        # Hintertür.
        if observation.key not in created:
            report.reused += 1
        _decide(verdict, delta, threshold, kept, report)
    return kept, report


def _is_discovery(delta: Delta) -> bool:
    """Die Erstsichtung einer Entdeckung — das, wofür ein Steckbrief gebraucht wird.

    Ein Watchlist-Titel wurde von der Leserin selbst gewählt; ihn gegen ihr
    eigenes Profil abzulehnen wäre anmaßend. Ein Preissturz wird ebenfalls
    nicht *beschrieben* — aber er wird sehr wohl am vorhandenen Urteil
    gemessen, und das tut :func:`apply` an seiner eigenen Stelle.
    """
    return (
        delta.kind is DeltaKind.FIRST_SEEN
        and delta.current.match_reason is not MatchReason.WATCHLIST
    )
