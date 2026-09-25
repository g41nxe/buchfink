"""Die Geschmacksform und die Formüberdeckung (#79, docs/research/urteil-methode.md).

Die **Geschmacksform** ist der Geschmack der Leserin als Form über den Achsen
des Vokabulars, wie ein Spinnennetz: nach außen, wo sie etwas mag, nach innen,
wo sie es ablehnt, in der Mitte, wo sie nichts gesagt hat. Wie weit sie reicht,
wird aus ihren Büchern gelernt (*Mag ich* und *Doof*, jedes Merkmal so stark,
wie es im Buch wiegt); was sie angetippt oder verstärkt hat, ist der Startwert.

Die **Formüberdeckung** ist das Urteil: wie viel der Form eines Buchs in ihrer
Geschmacksform liegt, weniger dem, was im ablehnenden Teil liegt. Absichtlich
einseitig: ein Buch muss nicht alles tragen, was sie mag. Die Erzählmuster
bilden eine zweite Spinne mit derselben Rechnung. Eine Facette, die das Buch
ganz trägt, gibt einen Aufschlag; ein Gegengewicht mit Genre bleibt eine Regel.

Kein Modell wird gefragt, und nichts wird gespeichert (ADR 33). Die Werte
stehen im Bewertungsschema (``urteil_formueberdeckung``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .facets import (
    Counterweight,
    ReadingProfile,
    Reason,
    Weights,
    family_name,
    family_names,
    genre_matches,
    is_pattern,
)
from .portrait import Portrait, Vocabulary

#: Ab welchem Wert der Form ein Merkmal in der Begründung als gemocht oder als
#: dagegen genannt wird. Darunter trägt es zum Urteil bei, ohne eigene Marke:
#: eine Begründung, die jedes schwach Gemochte aufzählt, sagt nichts mehr.
NAMED_FROM = 0.3


@dataclass(frozen=True, slots=True)
class RatedBook:
    """Ein Buch, das die Leserin gelesen und bewertet hat."""

    title: str
    #: +1 für *Mag ich*, −1 für *Doof*.
    sign: int
    #: Merkmal → Gewicht im Buch, aus dem Steckbrief (``book_terms``).
    terms: Mapping[str, float]
    genre: str | None = None
    #: Familien, die das Buch für die Leserin trug, obwohl der Steckbrief sie
    #: nicht nennt (Z10): beim Schwarm *gemächlich*.
    added: tuple[str, ...] = ()
    #: Familien, die nicht zählen: was sie anders erlebt hat (der Schwarm war
    #: für sie nicht *spannungsgeladen*), oder was sie nur hier gestört hat.
    dropped: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TasteForm:
    """Die Geschmacksform: je Familie und je Merkmal ein Wert von −1 bis 1."""

    family: Mapping[str, float]
    term: Mapping[str, float]
    #: Die Familien, zu denen es irgendeine Angabe gibt. Über alle anderen
    #: weiß die Form nichts, und sie zählen weder dafür noch dagegen (Z2).
    known: frozenset[str]
    #: Gegengewichte, die nur in einem Genre gelten: eine Regel der Leserin,
    #: keine Richtung der Form.
    genre_rules: tuple[Counterweight, ...] = ()

    def value(self, term: str, family: str) -> float:
        """Der Wert eines Merkmals; ohne eigene Angabe der seiner Familie."""
        return self.term.get(term, self.family.get(family, 0.0))


@dataclass(frozen=True, slots=True)
class Overlap:
    """Die Übereinstimmung eines Buchs mit der Geschmacksform."""

    #: Zwischen 0 und 1; ordnet die Liste.
    share: float
    #: 1 bis 5; fasst zusammen.
    stars: int
    #: Die Begründung, Zeile für Zeile.
    reasons: tuple[Reason, ...]


def book_terms(portrait: Portrait, vocabulary: Vocabulary, weights: Weights) -> dict[str, float]:
    """Merkmal → Gewicht im Buch. Ein Merkmal, das das Vokabular nicht kennt, fehlt."""
    out: dict[str, float] = {}
    for trait in portrait.traits:
        if trait.term in vocabulary.terms:
            w = weights.trait_weight(trait.weight)
            out[trait.term] = max(out.get(trait.term, 0.0), w)
    return out


def learn(
    profile: ReadingProfile,
    rated: Sequence[RatedBook],
    vocabulary: Vocabulary,
    weights: Weights,
) -> TasteForm:
    """Die Geschmacksform: aus den Büchern gelernt, das Getippte als Startwert.

    Zustimmung wird über die gemochten Bücher summiert. Ablehnung zählt je
    enttäuschendem Buch getrennt, und für jedes Merkmal das stärkste
    (MultiNeg, Wang/Fang/Zhai 2008): zwei enttäuschende Bücher mit demselben
    Merkmal lehnen es nicht doppelt ab. Wie stark ein enttäuschendes Buch
    gegenüber einem durchschnittlichen gemochten wiegt, ist das Verhältnis
    des Rocchio-Verfahrens (γ/β).
    """

    def family_of(term: str) -> str:
        return vocabulary.family_of(term).id

    genre_rules = tuple(c for c in profile.counterweights if c.genre)
    limited = {(book, f) for c in genre_rules for book in c.books for f in c.families}
    liked_books = sum(1 for r in rated if r.sign > 0)
    n = max(1, liked_books)

    agree_family: dict[str, float] = defaultdict(float)
    agree_term: dict[str, float] = defaultdict(float)
    reject_family: dict[str, float] = defaultdict(float)
    reject_term: dict[str, float] = defaultdict(float)
    for book in rated:
        for term, w in book.terms.items():
            f = family_of(term)
            if f in book.dropped:
                continue  # das Buch war für sie nicht so (Z10)
            if book.sign > 0:
                agree_family[f] += w
                agree_term[term] += w
            elif (book.title, f) not in limited:
                # An diesem Buch hat die Leserin die Ablehnung auf ein Genre
                # beschränkt; dann gilt die Regel, nicht die Form.
                reject_family[f] = max(reject_family[f], w)
                reject_term[term] = max(reject_term[term], w)
        # Was sie selbst nennt, wiegt wie ein prägendes Merkmal; es gilt der
        # Familie, weil sie in Familien spricht, nicht in Merkmalen.
        for f in book.added:
            if book.sign > 0:
                agree_family[f] += weights.reader_reason
            else:
                reject_family[f] = max(reject_family[f], weights.reader_reason)
    lam = weights.rejection_ratio * n
    for f, w in reject_family.items():
        agree_family[f] -= lam * w
    for term, w in reject_term.items():
        agree_term[term] -= lam * w

    # Eine Facette ist eine Kombination gemochter Merkmale; ihre Familien
    # starten als gemocht, auch wenn sie nicht einzeln angetippt sind.
    prior: dict[str, float] = {
        f: weights.prior_liked for facet in profile.facets for f in facet.families
    }
    for g in profile.liked:
        prior[g.family] = weights.prior_boosted if g.boosted else weights.prior_liked
    for c in profile.counterweights:
        if not c.genre:
            for f in c.families:
                prior[f] = -weights.prior_against
    # Was sie selbst zu einem Buch nennt, ist eine Aussage wie ein Tipp: es
    # startet wie ein angetipptes Merkmal oder Gegengewicht.
    for book in rated:
        for f in book.added:
            if book.sign > 0:
                prior[f] = max(prior.get(f, 0.0), weights.prior_liked)
            else:
                prior[f] = min(prior.get(f, 0.0), -weights.prior_against)

    k = weights.prior_books
    family = {
        f: (agree_family.get(f, 0.0) + k * prior.get(f, 0.0)) / (n + k)
        for f in set(agree_family) | set(prior)
    }
    kt = weights.term_to_family
    term = {
        t: (e + kt * family[family_of(t)] * n) / (n + kt * n) for t, e in agree_term.items()
    }
    # Ein typisches Gemochtes zählt voll: skaliert wird auf ein Quantil der
    # Vorlieben, nicht auf die stärkste, sonst drückte ein Ausreißer alles.
    positive = sorted(v for v in family.values() if v > 0.02)
    top = positive[int(len(positive) * weights.full_quantile)] if positive else 1.0

    def scaled(v: float) -> float:
        return max(-1.0, min(1.0, v / top))

    return TasteForm(
        family={f: scaled(v) for f, v in family.items()},
        term={t: scaled(v) for t, v in term.items()},
        known=frozenset(family) | {f for c in genre_rules for f in c.families},
        genre_rules=genre_rules,
    )


def overlap(
    portrait: Portrait,
    profile: ReadingProfile,
    form: TasteForm,
    vocabulary: Vocabulary,
    weights: Weights,
) -> Overlap | None:
    """Wie gut das Buch passt — oder ``None``, wenn nicht geurteilt wird.

    Nicht geurteilt wird über ein Buch, das das Modell nicht kennt, und ohne
    eine Form, die etwas weiß (ADR 33, Punkt 8).
    """
    if not portrait.known or not any(v > 0 for v in form.family.values()):
        return None
    terms = book_terms(portrait, vocabulary, weights)
    inside = outside = mass = 0.0
    p_inside = p_outside = p_mass = 0.0
    named: dict[str, float] = {}
    for term, w in terms.items():
        f = vocabulary.family_of(term).id
        if f not in form.known:
            continue  # darüber weiß die Form nichts (Z2)
        v = form.value(term, f)
        named[f] = max(named.get(f, v), v) if v >= 0 else min(named.get(f, v), v)
        if is_pattern(f, vocabulary):
            # Die zweite Spinne: ein Muster trägt kein Gewicht im Buch; es
            # steht nur da, wenn es die Geschichte trägt.
            p_mass += 1.0
            p_inside += max(v, 0.0)
            p_outside += max(-v, 0.0)
        else:
            mass += w
            inside += w * max(v, 0.0)
            outside += w * max(-v, 0.0)

    # Geglättet: ein dünner Steckbrief bleibt vorsichtig (Z6).
    a, p0 = weights.smoothing, weights.baseline
    share = max(0.0, (inside - outside + a * p0) / (mass + a))
    pattern = 0.0
    if p_mass:
        ap = weights.pattern_smoothing
        pattern = (p_inside - p_outside + ap * p0) / (p_mass + ap)
    share = 1 - (1 - share) * (1 - weights.pattern_for * max(pattern, 0.0))

    families = {vocabulary.family_of(t).id for t in terms}
    hits = [facet for facet in profile.facets if set(facet.families) <= families]
    if hits:
        share = 1 - (1 - share) * (1 - weights.facet_bonus)
    share *= 1 - weights.pattern_against * max(-pattern, 0.0)
    rules = [c for c in form.genre_rules if set(c.families) <= families
             and genre_matches(c, portrait)]
    for rule in rules:
        strength = min(
            max(w for t, w in terms.items() if vocabulary.family_of(t).id == f)
            for f in rule.families
        )
        share *= 1 - weights.genre_counterweight * strength
    share = max(0.0, min(1.0, share))

    return Overlap(
        share=share,
        stars=weights.stars(share),
        reasons=_reasons(portrait, profile, hits, named, rules, vocabulary),
    )


def _reasons(
    portrait: Portrait,
    profile: ReadingProfile,
    hits: Sequence,
    named: Mapping[str, float],
    rules: Sequence[Counterweight],
    vocabulary: Vocabulary,
) -> tuple[Reason, ...]:
    """Die Begründung aus Daten: die ganze Facette, was gemocht ist, was dagegen spricht.

    Jede Marke trägt darunter den Satz aus dem Steckbrief. Ein Merkmal, das
    schon in einer getroffenen Facette steht, bekommt keine eigene Marke.
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

    boosted = {g.family for g in profile.liked if g.boosted}
    lines: list[Reason] = []
    for facet in hits:
        lines.append(Reason("ganz", family_names(facet.families, vocabulary)))
        lines.extend(evidence_for(facet.families))
    in_hits = {f for facet in hits for f in facet.families}
    liked = [f for f, v in named.items() if v >= NAMED_FROM and f not in in_hits]
    # Verstärktes zuerst, dann Merkmale vor Erzählmustern, dann das Stärkere.
    liked.sort(key=lambda f: (f not in boosted, is_pattern(f, vocabulary), -named[f]))
    for f in liked:
        kind = "muster" if is_pattern(f, vocabulary) else "merkmal"
        lines.append(Reason(kind, family_name(f, vocabulary), f in boosted))
        lines.extend(evidence_for((f,)))
    if not hits and not liked:
        lines.append(Reason("keine", "nichts Gemochtes getroffen"))
    against = sorted((f for f, v in named.items() if v <= -NAMED_FROM), key=lambda f: named[f])
    for f in against:
        lines.append(Reason("dagegen", family_name(f, vocabulary)))
        lines.extend(evidence_for((f,)))
    for rule in rules:
        lines.append(Reason("dagegen", f"{family_names(rule.families, vocabulary)} "
                                       f"(bei {rule.genre})"))
        lines.extend(evidence_for(rule.families))
    return tuple(lines)
