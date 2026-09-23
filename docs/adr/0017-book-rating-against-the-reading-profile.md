# 17. Rating books against the reading profile

## Context

ADR 13 lists "profile matching of discoveries" as deferred work: deciding
whether a *found* title suits the reader, not merely whether its author or its
shelf does. A genre shelf cannot express "beklemmend", "isolierte Settings" or
"Katz-und-Maus", so the category feed reaches the Digest unfiltered — a hundred
suggestions a Run, ranked by nothing.

A first attempt at rating the reader's own books by hand exposed the second
problem: without a written standard, two ratings of the same book do not agree,
and four of thirteen books were rated from inference rather than fact. Three of
those four were too low, and one author had simply not been looked up.

## Decision

**`docs/leseprofil.md` is the standard, and it is versioned in the repo.** It
holds the axes, the contraindications, the star definitions and the rules a
justification has to satisfy. The reader's personal lists — Reference Authors,
`liked_books`, `disliked_books`, the owned books — stay in `data/`, which is not
tracked. The yardstick belongs in the repo; the reading data does not.

**Two skills, and only one of them may change the standard.**
`buch-bewerten` applies it and writes only into the book list it was handed.
`leseprofil-schaerfen` measures the standard against the books and, after
per-change confirmation, rewrites it. A rating skill that could nudge the
yardstick would be a measuring instrument calibrating itself.

**The manual rating is the prototype of the automatic classifier**, not a
separate conversational tool. One standard, one scale: the classifier awards
stars too. Building the manual version first is the cheapest way to learn what
the automatic one needs.

**Every axis declares whether a machine could read it.** This turned out to
matter: the strongest axis (a series with a recurring protagonist) is only half
readable — the Onleihe names the series in a field, beam-shop hides it in the
title, and that the *character* recurs is nowhere in any metadata. The second
strongest (a distinctive, usually damaged narrative voice) is readable from a
blurb only unreliably.

**Therefore ratings carry `confidence`** — `belegt`, `teils`, `vermutet` — with
defined meanings. `vermutet` is legitimate for the automatic filter, which
cannot research a hundred finds a Run, and is a defect in a hand-made rating,
where the instruction is to research until at least `teils` holds.

**Blurb, subtitle and series are captured from now on.** Four of the seven
criteria can only be read from a blurb, and both Sources already serve one on
pages the Run fetches anyway — beam in `.product--description`, the Onleihe in
`cardAbstract`, plus an explicit `Reihe:` field on its detail page. We were
downloading them and throwing them away. It costs no extra request, and history
cannot be backfilled: whatever is not recorded today is missing from the data
the classifier will have to be built and checked against.

**Changes to the standard carry an asymmetric burden of proof.**

| Stufe | Change | Evidence |
|---|---|---|
| 1 | extend `liked_books` / `disliked_books`, propose a Reference Author | none |
| 2 | drop or soften a contraindication | **one** contradiction |
| 3 | add, remove or reweight an axis; change the star definition | **two independent** books |

A wrong contraindication does damage immediately and invisibly — it hides books
the reader wanted and they never learn of it. That is not hypothetical: the
original profile's "Romantik-Subplot" and "langatmiger Weltenbau" would both
have discarded books from the reader's own list of favourites. A misweighted
axis merely costs ranking. So: **striking is cheap, weighting is expensive.**

**Negative examples are collected.** The standard was built entirely from
approval — nine liked books, none that disappointed — and accordingly all
thirteen rated books landed between three and five stars. A scale where nothing
ever reaches the bottom does not discriminate, it confirms. The most valuable
entry is not a cozy mystery, which the standard already excludes, but a book
that fit on paper and lost the reader anyway.

**A rating records which version of the standard produced it**, and a change
never triggers automatic re-rating. The skill reports how many ratings are now
stale and leaves the decision open — worth redoing for thirteen books, not for
eight hundred.

## Consequences

- `observation` gains `blurb`, `subtitle` and `series`. Existing rows stay NULL;
  the classifier's evidence base starts accumulating from today.
- `Profile` gains `disliked_books` beside `liked_books`. Both are dormant — like
  `no_gos`, nothing reads them yet.
- Axis B stays machine-unreadable. The classifier will either have to ignore it
  or replace it with something a blurb can carry, which would not be the same
  thing. This is a known, deliberate gap rather than an oversight.
- Justifications are constrained: a bare fact ("Band 1 einer Reihe") or a
  circular claim ("trifft den Kern") is not a reason. Each must name the axis,
  the concrete element in the book, why it counts for this reader, and what
  costs the missing star.

> **Nachtrag: in Teilen abgelöst durch ADR 33.** Das Leseprofil ist keine
> Repo-Datei mehr, die nur `leseprofil-schaerfen` ändert; es entsteht in der
> Oberfläche und liegt in der Datenbank. Gegenanzeigen gibt es nicht mehr, nur
> Gegengewichte, die nie ausschließen. Die dreistufige Beweislast ist keine
> Schranke mehr; ihre Asymmetrie lebt als „Bestärken ist billig, Ändern fragt
> nach" fort, und wie gut etwas belegt ist, zeigt die Stärke einer Facette.
> Die Anforderungen an eine Begründung oben gelten weiter; sie werden jetzt
> aus Daten erfüllt statt von einem Modell.
