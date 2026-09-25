"""Prüfstand mit synthetischen Leserinnen (#79, docs/research/urteil-methode.md, 13).

Die echte Leserin ist eine Stichprobe von eins, und ihr Urteil über die meisten
Bücher kennen wir nicht. Hier bekommt jede synthetische Leserin einen *wahren
Geschmack* als Regel über die Familien eines Steckbriefs. Die Regeln sind
absichtlich keine gewichteten Summen, sondern Kombinationen und Richtungen —
sonst prüfte der Prüfstand nur, ob die Methode sich selbst ähnelt.

Jede Leserin tippt, was sie mag (drei Familien) und was sie stört (eine), und
bewertet *k* Bücher aus dem Pool, die sie kennt. Dann urteilt die Rechnung über
die übrigen Bücher. Gemessen wird am Tor (ab drei Sternen):

- **Treffsicherheit**: Anteil der durchgelassenen Bücher, die sie mag.
- **Ausbeute**: Anteil der Bücher, die sie mag, die durchkommen.
- **Ablehnung**: Anteil der Bücher, die sie nicht mag, die zurückgehalten werden.

Verglichen werden die alte Rechnung (``alte_rechnung.py``, mit Facetten aus den
bewerteten Büchern) und die Formüberdeckung, wie sie im Code steht.

Pool: alle bekannten Steckbriefe der Datenbank zum geltenden Vokabular und die
Gegenproben. Liest nur; kein Modellaufruf.

Aufruf: ``uv run python docs/research/prototyp/synthetische_leser.py AUSGABE.json``;
die Varianten der Formüberdeckung stehen in ``VARIANTS`` (Abweichungen vom
Bewertungsschema).
"""

import json
import random
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent))
from alte_rechnung import Weights as OldWeights  # noqa: E402
from alte_rechnung import fit as old_fit  # noqa: E402

from ebook_watchlist import paths  # noqa: E402
from ebook_watchlist.facets import (  # noqa: E402
    Counterweight,
    Facet,
    Liked,
    ReadingProfile,
    derive_facets,
    is_pattern,
    load_weights,
)
from ebook_watchlist.portrait import Portrait, Trait, fingerprint, load_vocabulary  # noqa: E402
from ebook_watchlist.store import PortraitRow, Store, _portrait_of  # noqa: E402
from ebook_watchlist.taste_form import RatedBook, book_terms, learn, overlap  # noqa: E402

OUT = sys.argv[1]
V, W, OLD = load_vocabulary(), load_weights(), OldWeights()
STAMP = fingerprint(V)
RUNS = 40
random.seed(11)
#: Varianten der Formüberdeckung: Name → Abweichung vom Bewertungsschema.
VARIANTS = {
    "stärkstes 0,2": {"rejection_mean": False, "rejection_ratio": 0.2},
    "gemittelt 0,2": {"rejection_mean": True, "rejection_ratio": 0.2},
    "gemittelt 0,33": {"rejection_mean": True, "rejection_ratio": 0.33},
}


# --- der Pool ----------------------------------------------------------------------


def _pool() -> list[Portrait]:
    store = Store(paths.db_path())
    with store.session() as session:
        rows = list(
            session.scalars(
                select(PortraitRow)
                .where(PortraitRow.fingerprint == STAMP)
                .order_by(PortraitRow.created_at, PortraitRow.id)
            )
        )
    latest = {r.subject: _portrait_of(r) for r in rows}
    books, seen = [], set()
    for p in latest.values():
        key = (p.title or "").casefold()
        if p.known and key and key not in seen:
            seen.add(key)
            books.append(p)
    probe_file = paths.db_path().parent / "research" / "gegenproben.json"
    if probe_file.exists():
        for d in json.loads(probe_file.read_text(encoding="utf-8")):
            d = {k: v for k, v in d.items() if k != "expect"}
            d["traits"] = tuple(Trait(**t) for t in d["traits"])
            d["violations"] = ()
            books.append(Portrait(**d))
    return books


POOL = _pool()


def families(p: Portrait) -> dict[str, float]:
    """Familie → stärkstes Gewicht im Buch."""
    out: dict[str, float] = {}
    for term, w in book_terms(p, V, W).items():
        f = V.family_of(term).id
        out[f] = max(out.get(f, 0.0), w)
    return out


# --- die Leserinnen ------------------------------------------------------------------


@dataclass(frozen=True)
class Reader:
    name: str
    #: Die Regel: gibt +1 (mag), −1 (mag nicht) oder 0 (egal) für ein Buch.
    rule: object
    #: Was sie antippt (drei) und was sie als Gegengewicht nennt (eine).
    taps: tuple[str, ...]
    against: tuple[str, ...]


def _has(fams, *ids, strong=0.0):
    return any(fams.get(f, 0.0) > strong for f in ids)


def krimi(f):
    """Düster und spannend, aber nicht witzig — eine Kombination."""
    if _has(f, "funny", "romantic", "warm"):
        return -1
    if _has(f, "harsh", "menacing", "brooding") and _has(f, "nerve_racking", "fast"):
        return 1
    return -1 if _has(f, "leisurely", "lyrical") else 0


def zwei_richtungen(f):
    """Düstere Spannung ODER warmer Witz — zwei Richtungen, die sich nicht mischen."""
    dunkel = _has(f, "harsh", "menacing") and _has(f, "nerve_racking")
    warm = _has(f, "funny") and _has(f, "likeable", "warm", "odd_character")
    if dunkel or warm:
        return 1
    return -1 if _has(f, "leisurely", "descriptive") else 0


