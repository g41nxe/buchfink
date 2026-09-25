"""Prototyp der Methode „Formüberdeckung" (docs/research/urteil-methode.md).

Lernt die Form der Leserin, urteilt, misst am Prüfstand. Liest die echte
Datenbank nur lesend; kein Modellaufruf. Aufruf: `uv run python
docs/research/prototyp/formueberdeckung.py AUSGABE.json [PARAMETER-JSON]`.
"""

import json
import random
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field, replace

from sqlalchemy import select

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.facets import (
    ReadingProfile,
    _genre_matches,
    fit,
    is_pattern,
)
from ebook_watchlist.judging import load_judge
from ebook_watchlist.portrait import Portrait, Trait
from ebook_watchlist.store import PortraitRow, Store, _portrait_of

store, settings = Store(paths.db_path()), load_settings()
judge = load_judge(store, settings.slug)
V, P6, W0 = judge.vocabulary, judge.profile, judge.weights
random.seed(3)

PAR = dict(
    w={"defining": 1.0, "clear": 0.7, "marginal": 0.4, None: 0.7},
    lam=1.5,  # ein enttäuschendes Buch wiegt 1,5-fach
    k=2.0,  # Vorab-Gewicht des Getippten (in Büchern gemessen)
    prior_boost=0.6,
    prior_tap=0.4,
    prior_against=-0.4,
    k_term=1.0,  # wie stark ein einzelnes Merkmal zur Familie hin geglättet wird
    alpha=4.0,
    p0=0.2,  # Glättung des Anteils bei dünner Beschreibung
    mu=0.35,  # bestes gemochtes Muster
    nu=0.5,  # stärkstes abgelehntes Muster
    beta=0.25,  # Facette ganz getroffen
    genre_cw=0.5,  # Gegengewicht mit Genre (Regel der Leserin)
    reason_w=1.0,  # Gewicht eines Grundes, den die Leserin selbst nennt
    stars=((5, 0.7), (4, 0.55), (3, 0.4), (2, 0.2)),
    q=0.75,  # welches Quantil der Vorlieben als „voll gemocht" gilt
    muster_spinne=True,  # Erzählmuster als zweite Spinne (False: nur „bestes Muster")
    alpha_p=1.0,
    neg_max=False,
    rocchio=None,  # γ/β; gesetzt ersetzt es lam (Literatur: 0,2 bis 0,33)  # Ablehnungen je Buch als Maximum statt als Summe  # Glättung der zweiten Spinne (ein Buch trägt 1–3 Muster)
)
if len(sys.argv) > 2:
    PAR.update(json.loads(sys.argv[2]))

FAM = {t: V.family_of(t).id for t in V.terms}
PAT = {f: is_pattern(f, V) for f in set(FAM.values())}


def book_terms(p):
    """Merkmal → Gewicht im Buch. Erzählmuster je Grundhandlung, oder mit der
    zweiten Spinne je Muster (Grundhandlung als Familie, wie bei den Merkmalen)."""
    out = {}
    for t in p.traits:
        if t.term in V.terms:
            spinne = PAR["muster_spinne"]
            key = FAM[t.term] if PAT[FAM[t.term]] and not spinne else t.term
            out[key] = max(out.get(key, 0), PAR["w"].get(t.weight, 0.7))
    return out


@dataclass
class Rated:
    title: str
    sign: int  # +1 Mag ich, −1 Doof
    terms: dict  # aus dem Steckbrief
    reasons_add: tuple = ()  # Gründe der Leserin (Z10), aus dem Vokabular
    reasons_drop: tuple = ()  # was sie anders erlebt hat (Z10)
    genre: str | None = None

    def effective(self):
        t = {
            k: v
            for k, v in self.terms.items()
            if k not in self.reasons_drop and FAM.get(k, k) not in self.reasons_drop
        }
        for r in self.reasons_add:
            t[r] = max(t.get(r, 0), PAR["reason_w"])
        return t


@dataclass
class Form:
    fam: dict = field(default_factory=dict)  # Familie → −1 … 1
    term: dict = field(default_factory=dict)  # Merkmal → −1 … 1
    known: set = field(default_factory=set)  # Familien, zu denen es irgendeine Angabe gibt
    genre_rules: tuple = ()  # Gegengewichte mit Genre


