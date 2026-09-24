"""Das Urteil über einen Fund, gerechnet statt gespeichert (ADR 33, #48).

Eine Stelle für Tor, Stapel, Tagesbericht und Buchseite: aus dem Steckbrief
eines Buchs und dem Leseprofil der Leserin werden Prozent, Sterne und
Begründung. Nichts davon wird gespeichert — eine neue Profilfassung wirkt
damit sofort und ohne Modellaufruf auf alles.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import yaml

from .facets import ReadingProfile, Reason, Weights, fit, load_weights
from .portrait import Portrait, Vocabulary, VocabularyError, fingerprint, load_vocabulary
from .store import Store


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


@dataclass(frozen=True, slots=True)
class Judge:
    """Profil, Vokabular und Gewichte, einmal geladen — für eine ganze Liste.

    Der Stapel, die Watchlist und die Startseite urteilen über Dutzende Funde
    auf einmal; das Profil und das Vokabular je Zeile neu zu laden wäre
    Verschwendung.
    """

    profile: ReadingProfile
    vocabulary: Vocabulary
    weights: Weights
    #: Der Fingerabdruck des Vokabulars: nur Steckbriefe mit diesem gelten.
    stamp: str

    @property
    def threshold(self) -> int:
        """Ab wie vielen Sternen das Tor durchlässt."""
        return self.weights.gate_stars

    def verdict(self, portrait: Portrait | None) -> Verdict | None:
        return judge(portrait, self.profile, self.vocabulary, self.weights)

    def verdict_among(
        self, portraits: Mapping[str, Portrait], subjects: Sequence[str]
    ) -> Verdict | None:
        """Das Urteil nach dem ersten Schlüssel, zu dem es einen Steckbrief gibt.

        Ein Buch kann unter der ISBN, unter einer Produktnummer oder unter seiner
        Buchnummer beschrieben sein; welcher gilt, sagt die Reihenfolge.
        """
        for subject in subjects:
            if subject in portraits:
                return self.verdict(portraits[subject])
        return None

    def portraits(self, store: Store, subjects) -> dict[str, Portrait]:
        return store.portraits_for(subjects, self.stamp)


def load_judge(store: Store, slug: str) -> Judge | None:
    """Der Urteilende dieser Leserin — oder ``None``, wenn nicht geurteilt wird.

    Nicht geurteilt wird ohne Profil in der Datenbank (ADR 33, Punkt 8) und
    ohne lesbares Vokabular oder Schema: die Seiten zeigen dann, was sie ohne
    Urteil zeigen, statt zu scheitern.
    """
    profile = store.reading_profile(slug)
    if profile is None:
        return None
    try:
        vocabulary = load_vocabulary()
        weights = load_weights()
    except (VocabularyError, OSError, KeyError, ValueError, yaml.YAMLError):
        return None
    return Judge(profile, vocabulary, weights, fingerprint(vocabulary))
