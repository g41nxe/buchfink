# Context: Buchfink

## Glossary

Der Code und dieses Glossar sind englisch, alles Gelesene ist deutsch.
Hinter jedem Namen steht deshalb sein deutsches Wort — genau eines
(ADR 22).

### Profile
*deutsch: Profil*

A reader's taste definition: Reference Authors (a whitelist), Genre Categories,
deal thresholds (`strong_deal_max_cents`, `deal_max_cents`, `min_discount_pct`),
and no-gos (dormant in v1). A first-class, keyed entity. v1 runs with a single
profile, but nothing hard-codes that — the data model and code support multiple
profiles.

### Watchlist
*deutsch: Watchlist*

The set of Watchlist Entries belonging to one Profile. Titles/authors actively
watched regardless of whether they fit the Profile's genres.

### Watchlist Entry
*deutsch: Watchlist-Eintrag*

One watched item. From Phase 2 this is a Book Relation of kind `watching`
(ADR 18) — the title and author live on the Book, the per-Source links in
`book_source`, and current price/availability in the Snapshot as Observations.
Never on the entry itself.

### Book
*deutsch: Buch*

A book as a thing in itself — title, author, ISBN, series — independent of any
Source. A Book row exists **only where the reader has a relationship to it**
(ADR 18); a bare discovery stays an Observation. Identity is the ISBN where one
is available, otherwise title and author through the matcher.

### Book Relation
*deutsch: Buchbeziehung*

What a Profile has to do with a Book. Several hold at once — a book can be
owned *and* have been watched. Relations are deactivated rather than deleted,
so "watched until you bought it" stays visible.

| kind | deutsch (the state) | on the button | what it says |
| --- | --- | --- | --- |
| `watching` | in Beobachtung | Beobachten | on the Watchlist, reported at every price |
| `owned` | im Besitz | Hab ich | the reader has it |
| `liked` | Mag ich | Mag ich | read, and it was good |
| `disliked` | Kein Interesse | Doof | read, and it was not |
| `dismissed` | Ausgeschlossen | Ausschließen | never offer this book again |

Two words, two questions (ADR 29 and its addendum). The state name answers
"what is this book to me?" and stands where books are described in prose — the
profile, the Digest, the Watchlist status — like a shelf label. The button word
answers "what do you do with it?" and stands on *every* button: the Suggestion
pile, the start page, the Watchlist menu, the find page and the book page. For
`liked` and `disliked` both roles fall on the same word; that is one word doing
two jobs, not drift. What never happens is the swap: a state name that is no
button word never reaches a button.

`disliked` and `dismissed` are different statements, and neither implies the
other. `disliked` is a verdict *after reading* and says something about taste.
`dismissed` is an instruction about the Suggestion pile and says nothing about
whether the book is any good — a book can be dismissed unread.

### Interest
*deutsch: Entdeckungskanal*

Not *Interesse*: that word belongs to the reader's `disliked` relation, which
the interface calls "Kein Interesse".

Where the tool should look for new books: a Reference Author or a Genre
Category, unified into one concept because both answer the same question and
produce the two discovery Match Reasons. Extensible by a free-text key —
publisher, series, keyword — each needing a handler, not a migration.

### Hold
*deutsch: Vormerkung*

The user's reservation ("Vormerkung") on a Library Source title that is
currently lent out. **v2 feature** (see ADR 6). A hold is *observed*, not set —
v2 reads it off the authenticated account page — so it lives on the Observation
as `hold_state` (`none` → `placed` → `ready`) and `hold_expected_date`
(ADR 18, correcting ADR 6). The `placed` → `ready` transition is therefore an
ordinary Delta, with history, rather than a mutable flag on an entry.

### Source
*deutsch: Quelle*

A place that is polled for data, behind a common interface. Two kinds, three
sources:

- **Library Source** (*deutsch: Bibliothek*) — reports availability/borrowable
  status for a title. Two of them: `onleihe` and `overdrive`, both run by the
  VÖBB in Berlin and each with its own holdings. A source is therefore named
  after the **platform**, never after the library — and where the reader knows
  that name, the interface shows it instead of the kind (`registry.DISPLAY`).
- **Shop Source** — reports price and catalogue presence for a title.
  First implementation: beam-shop.de (DRM-free German ebook shop).

More Sources of either kind can be added without changing the core.

### Resolution
*deutsch: Zuordnung*

Deciding which entry in a Source's catalogue a watched book actually *is* —
title and author in, one stable product number out (ADR 9). A Source searches,
the shared matcher ranks, and a confidence gate decides: accept it, hand it to
the reader to confirm, or call it not found. An accepted Resolution is pinned
and reused every Run, so the search happens once, not daily.

The matcher compares normalised titles, but an exact **identifier** wins over
any title score: `Dark Matter` and `Der Zeitenläufer (Dark Matter)` are the
same book and score 26 out of 100, while their ISBN is identical.

### Thunder
*deutsch: die Schnittstelle von OverDrive*