def learn(profile, rated):
    """Die Form der Leserin: aus ihren Büchern gelernt, das Getippte als Startwert."""
    genre_rules = tuple(c for c in profile.counterweights if c.genre)
    genre_fams = {f for c in genre_rules for f in c.families}
    limited = {(b, f) for c in genre_rules for b in c.books for f in c.families}
    n = max(1, sum(1 for r in rated if r.sign > 0))
    e_f, e_t = defaultdict(float), defaultdict(float)
    # Ablehnung je Buch getrennt; zusammengeführt als Summe oder als Maximum
    # (MultiNeg, Wang/Fang/Zhai 2008).
    neg_f, neg_t = defaultdict(float), defaultdict(float)
    for r in rated:
        for key, w in r.effective().items():
            f = FAM.get(key, key)
            if r.sign < 0 and (r.title, f) in limited and key not in r.reasons_add:
                continue  # an diesem Buch hat die Leserin die Ablehnung auf ein Genre beschränkt
            if r.sign > 0:
                e_f[f] += w
                e_t[key] += w
            elif PAR["neg_max"]:
                neg_f[f] = max(neg_f[f], w)
                neg_t[key] = max(neg_t[key], w)
            else:
                neg_f[f] += w
                neg_t[key] += w
    # Rocchio-Verhältnis γ/β: Zustimmung und Ablehnung je über ihre Bücher gemittelt.
    # Bei n gemochten und m enttäuschenden Büchern entspricht das λ = γ/β · n / m.
    m = max(1, sum(1 for r in rated if r.sign < 0))
    lam = PAR["rocchio"] * n / m if PAR["rocchio"] is not None else PAR["lam"]
    for f, w in neg_f.items():
        e_f[f] -= lam * w
    for key, w in neg_t.items():
        e_t[key] -= lam * w
    prior = {}
    for g in profile.liked:
        prior[g.family] = PAR["prior_boost"] if g.boosted else PAR["prior_tap"]
    for c in profile.counterweights:
        if not c.genre:
            for f in c.families:
                prior[f] = PAR["prior_against"]
    fam = {}
    for f in set(e_f) | set(prior):
        fam[f] = (e_f[f] + PAR["k"] * prior.get(f, 0.0)) / (n + PAR["k"])
    term = {}
    for key, e in e_t.items():
        f = FAM.get(key, key)
        term[key] = (e + PAR["k_term"] * fam[f] * n) / (n + PAR["k_term"] * n)
    pos = sorted(v for v in fam.values() if v > 0.02)
    top = pos[int(len(pos) * PAR["q"])] if pos else 1.0  # ein typisches Gemochtes zählt voll
    fam = {k: max(-1, min(1, v / top)) for k, v in fam.items()}
    term = {k: max(-1, min(1, v / top)) for k, v in term.items()}
    known = {f for f, v in fam.items()} | genre_fams
    return Form(fam, term, known, genre_rules)


def verdict(portrait, form, profile):
    """Übereinstimmung 0 … 1, dazu die Teile für die Begründung — oder None."""
    if not portrait.known or not form.known:
        return None
    bt = book_terms(portrait)
    inside = outside = mass = 0.0
    for key, w in bt.items():
        f = FAM.get(key, key)
        if PAT.get(f):
            continue
        if f not in form.known:
            continue  # darüber weißt du nichts: zählt weder dafür noch dagegen (Z2)
        v = form.term.get(key, form.fam.get(f, 0.0))
        mass += w
        inside += w * max(v, 0)
        outside += w * max(-v, 0)
    feat = (inside - outside + PAR["alpha"] * PAR["p0"]) / (mass + PAR["alpha"])
    if PAR["muster_spinne"]:
        # Zweite Spinne: dieselbe Rechnung über die Erzählmuster. Ein Muster
        # trägt kein Gewicht im Buch; es steht nur da, wenn es die Geschichte trägt.
        p_in = p_out = p_mass = 0.0
        for key in bt:
            f = FAM.get(key, key)
            if not PAT.get(f) or f not in form.known:
                continue
            v = form.term.get(key, form.fam.get(f, 0.0))
            p_mass += 1.0
            p_in += max(v, 0)
            p_out += max(-v, 0)
        # Weiß das Profil über keines der Muster etwas, sagt die zweite Spinne nichts.
        pat = (
            (p_in - p_out + PAR["alpha_p"] * PAR["p0"]) / (p_mass + PAR["alpha_p"])
            if p_mass
            else 0.0
        )
        pat_like, pat_dis = max(pat, 0), max(-pat, 0)
    else:
        pats = [f for f in bt if PAT.get(f)]
        pat_like = max([max(form.fam.get(f, 0), 0) for f in pats] + [0])
        pat_dis = max([max(-form.fam.get(f, 0), 0) for f in pats] + [0])
    share = 1 - (1 - max(feat, 0)) * (1 - PAR["mu"] * pat_like)
    fams = {FAM.get(k, k) for k in bt}
    if any(set(fc.families) <= fams for fc in profile.facets):
        share = 1 - (1 - share) * (1 - PAR["beta"])
    share *= 1 - PAR["nu"] * pat_dis
    for c in form.genre_rules:
        if all(f in fams for f in c.families) and _genre_matches(c, portrait):
            w = min(max(v for k, v in bt.items() if FAM.get(k, k) == f) for f in c.families)
            share *= 1 - PAR["genre_cw"] * w
    return max(0.0, min(1.0, share))


