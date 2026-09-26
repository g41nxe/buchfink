# 8. Matching

Matching a scraped item to a Watchlist Entry or a Reference Author is
normalize-then-compare with a fuzzy fallback, not raw string equality.

## Context

The spec assumed plain string comparison suffices. In practice titles and author
names differ across Sources by diacritics, case, `ß`/`ss`, whitespace, subtitle
and series noise, format tokens, author-name order, multi-author fields, and
translation drift.

## Decision

- **Normalization:** lowercase; Unicode NFKD + strip diacritics; `ß` -> `ss`;
  collapse whitespace. Titles additionally: drop trailing `(...)`/`[...]`,
  drop everything after ` - ` / ` — ` / `: `, strip known format tokens
  (`ebook`, `ungekürzt`, `gekürzt`, ...). Authors: canonicalise to
  `first last`; split multi-author fields on `;`, `&`, `und`, `,`.
- **Match ladder:** normalized exact match -> else `rapidfuzz` token-set ratio
  >= ~90 -> else no match.
- **Fuzzy hits are provisional:** marked "probable, confirm in UI"; they do not
  trigger a notification until confirmed. Exception — automated entry resolution
  (ADR 9) uses a **confidence gate**: a top candidate above a high threshold is
  accepted with no confirmation; only genuinely ambiguous cases are surfaced for
  attention.
- **Research done:** see `docs/research/calibre-matching-rules.md`. Key outcome —
  Calibre does *no* fuzzy matching; it normalises aggressively then does a
  deterministic lexicographic sort. We take its normalisation recipe and
  ranking-key design and add our own `rapidfuzz` layer + confidence gate.
  Adopt from the research doc:
  - the consolidated `normalize_title` / `normalize_author` checklists
    (NFKD + combining-mark strip + explicit `ß/ø/ł/æ/œ/ð/þ` table + `casefold`;
    bracket/edition/format/subtitle stripping; looped leading-article drop
    extended with German articles; comma-swap + prefix/suffix/particle drop for
    authors; keep an initials-included variant for a looser second pass);
  - a **lexicographic sort key**, not a weighted sum:
    `(id_match, title_exact, -(title_fuzzy//5), author_exact, -(author_fuzzy//5),
    year_delta, source_rank)`, best = min;
  - the **confidence trichotomy** for ADR 9's gate: auto-accept on
    `id_match` OR (`title_exact` AND `author_fuzzy >= 90`) OR
    (`title_fuzzy >= 95` AND `author_exact`); provisional when `title_fuzzy` in
    ~[85,95) or the #1/#2 candidates are within ~3 points; no match below ~85.
  - Do **not** copy: `title_sort` article-to-suffix rewriting, `titlecase()`
    re-casing, `xisbn`, first-author-only comparison, the hard ≤2-char token
    drop, plain `.lower()` merge keys.
- **Raw values retained:** every Observation stores the raw scraped `title` and
  `author` alongside the matched entry.
- **Pin-the-ID escape hatch:** once a match is confirmed for a Source, the
  resolved `source_item_id` / deep link is stored on the Watchlist Entry and
  future Runs skip matching for that Source.

## Consequences

- False positives stay out of notifications (provisional until confirmed).
- After first confirmation, a title's lookup is exact and cheap.
- `rapidfuzz` is a dependency.

## Nachtrag (#77): der Originaltitel

*Scythe* von Neal Shusterman stand bei OverDrive und im Shop als *Die Hüter
des Todes* im Ergebnis — Titelwert 29, kein Treffer, obwohl die Autorin bei
allen fünf Karten stimmte. Die Autor:in bestätigt weiterhin nur einen Titel,
der schon passt. Neu ist ein **zweiter Titel**, gegen den verglichen wird: der
Originaltitel, den die DNB zur ISBN einer Übersetzung kennt
(`matching.by_original_title`).

- Gefragt wird nur für Einträge, die sonst unaufgelöst blieben, nur für
  Karten mit bestätigt gleicher Autor:in und ISBN, und nie ohne Autor:in am
  Eintrag. Ein Titel, der schon passt, kostet keine DNB-Anfrage.
- Dieselben Schwellen wie beim Titel: ab 95 angenommen, zwischen 85 und 95
  eine Frage. Zwei verschiedene ISBNs mit diesem Originaltitel sind immer eine
  Frage; dieselbe ISBN auf zwei Karten ist ein Buch.
- Eine Karte, die einen späteren Band nennt, wird nicht gefragt, und ein
  Originaltitel, der nur die Reihe nennt, trifft den Bandtitel nicht.