OverDrive's public JSON API (`thunder.api.overdrive.com`), and the only door
the `overdrive` source knocks on. Its HTML site carries no result cards at all
— JavaScript builds them — so there is no HTML to parse in the first place
(ADR 31). No key, no login, and the field names live in
`sources/overdrive/selectors.py`, exactly where the Onleihe keeps its CSS
selectors.

### Snapshot
*deutsch: Aufzeichnung*

The stored history of Observations. A Run compares the latest Observation of an
item against the previous one and reports only what changed. Append-only, not a
single mutable current-state row.

### Observation
*deutsch: Beobachtung*

One recording of an item's state as seen by a Source during a Run: title,
author, ISBN, blurb, series, price, availability status, hold state,
`observed_at`, the Source, a stable `source_item_id` from that Source, the
matching Book (or NULL for a discovery), and a Match Reason.

An Observation records **what the Source said at that moment**, not what we
believe. Title, author and ISBN are kept even when the Book is known, so that a
source quietly switching editions under the same id stays detectable.

### Match Reason
*deutsch: Anlass*

Why an item is in the Snapshot: `watchlist` (hard title/author match),
`profile_author` (the item's author is on the Profile's reference-author list),
or `genre_category` (the item is a new arrival in one of the Profile's
Genre Categories — a low-confidence suggestion).

### Genre Category
*deutsch: Thema*

A Shop Source category path listed in `profile.yaml`'s `genre_categories`. v1
genre discovery trusts the shop's own shelving: new arrivals in this small
curated set are surfaced as suggestions. Dismissed suggestions
(`source_item_id`) never resurface.

Since ADR 19 a discovery from here is judged against the reading profile before
it reaches the reader, and it has to be a deal to be reported at all.

**Reader-facing name: *Thema*.** "Regal" was the shop's word for its own
shelving, not the reader's word for what interests them. The code keeps
`genre_category`; every string a reader sees says Thema, and both come from
`reasons.py`.

### Discovery
*deutsch: Fund*

An item a Source turned up that the reader never asked for by name — its Match
Reason is `profile_author` or `genre_category`, never `watchlist`. A Discovery
stays an Observation and gets **no** Book row until the reader says something
about it (ADR 18). It is the case every filtering rule in this tool exists for:
a Watchlist title is always reported, a Discovery has to earn it.

### Foreign Discovery
*deutsch: Fund in fremder Sprache*