def stars(x):
    if x is None:
        return None
    return next((s for s, ab in PAR["stars"] if x >= ab - 1e-9), 1)


# --- Daten ------------------------------------------------------------------
with store.session() as sess:
    all_rows = list(sess.scalars(select(PortraitRow).order_by(PortraitRow.id)))
latest = {r.subject: _portrait_of(r) for r in all_rows}


def portrait_of(bid):
    b = store.book(bid)
    for s in (f"book:{bid}", f"isbn:{b.isbn}" if b.isbn else None):
        if s and s in latest and latest[s].known:
            return b.title, latest[s]
    return b.title, None


REASONS = {  # was die Leserin selbst gesagt hat (25.09.2026)
    "Der Schwarm": (("leisurely", "ensemble", "sweeping"), ("nerve_racking",)),
}
rated, rated_portraits = [], {}
for kind, sign in (("liked", 1), ("disliked", -1)):
    for rel in store.relations(settings.slug, kind=kind):
        t, p = portrait_of(rel.book_id)
        if p is None:
            continue
        add, drop = REASONS.get(t, ((), ()))
        rated.append(Rated(t, sign, book_terms(p), add, drop, p.genre))
        rated_portraits[t] = p

FULL = learn(P6, rated)
sample = [p for s, p in latest.items() if p.known and not s.startswith(("intake:", "book:"))]


def v0(p, prof=P6):
    r = fit(p, prof, V, W0)
    return None if r is None else r.share


def v0stars(x):
    return None if x is None else next((s for s, ab in W0.stars_from if x >= ab - 1e-9), 1)


def fmt(x, s):
    return "kein Urteil" if x is None else f"{s}★ {round(x * 100)} %"


out = {"par": {k: v for k, v in PAR.items() if k != "w"}}

# 1. eigene Bücher, jedes mit einer Form, die ohne dieses Buch gelernt wurde
loo = []
for r in rated:
    form = learn(P6, [x for x in rated if x is not r])
    p = rated_portraits[r.title]
    x = verdict(p, form, P6)
    loo.append(
        (
            ("Mag ich" if r.sign > 0 else "Doof"),
            r.title[:24],
            fmt(v0(p), v0stars(v0(p))),
            fmt(x, stars(x)),
        )
    )
out["loo"] = loo
out["mit_sich_selbst"] = [
    (
        ("Mag ich" if r.sign > 0 else "Doof"),
        r.title[:24],
        fmt(
            verdict(rated_portraits[r.title], FULL, P6),
            stars(verdict(rated_portraits[r.title], FULL, P6)),
        ),
    )
    for r in rated
]

# 2. Stichprobe
xs = [verdict(p, FULL, P6) for p in sample]
out["sample_pass"] = {
    "heute": sum(1 for p in sample if (v0stars(v0(p)) or 0) >= 3),
    "neu": sum(1 for x in xs if (stars(x) or 0) >= 3),
    "n": len(sample),
}
nf = [sum(1 for k in book_terms(p) if not PAT.get(FAM.get(k, k))) for p in sample]
out["length_corr"] = {
    "heute": round(statistics.correlation(nf, [v0(p) for p in sample]), 2),
    "neu": round(statistics.correlation(nf, xs), 2),
}


def thin(p):
    feats = [t for t in p.traits if t.term in V.terms and not PAT[FAM[t.term]]]
    pats = [t for t in p.traits if t.term in V.terms and PAT[FAM[t.term]]]
    keep = random.sample(feats, max(1, round(len(feats) * 0.6))) if feats else []
    return replace(p, traits=tuple(keep + pats))


ch0 = ch1 = tot = 0
for _ in range(20):
    for p in sample:
        if sum(1 for t in p.traits if t.term in V.terms and not PAT[FAM[t.term]]) < 4:
            continue
        q = thin(p)
        tot += 1
        ch0 += v0stars(v0(p)) != v0stars(v0(q))
        ch1 += stars(verdict(p, FULL, P6)) != stars(verdict(q, FULL, P6))
out["stability"] = {"heute": f"{round(100 * ch0 / tot)} %", "neu": f"{round(100 * ch1 / tot)} %"}

