"""Die Spinnen: die Geschmacksform als Netz, ein Buch darübergelegt (#79).

Jede Achse ist eine Familie, über die die Form etwas weiß. Ein gestrichelter
Ring in der Mitte des Radius heißt *egal*: nach außen, was die Leserin mag,
nach innen, was sie ablehnt. Ein Buch liegt auf derselben Skala — auf dem
Ring, wo es eine Familie nicht trägt, darüber, so weit sie im Buch wiegt.
Ragt es in eine Einbuchtung der Form, spricht das dagegen.

Zwei Spinnen wie in der Rechnung: Merkmale und Erzählmuster. Gezeichnet
werden höchstens ``MOST_AXES`` Achsen, die stärksten; ein Netz mit fünfzig
Speichen liest niemand. Unter drei Achsen gibt es keine Spinne.

Hier wird nur gerechnet, wo was liegt; wie es aussieht, sagt ``_spider.html``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..facets import Weights, family_name, is_pattern
from ..portrait import Portrait, Vocabulary
from ..taste_form import TasteForm, book_terms

#: Wie viele Achsen eine Spinne höchstens hat.
MOST_AXES = 12
#: Wie stark eine Familie in der Form sein muss, um eine Achse zu bekommen.
#: Darunter ist sie so gut wie egal und machte das Netz nur voller.
AXIS_FROM = 0.15

#: Die Maße des Netzes im Koordinatensystem der Zeichnung.
CENTER = 150.0
RADIUS = 100.0


@dataclass(frozen=True, slots=True)
class Axis:
    family_id: str
    name: str
    #: Der Wert der Form, −1 bis 1.
    value: float
    reader_radius: float
    reader_point: tuple[float, float]
    #: Wo die Beschriftung steht und wie sie ausgerichtet ist.
    label_point: tuple[float, float]
    anchor: str
    #: Wie stark das Buch die Familie trägt, 0 bis 1 — nur auf der Buchseite.
    book: float | None = None
    book_radius: float | None = None
    book_point: tuple[float, float] | None = None
    #: Die Spitze der Speiche, für das Gitter.
    tip: tuple[float, float] = (0.0, 0.0)
    #: Wo auf schmalen Bildschirmen die Nummer der Achse steht: dort reicht
    #: der Platz nicht für die Namen, sie stehen in einer Liste darunter.
    number_point: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True, slots=True)
class Spider:
    title: str
    axes: tuple[Axis, ...]
    center: float = CENTER
    radius: float = RADIUS
    #: Familien des Buchs, über die die Form nichts weiß: sie zählen nicht.
    unknown: int = 0

    @property
    def neutral(self) -> float:
        return self.radius / 2

    @property
    def reader_points(self) -> str:
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in (a.reader_point for a in self.axes))

    @property
    def book_points(self) -> str:
        return " ".join(
            f"{x:.1f},{y:.1f}" for x, y in (a.book_point for a in self.axes if a.book_point)
        )

    @property
    def has_book(self) -> bool:
        return any(a.book_point for a in self.axes)


def _radius(value: float) -> float:
    """−1 in der Mitte, 0 auf dem Ring, 1 am Rand."""
    return RADIUS * (0.5 + 0.5 * max(-1.0, min(1.0, value)))


def _shifted(point: tuple[float, float], dy: float) -> tuple[float, float]:
    return point[0], point[1] + dy


def _point(index: int, count: int, radius: float) -> tuple[float, float]:
    angle = -math.pi / 2 + 2 * math.pi * index / count  # die erste Achse zeigt nach oben
    return CENTER + radius * math.cos(angle), CENTER + radius * math.sin(angle)


def _spider(
    title: str,
    chosen: list[str],
    form: TasteForm,
    vocabulary: Vocabulary,
    book: dict[str, float] | None = None,
    unknown: int = 0,
    values: dict[str, float] | None = None,
) -> Spider | None:
    if len(chosen) < 3:
        return None
    order = {name: i for i, (name, _) in enumerate(vocabulary.dimensions)}

    def dimension(f: str) -> int:
        try:
            first = vocabulary.family(f).members[0]
            return order.get(vocabulary.terms[first].dimension, len(order))
        except KeyError:
            return len(order)

    # Nach Dimension geordnet, damit Verwandtes nebeneinander liegt.
    chosen = sorted(chosen, key=lambda f: (dimension(f), family_name(f, vocabulary).casefold()))
    axes = []
    for i, f in enumerate(chosen):
        value = (values or {}).get(f, form.family.get(f, 0.0))
        r = _radius(value)
        lx, ly = _point(i, len(chosen), RADIUS + 12)
        dx = lx - CENTER
        anchor = "middle" if abs(dx) < 8 else ("start" if dx > 0 else "end")
        weight = None if book is None else book.get(f, 0.0)
        br = None if weight is None else _radius(weight)
        axes.append(
            Axis(
                f,
                family_name(f, vocabulary),
                value,
                r,
                _point(i, len(chosen), r),
                (lx, ly + 4),
                anchor,
                weight,
                br,
                None if br is None else _point(i, len(chosen), br),
                _point(i, len(chosen), RADIUS),
                _shifted(_point(i, len(chosen), RADIUS + 16), 6),
            )
        )
    return Spider(title, tuple(axes), unknown=unknown)


def _strongest(form: TasteForm, vocabulary: Vocabulary, patterns: bool) -> list[str]:
    fams = [
        f for f, v in form.family.items()
        if abs(v) >= AXIS_FROM and is_pattern(f, vocabulary) == patterns
    ]
    return sorted(fams, key=lambda f: -abs(form.family[f]))


def reader_spiders(
    form: TasteForm, vocabulary: Vocabulary
) -> tuple[Spider | None, Spider | None]:
    """Die Geschmacksform: Merkmale und Erzählmuster, je die stärksten Achsen."""
    return (
        _spider("Merkmale", _strongest(form, vocabulary, False)[:MOST_AXES], form, vocabulary),
        _spider("Erzählmuster", _strongest(form, vocabulary, True)[:MOST_AXES], form, vocabulary),
    )


def book_spiders(
    portrait: Portrait, form: TasteForm, vocabulary: Vocabulary, weights: Weights
) -> tuple[Spider | None, Spider | None]:
    """Das Buch über der Form: seine Familien zuerst, dann die stärksten der
    Form, bis die Spinne voll ist — so sieht man auch, was dem Buch fehlt.

    Wo das Buch eine Familie trägt, zeigt die Achse den Wert, mit dem das
    Urteil gerechnet hat: den seines stärksten Merkmals, nicht den der
    Familie. Sonst stünde eine Familie außen, die die Begründung darüber
    „dagegen" nennt.
    """
    carried: dict[str, float] = {}
    values: dict[str, float] = {}
    for term, w in book_terms(portrait, vocabulary, weights).items():
        f = vocabulary.family_of(term).id
        carried[f] = max(carried.get(f, 0.0), w)
        if f in form.known:
            v = form.value(term, f)
            if abs(v) >= abs(values.get(f, 0.0)):
                values[f] = v
    spiders = []
    for patterns, title in ((False, "Merkmale"), (True, "Erzählmuster")):
        own = [f for f in carried if is_pattern(f, vocabulary) == patterns]
        # Was im Buch am stärksten wiegt, bekommt zuerst eine Achse.
        known = sorted((f for f in own if f in form.known), key=lambda f: -carried[f])
        chosen = known[:MOST_AXES]
        for f in _strongest(form, vocabulary, patterns):
            if len(chosen) >= MOST_AXES:
                break
            if f not in chosen:
                chosen.append(f)
        spiders.append(
            _spider(
                title, chosen, form, vocabulary, carried, len(own) - len(known), values
            )
        )
    return spiders[0], spiders[1]


def unknown_families(
    portrait: Portrait, form: TasteForm, vocabulary: Vocabulary, weights: Weights
) -> int:
    """Wie viele Familien des Buchs die Form nicht kennt — Merkmale und Muster."""
    families = {vocabulary.family_of(t).id for t in book_terms(portrait, vocabulary, weights)}
    return len(families - form.known)