def ideen(f):
    """Große Ideen, gern große Welt — aber nicht gemächlich (die Schwarm-Regel)."""
    if _has(f, "thought_provoking") and not _has(f, "leisurely"):
        return 1
    if _has(f, "big_world") and _has(f, "leisurely"):
        return -1
    return -1 if _has(f, "romantic") else 0


def figuren(f):
    """Figuren vor Handlung; blutige Härte stört, egal wie gut der Rest ist."""
    if f.get("harsh", 0) >= 1.0:
        return -1
    if _has(f, "character_driven", "complex", "brooding"):
        return 1
    return -1 if _has(f, "plot_driven") else 0


def muster(f):
    """Liest nach der Geschichte: Rätsel und Katz und Maus, nie Heldenreise."""
    if _has(f, "quest"):
        return -1
    return 1 if _has(f, "riddle", "pursuit") else 0


READERS = [
    Reader("Krimi (Kombination)", krimi, ("harsh", "menacing", "nerve_racking"), ("funny",)),
    Reader("zwei Richtungen", zwei_richtungen, ("nerve_racking", "funny", "harsh"),
           ("leisurely",)),
    Reader("Ideen, nicht gemächlich", ideen, ("thought_provoking", "big_world", "intricate"),
           ("leisurely",)),
    Reader("Figuren, keine Härte", figuren, ("character_driven", "brooding", "complex"),
           ("plot_driven",)),
    Reader("nach Erzählmuster", muster, ("riddle", "pursuit", "brooding"), ("quest",)),
]


# --- die Rechnungen ------------------------------------------------------------------


def profile_of(reader: Reader, liked_books: list[Portrait]) -> ReadingProfile:
    liked = tuple(Liked(f) for f in reader.taps if f in {x.id for x in V.families} or f in V.terms)
    carriers: dict[str, list[str]] = {}
    for i, p in enumerate(liked_books):
        for f in families(p):
            carriers.setdefault(f, []).append(str(i))
    terms = [g.family for g in liked if not is_pattern(g.family, V)]
    facets = tuple(Facet(x.families, x.books) for x in derive_facets(terms, carriers))
    return ReadingProfile(
        facets=facets,
        counterweights=tuple(Counterweight((f,)) for f in reader.against),
        liked=liked,
    )


def judge_old(profile, p):
    r = old_fit(p, profile, V, OLD)
    return None if r is None else r.stars


def judge_new(profile, form, p, weights=W):
    r = overlap(p, profile, form, V, weights)
    return None if r is None else r.stars


def _mean(rows, i):
    vals = [r[i] for r in rows if r[i] is not None]
    return round(100 * statistics.mean(vals)) if vals else None


def run(reader: Reader, k: int, noise: float = 0.0) -> dict:
    truth = {id(p): reader.rule(families(p)) for p in POOL}
    liked = [p for p in POOL if truth[id(p)] > 0]
    disliked = [p for p in POOL if truth[id(p)] < 0]
    stats = {"alt": [], **{name: [] for name in VARIANTS}}
    for _ in range(RUNS):
        n_like = min(len(liked) - 2, max(1, round(k * 0.7)))
        n_dis = min(len(disliked) - 2, k - n_like)
        read = random.sample(liked, n_like) + random.sample(disliked, max(0, n_dis))
        rated = []
        for p in read:
            sign = 1 if truth[id(p)] > 0 else -1
            if random.random() < noise:
                sign = -sign  # sie irrt sich oder das Modell beschreibt falsch
            rated.append(RatedBook(p.title or "?", sign, book_terms(p, V, W), p.genre))
        profile = profile_of(reader, [p for p in read if truth[id(p)] > 0])
        rest = [p for p in POOL if p not in read and truth[id(p)] != 0]
        judges = [("alt", lambda p, pr=profile: judge_old(pr, p))]
        for name, change in VARIANTS.items():
            w = replace(W, **change)
            fo = learn(profile, rated, V, w)
            judges.append((name, lambda p, pr=profile, fo=fo, w=w: judge_new(pr, fo, p, w)))
        for name, judge in judges:
            passed = [p for p in rest if (judge(p) or 0) >= W.gate_stars]
            good = [p for p in rest if truth[id(p)] > 0]
            bad = [p for p in rest if truth[id(p)] < 0]
            stats[name].append((
                sum(truth[id(p)] > 0 for p in passed) / len(passed) if passed else None,
                sum(p in passed for p in good) / len(good) if good else None,
                sum(p not in passed for p in bad) / len(bad) if bad else None,
            ))
    out = {"mag": len(liked), "mag_nicht": len(disliked)}
    for name, rows in stats.items():
        out[name] = {
            label: _mean(rows, i)
            for i, label in enumerate(("treffsicher", "ausbeute", "ablehnung"))
        }
    return out


results = {"pool": len(POOL), "runs": RUNS, "leserinnen": {}}
for reader in READERS:
    rows = {}
    for k in (5, 10, 20):
        rows[f"k={k}"] = run(reader, k)
    rows["k=10, 15 % Irrtum"] = run(reader, 10, noise=0.15)
    results["leserinnen"][reader.name] = rows

json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"Pool {results['pool']} Bücher, je {RUNS} Durchgänge")
print("Werte in %: Treffsicherheit / Ausbeute / Ablehnung am Tor (ab 3★)")
for name, rows in results["leserinnen"].items():
    first = next(iter(rows.values()))
    print(f"\n{name}  (mag {first['mag']}, mag nicht {first['mag_nicht']})")
    for label, r in rows.items():
        cells = [
            f"{name} {r[name]['treffsicher']}/{r[name]['ausbeute']}/{r[name]['ablehnung']}"
            for name in ("alt", *VARIANTS)
        ]
        print(f"  {label:<18} " + " | ".join(cells))
