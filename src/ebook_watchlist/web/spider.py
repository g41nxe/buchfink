"""Die Spinnen: die Geschmacksform im Kreis, ein Buch darübergelegt (#79).

Seit dem 26.09.2026 vollständig (docs/research/spinne-darstellung.md). Vorher
standen höchstens zwölf Achsen da, die stärksten — die Form täuschte
Vollständigkeit vor und ließ 17 von 29 bekannten Familien weg.

- **Ein fester Platz je Familie**, auch für die, über die die Form noch nichts
  weiß: ein leerer Platz heißt *unbekannt*, ein Punkt auf dem Ring *egal*.
  Fehlendes wegzulassen schadet dem Verständnis am meisten (Song & Szafir 2018),
  und feste Plätze lernt man (Diehl et al. 2010).
- **Ein Sektor je Dimension**, mit einer Lücke davor; die erste liegt oben und
  markiert den Anfang. Innerhalb eines Sektors steht eine Familie, die auch zu
  einer Nachbardimension gehört, an deren Grenze, und ein Gegensatzpaar
  nebeneinander.
- **Balken statt Fläche**: vom Ring *egal* nach außen (gemocht) oder innen
  (abgelehnt), linear im Radius, gleich breit. Ein Polygon hängt von der
  Reihenfolge der Achsen ab und lässt urteilen nach der Form statt nach den
  Werten (Fuchs et al. 2014, Few 2005) — deshalb auch kein Umriss.
- **Das Buch** ist eine bernsteinfarbene Spur außerhalb des Randes, so lang wie
  es die Familie trägt; was es nicht trägt, tritt zurück. Der Balken zeigt
  überall den Wert der Familie, damit sie auf Profil- und Buchseite gleich
  aussieht; womit das Urteil rechnete, zeigt ein Querstrich, wo es abweicht.

Hier wird nur gerechnet, wo was liegt; wie es aussieht, sagt ``_spider.html``.
Winkel im Uhrzeigersinn ab zwölf Uhr, der Mittelpunkt liegt bei (0, 0).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..facets import Weights, family_name
from ..portrait import Family, Portrait, Vocabulary
from ..taste_form import TasteForm, book_terms

#: Die Reihenfolge der Sektoren im Uhrzeigersinn. So stehen vier der fünf
#: Familien, die zu zwei Dimensionen gehören, an der Grenze zu ihrer zweiten
#: (die Dateireihenfolge schafft eine; Abschnitt 7.2 der Recherche).
SECTOR_ORDER = ("Tempo", "Handlung", "Stil", "Stimmung", "Figuren")

#: Die Maße im Koordinatensystem der Zeichnung.
R_ZERO = 60.0  # der Ring „egal"
SCALE = 36.0  # je Wertpunkt: −1 bei 24, +1 bei 96
R_RIM = 100.0  # der Rand
R_TRACK = 102.0  # dort beginnt die Spur des Buchs
TRACK = 7.0  # ihre Länge bei vollem Gewicht
R_LABEL = 112.0  # dort beginnen die Namen
GAP = 1.5  # eine Lücke vor jedem Sektor, in Plätzen

#: Unter diesem Betrag ist ein Wert *egal*: ein Punkt auf dem Ring, kein Balken.
EGAL = 0.05
#: Ab hier widerspricht ein Merkmal seiner Familie so, dass es einen Strich bekommt.
CONTRADICTS = 0.15
#: Ab dieser Abweichung zeigt die Buchseite, womit das Urteil rechnete.
VERDICT_OFF = 0.1
#: Mit weniger bekannten Familien sagt eine Spinne nichts.
FEWEST_KNOWN = 3


def radius(value: float) -> float:
    """−1 innen, 0 auf dem Ring, +1 am Rand — linear."""
    return R_ZERO + SCALE * max(-1.0, min(1.0, value))


def _at(angle: float, r: float) -> tuple[float, float]:
    theta = math.radians(angle)
    return r * math.sin(theta), -r * math.cos(theta)


def _across(angle: float, r: float, half: float) -> tuple[tuple[float, float], ...]:
    """Ein kurzer Strich quer zur Speiche, bei Radius ``r``."""
    x, y = _at(angle, r)
    theta = math.radians(angle)
    dx, dy = half * math.cos(theta), half * math.sin(theta)
    return (x - dx, y - dy), (x + dx, y + dy)


def _along(angle: float, r: float) -> tuple[tuple[float, float], float, str]:
    """Wo ein Name entlang der Speiche steht: Punkt, Drehung, Ausrichtung.

    Rechts lesbar von innen nach außen, links gedreht, damit nichts kopfsteht
    (wie Bostocks Sunburst).
    """
    if angle < 180:
        return (r, 0.0), angle - 90, "start"
    return (-r, 0.0), angle + 90, "end"


@dataclass(frozen=True, slots=True)
class Place:
    family_id: str
    name: str
    sector: str
    angle: float
    known: bool
    #: Der Wert der Familie, −1 bis 1 — ``None``, wenn die Form sie nicht kennt.
    value: float | None
    #: Balken vom Ring zu ``bar_to``, oder ``None`` (unbekannt oder egal).
    bar_from: tuple[float, float] | None
    bar_to: tuple[float, float] | None
    bar_radius: float
    #: Ein Punkt auf dem Ring: bekannt und egal.
    dot: tuple[float, float] | None
    #: ``accent`` gemocht, ``danger`` abgelehnt, ``soft`` egal oder unbekannt.
    tone: str
    #: Merkmale, die ihrer Familie widersprechen: je ein Strich und sein Ton.
    ticks: tuple[tuple[tuple[tuple[float, float], ...], str], ...]
    label_at: tuple[float, float]
    label_rotate: float
    label_anchor: str
    #: Eine unsichtbare, platzbreite Linie, damit der Hinweis sich treffen lässt.
    hit: tuple[tuple[float, float], tuple[float, float]]
    tooltip: str
    #: Nur auf der Buchseite.
    carried: bool = False
    track_length: float = 0.0
    track: tuple[tuple[float, float], tuple[float, float]] | None = None
    hollow: tuple[float, float] | None = None
    dimmed: bool = False
    verdict_value: float | None = None
    verdict_tick: tuple[tuple[float, float], ...] | None = None


@dataclass(frozen=True, slots=True)
class Sector:
    name: str
    #: Die Mitte der Lücke vor dem Sektor und die Mitte des Sektors, in Grad.
    gap_angle: float
    mid_angle: float
    #: Am Schreibtisch: der Name klein in der Lücke, entlang ihrer Mitte.
    inner_at: tuple[float, float]
    inner_rotate: float
    inner_anchor: str
    #: Auf dem Telefon: der Name waagerecht außen an der Sektormitte.
    outer_at: tuple[float, float]
    outer_anchor: str


@dataclass(frozen=True, slots=True)
class Spider:
    title: str
    places: tuple[Place, ...]
    sectors: tuple[Sector, ...]
    #: Familien des Buchs, über die die Form nichts weiß: sie zählen nicht.
    unknown: int = 0
    r_zero: float = R_ZERO
    r_min: float = R_ZERO - SCALE
    r_max: float = R_ZERO + SCALE
    r_rim: float = R_RIM

    @property
    def has_book(self) -> bool:
        return any(p.carried for p in self.places)

    @property
    def groups(self) -> tuple[tuple[str, tuple[Place, ...], tuple[str, ...]], ...]:
        """Für die Liste auf dem Telefon: je Sektor die bekannten Familien nach
        Wert und die Namen der unbekannten."""
        out = []
        for sector in self.sectors or (Sector(self.title, 0, 0, (0, 0), 0, "", (0, 0), ""),):
            own = [p for p in self.places if p.sector == sector.name]
            known = tuple(sorted((p for p in own if p.known), key=lambda p: -(p.value or 0.0)))
            unknown = tuple(p.name for p in own if not p.known)
            out.append((sector.name, known, unknown))
        return tuple(out)


def _all_families(vocabulary: Vocabulary, patterns: bool) -> list[Family]:
    """Jede Familie des Vokabulars einmal, in der Reihenfolge ihres ersten
    Merkmals in der Datei; ein Merkmal ohne Familie ist seine eigene."""
    seen: dict[str, Family] = {}
    for term_id in vocabulary.terms:
        family = vocabulary.family_of(term_id)
        if vocabulary.is_pattern(family.id) == patterns and family.id not in seen:
            seen[family.id] = family
    return list(seen.values())


def _sectors_and_order(
    families: list[Family], vocabulary: Vocabulary
) -> list[tuple[str, list[Family]]]:
    """Die Merkmalsfamilien je Sektor, in der Reihenfolge der drei Regeln."""
    by_name = {f.name: f.id for f in families}
    order = [d for d in SECTOR_ORDER if any(
        vocabulary.terms[f.members[0]].dimension == d for f in families)]
    rest = sorted({vocabulary.terms[f.members[0]].dimension for f in families} - set(order))
    order += rest
    out = []
    for i, sector in enumerate(order):
        before, after = order[i - 1], order[(i + 1) % len(order)]
        own = [f for f in families if vocabulary.terms[f.members[0]].dimension == sector]

        def other(f: Family, sector: str = sector) -> set[str]:
            return {vocabulary.terms[m].dimension for m in f.members} - {sector}

        front = [f for f in own if before in other(f)]
        back = [f for f in own if after in other(f) and f not in front]
        middle = [f for f in own if f not in front and f not in back]
        placed = front + middle + back
        # Gegensatzpaare nebeneinander: das Gegenteil rückt neben seinen Partner,
        # und zwar auf die Innenseite, wenn der Partner am Rand festsitzt.
        for f in list(placed):
            partner_id = by_name.get(f.opposite or "")
            partner = next((g for g in placed if g.id == partner_id), None)
            if partner is None or f not in placed:
                continue
            if abs(placed.index(f) - placed.index(partner)) == 1:
                continue
            pinned, moving = (f, partner) if (f in front or f in back) else (partner, f)
            if moving in front or moving in back:
                continue
            placed.remove(moving)
            at = placed.index(pinned)
            placed.insert(at if pinned in back else at + 1, moving)
        out.append((sector, placed))
    return out


def _tooltip(name: str, value: float | None, members: list[tuple[str, float]]) -> str:
    if value is None:
        head = f"{name}: noch unbekannt"
    elif abs(value) < EGAL:
        head = f"{name}: egal"
    else:
        word = "gemocht" if value > 0 else "abgelehnt"
        head = f"{name}: {word} ({value:+.1f})".replace(".", ",")
    tail = " · ".join(f"{n} {v:+.2f}".replace(".", ",") for n, v in members)
    return f"{head} · {tail}" if tail else head


def _spider(
    title: str,
    form: TasteForm,
    vocabulary: Vocabulary,
    patterns: bool,
    book: dict[str, float] | None = None,
    verdict: dict[str, float] | None = None,
) -> Spider | None:
    families = _all_families(vocabulary, patterns)
    if sum(1 for f in families if f.id in form.known) < FEWEST_KNOWN:
        return None
    grouped = (
        [(title, families)] if patterns else _sectors_and_order(families, vocabulary)
    )
    n = sum(len(fs) for _, fs in grouped)
    unit = 360.0 / (n + GAP * len(grouped))

    places: list[Place] = []
    sectors: list[Sector] = []
    cursor = 0.0
    for name, fams in grouped:
        gap_angle = cursor + GAP * unit / 2
        cursor += GAP * unit
        start = cursor
        for family in fams:
            angle = cursor + unit / 2
            cursor += unit
            places.append(_place(family, name, angle, unit, form, vocabulary, book, verdict))
        mid = (start + cursor) / 2
        inner_at, inner_rotate, inner_anchor = _along(gap_angle, R_ZERO - 30)
        ox, oy = _at(mid, R_LABEL - 2)
        sectors.append(Sector(
            name, gap_angle, mid, inner_at, inner_rotate, inner_anchor,
            (ox, oy + 4), "middle" if abs(ox) < 20 else ("start" if ox > 0 else "end"),
        ))
    unknown = (
        sum(1 for f in families if book and f.id in book and f.id not in form.known)
        if book is not None else 0
    )
    return Spider(title, tuple(places), tuple(sectors) if not patterns else (), unknown)


def _place(
    family: Family,
    sector: str,
    angle: float,
    unit: float,
    form: TasteForm,
    vocabulary: Vocabulary,
    book: dict[str, float] | None,
    verdict: dict[str, float] | None,
) -> Place:
    known = family.id in form.known
    value = form.family.get(family.id, 0.0) if known else None
    r = radius(value) if value is not None else R_ZERO
    bar = value is not None and abs(value) >= EGAL
    tone = "soft" if not bar else ("accent" if value > 0 else "danger")
    members = [
        (vocabulary.terms[t].name, form.term[t]) for t in family.members if t in form.term
    ]
    ticks = []
    if value is not None and abs(value) >= CONTRADICTS:
        for t in family.members:
            v = form.term.get(t)
            if v is not None and v * value < 0 and abs(v) >= CONTRADICTS:
                ticks.append((_across(angle, radius(v), 2.5),
                              "accent" if v > 0 else "danger"))
    label_at, label_rotate, label_anchor = _along(angle, R_LABEL)
    carried = book is not None and family.id in book
    weight = book.get(family.id, 0.0) if book else 0.0
    verdict_value = (verdict or {}).get(family.id) if carried else None
    verdict_tick = (
        _across(angle, radius(verdict_value), 3.5)
        if verdict_value is not None and value is not None
        and abs(verdict_value - value) >= VERDICT_OFF
        else None
    )
    return Place(
        family_id=family.id,
        name=family_name(family.id, vocabulary),
        sector=sector,
        angle=angle,
        known=known,
        value=value,
        bar_from=_at(angle, R_ZERO) if bar else None,
        bar_to=_at(angle, r) if bar else None,
        bar_radius=r,
        dot=_at(angle, R_ZERO) if known and not bar else None,
        tone=tone,
        ticks=tuple(ticks),
        label_at=label_at,
        label_rotate=label_rotate,
        label_anchor=label_anchor,
        hit=(_at(angle, R_ZERO - SCALE), _at(angle, R_RIM)),
        tooltip=_tooltip(family_name(family.id, vocabulary), value, members),
        carried=carried,
        track_length=TRACK * weight if carried and known else 0.0,
        track=(_at(angle, R_TRACK), _at(angle, R_TRACK + TRACK * weight))
        if carried and known else None,
        hollow=_at(angle, R_TRACK + TRACK / 2) if carried and not known else None,
        dimmed=book is not None and not carried,
        verdict_value=verdict_value,
        verdict_tick=verdict_tick,
    )


def reader_spiders(
    form: TasteForm, vocabulary: Vocabulary
) -> tuple[Spider | None, Spider | None]:
    """Die Geschmacksform: Merkmale und Erzählmuster, jede Familie an ihrem Platz."""
    return (
        _spider("Merkmale", form, vocabulary, patterns=False),
        _spider("Erzählmuster", form, vocabulary, patterns=True),
    )


def book_spiders(
    portrait: Portrait, form: TasteForm, vocabulary: Vocabulary, weights: Weights
) -> tuple[Spider | None, Spider | None]:
    """Das Buch über der Form: seine Spur außen, die Form wie auf der Profilseite.

    Wo das Buch eine Familie trägt, merkt sich der Platz den Wert, mit dem das
    Urteil gerechnet hat: den seines stärksten Merkmals — gezeigt als Strich,
    wo er vom Wert der Familie abweicht.
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
    return (
        _spider("Merkmale", form, vocabulary, False, carried, values),
        _spider("Erzählmuster", form, vocabulary, True, carried, values),
    )


def unknown_families(
    portrait: Portrait, form: TasteForm, vocabulary: Vocabulary, weights: Weights
) -> int:
    """Wie viele Familien des Buchs die Form nicht kennt — Merkmale und Muster."""
    families = {vocabulary.family_of(t).id for t in book_terms(portrait, vocabulary, weights)}
    return len(families - form.known)
