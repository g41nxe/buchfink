"""Das Urteil über einen Fund, gerechnet statt gespeichert (ADR 33, #48).

Eine Stelle für Tor, Stapel, Tagesbericht und Buchseite: aus dem Steckbrief
eines Buchs und dem Leseprofil der Leserin werden Prozent, Sterne und
Begründung. Nichts davon wird gespeichert — eine neue Profilfassung wirkt
damit sofort und ohne Modellaufruf auf alles.
"""

from __future__ import annotations

from dataclasses import dataclass

from .facets import ReadingProfile, Reason, Weights, fit
from .portrait import Portrait, Vocabulary


@dataclass(frozen=True, slots=True)
class Verdict:
    """Was das Tor über einen Fund weiß."""

    stars: int
    #: ``None``, wenn die Leserin die Sterne selbst gegeben hat.
    percent: int | None = None
    reasons: tuple[Reason, ...] = ()
    pitch: str | None = None
    #: Die Sterne stammen von der Leserin, nicht aus der Rechnung.
    by_reader: bool = False

    def withholds(self, threshold: int) -> bool:
        return self.stars < threshold


def judge(
    portrait: Portrait | None,
    profile: ReadingProfile | None,
    vocabulary: Vocabulary,
    weights: Weights,
) -> Verdict | None:
    """Das gerechnete Urteil — oder ``None``, wenn nicht geurteilt wird.

    Nicht geurteilt wird ohne Steckbrief, über ein Buch, das das Modell nicht
    kennt, und ohne Profil (ADR 33, Punkt 8). Ein Fund ohne Urteil wird nie
    zurückgehalten (ADR 7).
    """
    if portrait is None or profile is None:
        return None
    result = fit(portrait, profile, vocabulary, weights)
    if result is None:
        return None
    return Verdict(
        stars=result.stars,
        percent=round(result.share * 100),
        reasons=result.reasons,
        pitch=portrait.pitch,
    )


def readers_verdict(stars: int) -> Verdict:
    """Die eigenen Sterne der Leserin: eine Tatsache, sie gehen der Rechnung vor."""
    return Verdict(stars=stars, by_reader=True)
