"""Prototyp: Formüberdeckung mit mehreren Richtungen (docs/research/urteil-methode.md, 9–10).

Die gemochten Bücher werden zu Richtungen gruppiert (Bücher, die einander ähneln); je
Richtung eine Form, gelernt wie in ``formueberdeckung.py``, aber nur aus Zustimmung.
Ein Buch wird gegen die Richtung gemessen, die am besten passt. Abgelehnt wird über
die enttäuschenden Bücher selbst: wie viel des Buchs einem enttäuschenden Buch gleicht,
ohne in der gewählten Richtung gemocht zu sein (eine Ablehnung ist eine Kombination).

Aufruf: ``uv run python docs/research/prototyp/richtungen.py AUSGABE.json [PARAMETER-JSON]``.
Liest die Datenbank nur lesend; kein Modellaufruf.
"""

import contextlib
import io
import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = sys.argv[1]
EXTRA = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
DPAR = {"tau": 0.2, "nu_dir": 0.8, "liked_cut": 0.1}
DPAR.update({k: v for k, v in EXTRA.items() if k in DPAR})
base_par = {k: v for k, v in EXTRA.items() if k not in DPAR}

sys.argv = [str(HERE / "formueberdeckung.py"), OUT + ".basis.json", json.dumps(base_par)]
with contextlib.redirect_stdout(io.StringIO()):
    import runpy

    g = runpy.run_path(str(HERE / "formueberdeckung.py"))

learn, verdict, stars = g["learn"], g["verdict"], g["stars"]
FAM, PAT, P6 = g["FAM"], g["PAT"], g["P6"]
rated, portraits, sample = g["rated"], g["rated_portraits"], g["sample"]
v0, v0stars, thin, book_terms = g["v0"], g["v0stars"], g["thin"], g["book_terms"]
random.seed(5)


def fam_vec(terms):
    """Familie → Gewicht, Merkmale und Muster, für die Ähnlichkeit zweier Bücher."""
    out = {}
    for key, w in terms.items():
        f = FAM.get(key, key)
        out[f] = max(out.get(f, 0), w)
    return out


def similarity(a, b):
    """Gewichtetes Jaccard (Σ min / Σ max)."""
    keys = set(a) | set(b)
    top = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
    return sum(min(a.get(k, 0), b.get(k, 0)) for k in keys) / top if top else 0.0


def directions(liked):
    """Gruppen gemochter Bücher: zusammengelegt, solange die mittlere Ähnlichkeit
    zweier Gruppen über tau liegt (Average Linkage)."""
    groups = [[r] for r in liked]
    vec = {id(r): fam_vec(r.effective()) for r in liked}
    while len(groups) > 1:
        best, pair = -1.0, None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                s = statistics.mean(
                    similarity(vec[id(a)], vec[id(b)]) for a in groups[i] for b in groups[j]
                )
                if s > best:
                    best, pair = s, (i, j)
        if best < DPAR["tau"]:
            break
        i, j = pair
        groups[i] += groups.pop(j)
    return groups


def model(profile, rated_books):
    """Richtungen, ihre Formen und die enttäuschenden Bücher als Gegenbeispiele."""
    liked = [r for r in rated_books if r.sign > 0]
    disliked = [r for r in rated_books if r.sign < 0]
    known = learn(profile, rated_books).known
    groups = directions(liked) if liked else []
    forms = []
    for grp in groups or [[]]:
        f = learn(profile, grp)
        f.known = known
        forms.append((grp, f))
    negs = [
        {k: w for k, w in r.effective().items() if not PAT.get(FAM.get(k, k))} for r in disliked
    ]
    return forms, negs


def judge_dirs(portrait, profile, m):
    forms, negs = m
    best, best_form = None, None
    for _grp, form in forms:
        x = verdict(portrait, form, profile)
        if x is not None and (best is None or x > best):
            best, best_form = x, form
    if best is None:
        return None
    # Ablehnung je Merkmal, nicht je Familie: *episch angelegt* (Der Schwarm) ist
    # nicht *Weltenbau* (Otherland, Auslöschung), obwohl beide *große Welt* sind.
    # Deshalb kein Rückfall auf die Familie: gemocht ist nur, was als Merkmal gemocht ist.
    cand = {
        k: w
        for k, w in book_terms(portrait).items()
        if not PAT.get(FAM.get(k, k)) and FAM.get(k, k) in best_form.known
    }
    mass = sum(cand.values())
    if mass and negs:
        free = {k: w for k, w in cand.items() if best_form.term.get(k, 0) <= DPAR["liked_cut"]}
        overlap = max(sum(min(w, n.get(k, 0)) for k, w in free.items()) / mass for n in negs)
        best *= 1 - DPAR["nu_dir"] * overlap
    return best


out = {"par": {**DPAR, **base_par}}
full = model(P6, rated)
out["richtungen"] = [[r.title[:22] for r in grp] for grp, _ in full[0]]

rows = []
for r in rated:
    p = portraits[r.title]
    if r.sign > 0:
        m = model(P6, [x for x in rated if x is not r])
        x = judge_dirs(p, P6, m)
        probe = "ohne sich selbst"
    else:
        x = judge_dirs(p, P6, full)
        probe = "mit sich selbst"
    rows.append(
        (
            "Mag ich" if r.sign > 0 else "Doof",
            r.title[:24],
            f"{v0stars(v0(p))}★ {round(v0(p) * 100)} %",
            f"{stars(x)}★ {round(x * 100)} %" if x is not None else "kein Urteil",
            probe,
        )
    )
out["eigene"] = rows
xs = [judge_dirs(p, P6, full) for p in sample]
out["tor"] = {
    "heute": sum(1 for p in sample if (v0stars(v0(p)) or 0) >= 3),
    "neu": sum(1 for x in xs if x is not None and stars(x) >= 3),
    "n": len(sample),
}
nf = [sum(1 for k in book_terms(p) if not PAT.get(FAM.get(k, k))) for p in sample]
out["laenge"] = round(statistics.correlation(nf, [x or 0 for x in xs]), 2)
ch = tot = 0
for _ in range(20):
    for p in sample:
        if sum(1 for k in book_terms(p) if not PAT.get(FAM.get(k, k))) < 4:
            continue
        tot += 1
        ch += stars(judge_dirs(p, P6, full)) != stars(judge_dirs(thin(p), P6, full))
out["stufenwechsel"] = f"{round(100 * ch / tot)} %"

json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Richtungen:", out["richtungen"])
for row in rows:
    print("  |", " | ".join(row), "|")
print("Tor", out["tor"], "| Länge", out["laenge"], "| Stufenwechsel", out["stufenwechsel"])
