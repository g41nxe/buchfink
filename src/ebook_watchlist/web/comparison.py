"""Der Abgleich auf der Buchseite: Buch und Leseprofil nebeneinander (26.09.2026).

Die volle Spinne beantwortet „wie sieht mein Geschmack aus“, nicht „passt
dieses Buch“: vier von 44 Plätzen zählen, und sie liegen verstreut. Aus sieben
Entwürfen gewählt (docs/research/spinne-darstellung.md, Prototypen A–G):

- **Überblick** (Wolke): was das Buch ist — seine Familien je Dimension, groß
  was es prägt, in der Farbe deines Geschmacks.
- **Brücke**: was es von deinem Profil abdeckt — deine stärksten Vorlieben und
  Abneigungen links, das Buch rechts, Linien, wo sie sich treffen; und was du
  magst, das es nicht hat.
- **Wasserfall**: wie die Prozentzahl entsteht — aus ``Overlap.steps``, also
  aus derselben Rechnung wie das Urteil.

Hier wird nur gerechnet; wie es aussieht, sagt ``_comparison.html``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..facets import family_name, is_pattern
from ..judging import Judge
from ..portrait import Portrait
from ..taste_form import book_terms, overlap
from .spider import SECTOR_ORDER

#: Ab diesem Betrag spricht eine Familie für oder gegen das Buch; darunter ist
#: sie dir fast egal. Dieselbe Schwelle, ab der die Spinne eine Familie zeigt,
#: wäre zu fein: +0,2 als „magst du“ las sich im Entwurf falsch.
LIKED_FROM = 0.3
#: Wie viele Vorlieben und Abneigungen die Brücke links zeigt.
MOST_LIKED = 7
MOST_REJECTED = 3
PATTERNS = "Erzählmuster"

STEP_LABELS = {
    "baseline": "Grundwert",
    "pattern_baseline": "Grundwert der Muster",
    "facet": "Kombination getroffen",
    "pattern_against": "Muster dagegen",
    "genre": "Gegengewicht im Genre",
    "floor": "Untergrenze",
    "ceiling": "Obergrenze",
}


@dataclass(frozen=True, slots=True)
class Pill:
    family_id: str
    name: str
    weight: float
    weight_word: str
    #: Dein Wert für das, was das Buch trägt — ``None``, wenn die Form es nicht kennt.
    value: float | None
    #: ``for``, ``against``, ``indifferent`` oder ``unknown``.
    side: str


@dataclass(frozen=True, slots=True)
class Group:
    dimension: str
    pills: tuple[Pill, ...]


@dataclass(frozen=True, slots=True)
class Mine:
    family_id: str
    name: str
    value: float
    #: Trägt das Buch diese Familie?
    hit: bool


@dataclass(frozen=True, slots=True)
class Bridge:
    mine: tuple[Mine, ...]
    book: tuple[Pill, ...]
    #: (Index links, Index rechts, Seite) je Linie.
    links: tuple[tuple[int, int, str], ...]
    #: Was du magst und das Buch nicht hat.
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WaterfallRow:
    label: str
    delta: float
    kind: str
    #: Wo der Balken beginnt und endet, 0 bis 1.
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class Comparison:
    groups: tuple[Group, ...]
    #: Was das Buch am stärksten prägt (alle mit dem höchsten Gewicht).
    strongest: tuple[Pill, ...]
    #: Weitere Familien, die dafür sprechen, und alle, die dagegen sprechen.
    also_for: tuple[str, ...]
    against: tuple[str, ...]
    bridge: Bridge
    waterfall: tuple[WaterfallRow, ...]
    share: float


def _side(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= LIKED_FROM:
        return "for"
    if value <= -LIKED_FROM:
        return "against"
    return "indifferent"


def _dimension(family_id: str, judge: Judge) -> str:
    v = judge.vocabulary
    if is_pattern(family_id, v):
        return PATTERNS
    first = next(t for t in v.terms if v.family_of(t).id == family_id)
    return v.terms[first].dimension


def _weight_word(weight: float, judge: Judge) -> str:
    w = judge.weights
    words = ((w.defining, "prägend"), (w.clear, "deutlich"), (w.marginal, "am Rand"))
    return min(words, key=lambda pair: abs(pair[0] - weight))[1]


def _pills(portrait: Portrait, judge: Judge) -> list[Pill]:
    """Die Familien des Buchs: Gewicht im Buch und der Wert, mit dem das
    Urteil rechnet (der des stärksten Merkmals, wie ``overlap``)."""
    v, form = judge.vocabulary, judge.form
    carried: dict[str, float] = {}
    values: dict[str, float] = {}
    for term, weight in book_terms(portrait, v, judge.weights).items():
        f = v.family_of(term).id
        carried[f] = max(carried.get(f, 0.0), weight)
        if f in form.known:
            value = form.value(term, f)
            if abs(value) >= abs(values.get(f, 0.0)):
                values[f] = value
    return [
        Pill(f, family_name(f, v), w, _weight_word(w, judge), values.get(f), _side(values.get(f)))
        for f, w in carried.items()
    ]


def _with_ties(ranked: list[tuple[str, float]], most: int) -> list[tuple[str, float]]:
    """Die ersten ``most`` — und alle, die genauso stark sind wie der letzte.

    Oben gekappt stehen oft acht Familien bei +1,0; bei sieben abzuschneiden
    ließe eine gleich starke Vorliebe zufällig weg (*figurengetrieben* bei
    *Achtsam morden*, 26.09.2026).
    """
    if len(ranked) <= most:
        return ranked
    cut = abs(ranked[most - 1][1])
    return [(f, x) for f, x in ranked if abs(x) >= cut]


def _bridge(pills: list[Pill], judge: Judge) -> Bridge:
    v, form = judge.vocabulary, judge.form
    order = {f.id: i for i, f in enumerate(v.families)}
    ranked = sorted(form.family.items(), key=lambda fv: (-fv[1], order.get(fv[0], 999)))
    liked = _with_ties([(f, x) for f, x in ranked if x >= LIKED_FROM], MOST_LIKED)
    rejected = _with_ties(
        [(f, x) for f, x in reversed(ranked) if x <= -LIKED_FROM], MOST_REJECTED)[::-1]
    carried = {p.family_id for p in pills}
    mine = tuple(Mine(f, family_name(f, v), x, f in carried) for f, x in liked + rejected)
    book = tuple(sorted(pills, key=lambda p: -p.weight))
    right = {p.family_id: i for i, p in enumerate(book)}
    links = tuple(
        (i, right[m.family_id], "for" if m.value > 0 else "against")
        for i, m in enumerate(mine) if m.hit
    )
    missing = tuple(m.name for m in mine if m.value > 0 and not m.hit)
    return Bridge(mine, book, links, missing)


def _waterfall(portrait: Portrait, judge: Judge) -> tuple[tuple[WaterfallRow, ...], float]:
    result = overlap(portrait, judge.profile, judge.form, judge.vocabulary, judge.weights)
    if result is None:
        return (), 0.0
    rows, at = [], 0.0
    for step in result.steps:
        if step.kind in ("family", "pattern"):
            label = family_name(step.family, judge.vocabulary)
            if step.kind == "pattern":
                label += " · Muster"
        else:
            label = STEP_LABELS.get(step.kind, step.kind)
        rows.append(WaterfallRow(label, step.delta, step.kind, at, at + step.delta))
        at += step.delta
    return tuple(rows), result.share


def compare(portrait: Portrait, judge: Judge) -> Comparison | None:
    """Der Abgleich dieses Buchs mit dem Leseprofil — ohne Form keiner."""
    if judge.form is None or not portrait.known:
        return None
    pills = _pills(portrait, judge)
    if not pills:
        return None
    groups = []
    for dimension in (*SECTOR_ORDER, PATTERNS):
        own = sorted((p for p in pills if _dimension(p.family_id, judge) == dimension),
                     key=lambda p: -p.weight)
        if own:
            groups.append(Group(dimension, tuple(own)))
    known = [p for p in pills if p.value is not None]
    top = max((p.weight for p in known), default=0.0)
    strongest = tuple(p for p in known if p.weight == top)
    waterfall, share = _waterfall(portrait, judge)
    return Comparison(
        groups=tuple(groups),
        strongest=strongest,
        also_for=tuple(p.name for p in pills if p.side == "for" and p not in strongest),
        against=tuple(p.name for p in pills if p.side == "against"),
        bridge=_bridge(pills, judge),
        waterfall=waterfall,
        share=share,
    )
