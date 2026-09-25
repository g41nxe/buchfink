"""Die Rechnung vor #79, als Nachbau für den Prüfstand.

Bis zum 26.09.2026 urteilte ``facets.fit``: Noisy-OR über ganze Facetten (0,8),
einzelne gemochte Merkmale (0,1, verstärkt 0,2) und Erzählmuster (0,3, verstärkt
0,4), das stärkste Gegengewicht zog 0,35 ab. Die Formüberdeckung hat sie ersetzt;
die Prototypen vergleichen mit ihr als „heute".
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ebook_watchlist.facets import (
    Counterweight,
    Facet,
    Liked,
    ReadingProfile,
    Reason,
    families_of,
    family_name,
    family_names,
    genre_matches,
    is_pattern,
)
from ebook_watchlist.portrait import Portrait, Vocabulary


@dataclass(frozen=True, slots=True)
class Weights:
    full: float = 0.8
    single: float = 0.1
    boost: float = 0.1
    pattern: float = 0.3
    counterweight: float = 0.35
    stars_from: tuple[tuple[int, float], ...] = ((5, 0.8), (4, 0.6), (3, 0.4), (2, 0.2))
    gate_stars: int = 3

    def liked(self, liked: Liked, pattern: bool) -> float:
        return (self.pattern if pattern else self.single) + (self.boost if liked.boosted else 0)


@dataclass(frozen=True, slots=True)
class FacetHit:
    facet: Facet


@dataclass(frozen=True, slots=True)
class Fit:
    share: float
    stars: int
    hits: tuple[FacetHit, ...]
    liked: tuple[Liked, ...]
    against: Counterweight | None
    reasons: tuple[Reason, ...]


def fit(
    portrait: Portrait, profile: ReadingProfile, vocabulary: Vocabulary, weights: Weights
) -> Fit | None:
    """Wie gut das Buch passt — oder ``None``, wenn nicht geurteilt wird.

    Nicht geurteilt wird ohne Profil — weder Facetten noch Gemochtes (ADR 33,
    Punkt 8) — und über ein Buch, das das Modell nicht kennt: ohne Merkmale
    hieße jedes Urteil "passt nicht", und das wäre eine Behauptung, keine
    Auskunft.

    Teiltreffer einer Facette gibt es nicht mehr: was eine Facette zum Teil
    trifft, zählt über ihre Merkmale einzeln (#64).
    """
    if not (profile.facets or profile.liked) or not portrait.known:
        return None
    book_families = families_of(portrait, vocabulary)

    hits = [FacetHit(facet) for facet in profile.facets if set(facet.families) <= book_families]
    liked = tuple(g for g in profile.liked if g.family in book_families)

    factors = [weights.full] * len(hits)
    factors += [weights.liked(g, is_pattern(g.family, vocabulary)) for g in liked]
    share = 1 - math.prod(1 - f for f in factors)
    against = next(
        (
            c
            for c in profile.counterweights
            if all(f in book_families for f in c.families) and genre_matches(c, portrait)
        ),
        None,
    )
    if against is not None:
        share *= 1 - weights.counterweight

    if share == 0:
        stars = 0 if against is not None else 1
    else:
        stars = next((s for s, ab in weights.stars_from if share >= ab), 1)

    return Fit(
        share=share,
        stars=stars,
        hits=tuple(hits),
        liked=liked,
        against=against,
        reasons=_reasons(
            hits, liked, lambda f: is_pattern(f, vocabulary), against, portrait, vocabulary
        ),
    )


def _reasons(
    hits: list[FacetHit],
    liked: Sequence[Liked],
    is_story_pattern: Callable[[str], bool],
    against: Counterweight | None,
    portrait: Portrait,
    vocabulary: Vocabulary,
) -> tuple[Reason, ...]:
    """Die Begründung aus Daten: welche Facette, welches Merkmal, und der Satz dazu.

    Alles ist gleich gebaut — eine Marke, darunter die Sätze aus dem
    Steckbrief. Nur der Satz: die Familie steht schon in der Marke, und zweimal
    derselbe Name ist keine zweite Auskunft. Ein Merkmal, das schon in einer
    getroffenen Facette steht, bekommt keine eigene Marke.
    """

    def evidence_for(family_ids: Sequence[str]) -> list[Reason]:
        sentences = []
        for family_id in family_ids:
            sentence = next(
                (
                    trait.sentence
                    for trait in portrait.traits
                    if trait.term in vocabulary.terms
                    and vocabulary.family_of(trait.term).id == family_id
                ),
                "",
            )
            if sentence:
                sentences.append(Reason("beleg", sentence))
        return sentences

    lines: list[Reason] = []
    for hit in hits:
        lines.append(Reason("ganz", family_names(hit.facet.families, vocabulary)))
        lines.extend(evidence_for(hit.facet.families))
    families_in_hits = {f for hit in hits for f in hit.facet.families}
    # Verstärktes zuerst, dann Merkmale vor Erzählmustern.
    for entry in sorted(liked, key=lambda g: (not g.boosted, is_story_pattern(g.family))):
        if entry.family in families_in_hits:
            continue
        kind = "muster" if is_story_pattern(entry.family) else "merkmal"
        lines.append(Reason(kind, family_name(entry.family, vocabulary), entry.boosted))
        lines.extend(evidence_for((entry.family,)))
    if not hits and not liked:
        lines.append(Reason("keine", "nichts Gemochtes getroffen"))
    if against is not None:
        genre_note = f" (bei {against.genre})" if against.genre else ""
        lines.append(Reason("dagegen", family_names(against.families, vocabulary) + genre_note))
        lines.extend(evidence_for(against.families))
    return tuple(lines)