A Discovery the DNB lists **explicitly** in a language the Profile does not
name (`languages`, ISO 639-2 codes, default `ger`). It never reaches the pile
and costs no Rating. Unknown is never foreign: without an ISBN or a DNB answer
a Discovery stays where it is. A Watchlist Entry is never foreign, whatever its
language (#10).

### Suggestion
*deutsch: Vorschlag*

A Discovery that is still waiting for a decision — one that got past the junk
filter, the price rule and the Rating Gate and now sits on the pile. Not a
synonym for Discovery: every Suggestion is a Discovery, but most Discoveries
never become one (ADR 22).

### Rating Gate
*deutsch: Bewertungstor*

The step that decides whether a Discovery reaches the reader at all (ADR 19).
It sits **behind** the Snapshot, so a failure costs a judgement and never
history, and **behind** the price rule, so nothing is judged that would not be
shown anyway. Without an API key it does nothing and everything is shown —
that is the intended degraded state, not an outage.

Its standing principle: **quality before quantity.** A handful of well-fitting
suggestions beats a pile of poor ones, and an empty pile is a good result.

**Reader-facing name: *Bewertungstor*.**

### Rating
*deutsch: Urteil*

What someone thinks of a book, on the Rubric's 0–5 scale, with a justification
and a confidence (`belegt` | `teils` | `vermutet`).

A Rating carries an **Origin** — who judged: `model` (the Rating Gate in a
Run), `conversation` (judged against the same Rubric in conversation; the
entries in `owned.yaml`), or `reader` (the reader's own stars, set on the book
page). The Origin is part of the key, because the difference is the point: a 4
from the reader is a fact, a 4 from a model is a suggestion (ADR 17). Both may
stand side by side, neither overwrites the other, and the two never render the
same.

A machine Rating is keyed to the *find* — the ISBN, else `(Source, item id)` —
because most finds never become a Book. A human Rating is keyed to the **Book**,
because that is where a person gives it and it should hold whichever Source the
book next arrives through.

A new **Reading Profile** version invalidates machine Ratings, and only those:
that the reader sharpened their own taste is no reason to void what they said.
A change to the Rating Scheme invalidates nothing at all (ADR 21).

### Reading Profile
*deutsch: Leseprofil*

A description of the books this reader likes — as detailed and as specific to
them as it can be made, written in prose, produced by discussing *why* they like
the books they like. It lives in the repository as `docs/leseprofil.md` and
carries a version number; that number means one thing only: the state of the
reader's taste.

It is the **basis for deciding whether an Observation is interesting**. Two
things are *derived* from it and are not themselves the profile: the Reference
Authors and the Genre Categories — what a shop can actually be asked for
(ADR 21).

It changes only through the `leseprofil-schaerfen` skill, which carries an
asymmetric burden of proof and asks for consent per change (ADR 17). The web UI
shows it and refuses to edit it, because a form there would bypass that
procedure.

**Reader-facing name: *Leseprofil*.**

### Rating Scheme
*deutsch: Bewertungsschema*

How a book is held against a Reading Profile and turned into stars: what a star
means, what a justification has to contain, what `confidence` means and what a
merely-suspected judgement may be used for, the counter-check, and the rule
against inventing facts.

It names **no** axis of taste — it is the procedure, not the content, and it
would work unchanged for a different reader. It is therefore **not** versioned
alongside the profile: a change to the scheme invalidates no Rating (ADR 21).

Both raters read the same scheme: the `buch-bewerten` skill and the Rating Gate
in a Run. Before they did, they had already drifted apart — the skill required
research until a judgement was at least half-evidenced, the gate explicitly
allowed a suspected one.

**Reader-facing name: *Bewertungsschema*.**

### Reference Author
*deutsch: Referenzautor:in*

An author on the Profile's whitelist. Any item by a Reference Author is a
Profile Match, discovered even if not on the Watchlist.

Derived from the Reading Profile rather than standing on its own: a shop can be
asked for a name, not for "a damaged narrator" (ADR 21).

### Strong Deal
*deutsch: Schnäppchen*

An item whose current price is below `strong_deal_max_cents` (default 5,00 €).
No discount check — cheap outright is enough.

### Deal
*deutsch: Schnäppchen im Mittelband*

An item priced between `strong_deal_max_cents` and `deal_max_cents`
(5,00-9,99 € by default) **and** genuinely discounted: at least
`min_discount_pct` (default 25%) below its struck original price, or below the
last price we observed. A standing 9,99 € is not a Deal. Note: beam-shop never
shows a struck price (German Buchpreisbindung), so beam Deals can only be
detected via an observed price drop, once history exists.

### Price Delta
*deutsch: Preisänderung*

Any decrease in an item's price versus the previous Observation. Always reported
in the Digest, independent of whether it also qualifies as a Deal or Strong Deal.

### Delta
*deutsch: Änderung*

The umbrella term for a reportable change between the latest Observation and the
previous one: an availability change (`not-available → available`), a Price
Delta, or a new discovery appearing. Deal / Strong Deal are flags on a Delta,
not separate things.

### Watchlist Match
*deutsch: Watchlist-Treffer*

A hard match: a scraped item resolves to a Watchlist Entry — by normalized
title/author comparison, a fuzzy fallback above threshold, or a previously
pinned per-Source link (see ADR 8).

### Profile Match
*deutsch: Profiltreffer*

A soft match for titles not on the Watchlist: the scraped item's author is on
the Profile's Reference Author whitelist. LLM genre classification of
unknown-author titles is out of scope for v1 (a possible v2 feature); v1 genre
discovery is category-based instead (see Genre Category). The Profile's `no_gos`
stay dormant until keyword refinement or v2.

### Digest
*deutsch: Tagesbericht*

A structured object a Run produces when it finds one or more Deltas or a Source
errored: an ordered list of sections (Bibliothek, Watchlist — Preise, Neue Titel
deiner Autor:innen, Genre-Vorschläge (unsicher), ⚠️ Fehler — always last), each
with typed entries. Empty sections are omitted. Rendered two ways from the one
model: a **text renderer** (stdout / cron logs) and an **HTML renderer**
(`data/digests/digest-<date>.html`, and HTML email later). Phase 2's Dashboard
renders the same model with shared HTML partials. Worded "Änderungen seit
letztem Check <date>", never "today". Fully silent only when there are no Deltas
and no errors — an error-only Digest still renders.

### Run
*deutsch: Lauf*

One execution of the scrape-diff-report cycle for a Profile. Fired three ways
against one entrypoint: cron (best-effort), the UI "Run now" button, or the CLI.
A Run is stateless with respect to schedule: it diffs current reality against the
Snapshot whenever the Snapshot was last written, so skipped runs lose nothing —
the next Run reports the accumulated Deltas. A lock serialises concurrent Runs.

### Seed file
*deutsch: Saatgutdatei*

A YAML file under the data directory. Which of them are seed and which are live
is not uniform, and saying "the database is the source of truth" flatly was
wrong:

| File | Role |
| --- | --- |
| `watchlist.yaml` | **Seed.** Imported once into Book Relations of kind `watching`; the database is the truth afterwards and edits happen through the UI. |
| `owned.yaml`, `dismissed.yaml` | **Seed.** Imported once into Relations and Ratings. |
| `profile.yaml` | **Live configuration, not seed.** There is no profile table; `load_profile()` reads the file on every request. Thresholds, the rating model, the sweep weekday, Reference Authors and Genre Categories all come from it at runtime. Its Interests are *additionally* seeded into the `interest` table, so those two exist in both places. |

Separate from all of these, and not in the data directory at all: the Reading
Profile and the Rating Scheme live under `docs/` and are read relative to the
package root. They are versioned with the code, not carried with the data.