# 3. schmale Profile (ohne Bücher, nur Getipptes)
empty = ReadingProfile(facets=(), counterweights=(), liked=())
merk = tuple(g for g in P6.liked if not PAT[g.family])
prof_rows = {}
for k in (1, 3, 5, 8, len(merk)):
    prof = replace(empty, liked=merk[:k])
    f = learn(prof, [])
    prof_rows[k] = (
        sum(1 for p in sample if (v0stars(v0(p, prof)) or 0) >= 3),
        sum(1 for p in sample if (stars(verdict(p, f, prof)) or 0) >= 3),
    )
out["narrow_profiles(heute,neu)"] = prof_rows

# 4. Szenarien gegen die volle Form
members = defaultdict(list)
for t in V.terms:
    members[FAM[t]].append(t)


def book(*keys, genre="Thriller", weights=None):
    tr = []
    for k in keys:
        term = k if k in V.terms and not (k in members and PAT.get(k)) else members[k][0]
        if k in members and not PAT.get(k):
            term = members[k][0]
        w = None if PAT.get(FAM[term]) else (weights or {}).get(k, "clear")
        tr.append(Trait(term, "S.", "wissen", w))
    return Portrait(known=True, fingerprint=judge.stamp, genre=genre, traits=tuple(tr))


S = [
    (
        "R1",
        "beide Facetten, nervenaufreibend, Rätsel",
        book(
            "brooding",
            "harsh",
            "menacing",
            "thought_provoking",
            "nerve_racking",
            "riddle",
            "intricate",
        ),
    ),
    (
        "R2",
        "eine Facette ganz, sonst neutral",
        book("brooding", "harsh", "sad", "offbeat", "dramatic"),
    ),
    ("R4b", "vier Merkmale, alle gemocht", book("character_driven", "antihero", "fast", "harsh")),
    (
        "R4c",
        "acht Merkmale, vier gemocht",
        book(
            "character_driven",
            "antihero",
            "fast",
            "harsh",
            "sad",
            "dramatic",
            "offbeat",
            "intricate",
        ),
    ),
    (
        "R5",
        "ein gemochtes Merkmal, vier andere",
        book("harsh", "sad", "dramatic", "offbeat", "ensemble"),
    ),
    (
        "R7a",
        "ein Muster (Rätsel) + drei gemochte",
        book("riddle", "character_driven", "antihero", "fast", "sad"),
    ),
    (
        "R7b",
        "drei Muster + dieselben drei",
        book("riddle", "pursuit", "escape", "character_driven", "antihero", "fast", "sad"),
    ),
    ("R7c", "nur Muster Rätsel, Merkmale neutral", book("riddle", "sad", "dramatic", "offbeat")),
    (
        "B3",
        "hart prägend + zwei gemocht",
        book("harsh", "antihero", "fast", "sad", weights={"harsh": "defining"}),
    ),
    (
        "B4",
        "hart am Rand + zwei gemocht",
        book("harsh", "antihero", "fast", "sad", weights={"harsh": "marginal"}),
    ),
    (
        "R10",
        "Facette + gemächlich prägend",
        book("brooding", "harsh", "leisurely", "sad", weights={"leisurely": "defining"}),
    ),
    (
        "R10b",
        "Facette + gemächlich am Rand",
        book("brooding", "harsh", "leisurely", "sad", weights={"leisurely": "marginal"}),
    ),
    (
        "Z11a",
        "episch angelegt (viele Schauplätze) + drei gemocht",
        book("sweeping", "character_driven", "antihero", "fast"),
    ),
    (
        "Z11b",
        "Weltenbau (Science-Fiction) + drei gemocht",
        book("world_building", "character_driven", "antihero", "fast", genre="Science-Fiction"),
    ),
    (
        "Z11c",
        "Weltenbau (Fantasy) + drei gemocht",
        book("world_building", "character_driven", "antihero", "fast", genre="Fantasy"),
    ),
    ("T1", "dünn: zwei Merkmale, beide gemocht, ein Muster", book("harsh", "brooding", "riddle")),
]
out["scenarios"] = [
    (k, t, fmt(v0(b), v0stars(v0(b))), fmt(verdict(b, FULL, P6), stars(verdict(b, FULL, P6))))
    for k, t, b in S
]

# 5. die Form selbst (für das Spinnennetz und die Anzeige)
out["form_top"] = sorted(((round(v, 2), f) for f, v in FULL.fam.items()), reverse=True)[:10]
out["form_bottom"] = sorted(((round(v, 2), f) for f, v in FULL.fam.items()))[:8]
out["terms_big_world"] = {
    t: round(FULL.term.get(t, FULL.fam.get("big_world", 0)), 2)
    for t in ("sweeping", "world_building")
}

json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for k, v in out.items():
    if k in ("loo", "scenarios", "mit_sich_selbst"):
        print(f"\n{k}:")
        for row in v:
            print("  |", " | ".join(row), "|")
    else:
        print(k, v)
