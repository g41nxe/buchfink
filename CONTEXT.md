# Context: Buchfink

## Glossary

Der Code und dieses Glossar sind englisch, alles Gelesene ist deutsch.
Hinter jedem Namen steht deshalb sein deutsches Wort — genau eines
(ADR 22).

### Profile
*deutsch: Profil*

A reader, as a keyed entity: everything in the database hangs off one `slug`.
v1 runs with a single profile, but nothing hard-codes that.

Its content lives in three places, and they carry three different words (#36).
Calling all three "the profile" is what let one file hold settings that take
effect at once beside fields that had stopped meaning anything:

- **Settings** (*Einstellungen*) — `data/settings.yaml`, below;
- **Seed** (*Saatgut*) — `data/seed.yaml`, see *Seed file*;
- **Reading Profile** (*Leseprofil*) — `docs/leseprofil.yaml`, see below.

### Settings
*deutsch: Einstellungen*

What the run needs: sources, cadence, budgets, deal thresholds, languages. Read
on every request, so a change takes effect at once. It holds no authors, no
themes and no book lists — what of those applies lives in the database, and
what seeded it in `seed.yaml`.

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

A Shop Source category path — an Interest in the database, seeded once from
`seed.yaml`'s `genre_categories` (#36). v1
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

A machine Rating is **computed by the code** from the Appeal Terms a model has
assigned to the book once and the reader's Facets and counterweights (ADR 33).
A new Reading Profile version therefore voids nothing: machine Ratings are
recomputed, and the reader's own stars stay as they are.

### Reading Profile
*deutsch: Leseprofil*

What the books this reader loved have in common: **Facets**, the
**counterweights** from books that disappointed them, and the **Reference
Authors and genres** that steer the search. It is derived from the reader's
books, not written in prose (ADR 33).

It is the **basis for deciding whether an Observation is interesting**. It comes
into being in the Intake, changes through Sharpening, and lives in the database
per reader, append-only: every version keeps the book or the click that caused
it. A version number still means one thing only — the state of the reader's
taste — but a new version no longer voids any Rating, because the code
recomputes them.

Without a Reading Profile nothing is judged.

Until ADR 33 is built, the code still reads the old prose profile from
`docs/leseprofil.yaml`, changed through the `leseprofil-schaerfen` skill
(ADR 17, ADR 21).

**Reader-facing name: *Leseprofil*.**

### Facet
*deutsch: Facette*

One named way a book can suit this reader. A Reading Profile holds several, and
each is an **independent reason** to like a book: a Facet hit in full counts
strongly, one hit in part counts little, and several reasons strengthen each
other without ever passing certainty (a noisy-OR, ADR 33). A book that hits two
Facets in full outranks one that hits a single Facet. What must never happen is
what the weighted axes it replaces did: partial hits collected until a book
looked right while suiting nobody.

It is the counterpart to a Genre Category: a Thema says where a shop shelves a
book, a Facet says what the book carries. Confusing the two is what put "Katz
und Maus" — a convention of the crime genre — into the profile as though it were
a matter of taste.

A Facet consists of **at least two Appeal Families** that the reader's loved
books carry together. The tool looks across all the books at once for families
several of them share and asks which of those are really the reader's; confirmed
families that the same books carry together form one Facet. A single family is too
wide to be a Facet: in the Intake experiment (#44) "große Ideen" alone let in a
disliked science thriller. A loved book that shares nothing with the others is
asked about on its own and can still form a Facet by itself.

A Facet keeps **how many loved books it rests on**. The reader does not see the
number but a scale (schwach, mittel, stark, sehr stark): a Facet from a single
book is a weak one, and it grows as sharpening adds books.

Facets are **derived from the books the reader already loved**, not invented for
them. The tool asks **no open questions**: it proposes, derived from the books,
and the reader chooses. A Facet is named by its Appeal Families — "gezeichnete
Figur · hart" — so choosing the Facet chooses its name.

What a disappointing book yields is its mirror image, a **Counterweight**: it
weighs against a book and never excludes it.

In library classification a "facet" is a dimension to sort by. Here it is the
reader's own combination of terms; the dimensions are the five appeal factors
the Appeal Terms belong to.

Resemblance to a particular loved book is **evidence inside a justification**
("carries the way David Hunter does"), never a Facet of its own and never itself
worth a star: resemblance narrows, a Facet generalises.

**Reader-facing name: *Facette*.**

### Counterweight
*deutsch: Gegengewicht*

The mirror image of a Facet: what the reader named as the reason a book lost
them. It weighs **against** a book — the strongest one takes a fifth off — and
never excludes it. The profile has no contraindications: an exclusion acts at
once and invisibly, and what spoiled one disappointing book can be exactly why
another is loved.

Like a Facet it is a **bundle**, and it counts only when a book carries all of
it. Unlike a Facet it may contain a **genre**: *Herr der Ringe* lost the reader
as classic fantasy on a hero's journey, while *Otherland*, a hero's journey in
science fiction, is loved. The counterweight is "klassische Fantasy ·
Heldenreise", and *Otherland* stays untouched. In a Counterweight a genre only
narrows what is punished, so it is safe; in a Facet it would narrow what is
found, which is why Facets stay without genre until a book shows otherwise.

When a counterweight is also carried by a loved book, it is not taken over
silently; the reader is asked — only for this book, for books generally, or
only together with a genre.

**Reader-facing name: *Gegengewicht*.**

### Appeal Term
*deutsch: Merkmal*

One word of a fixed vocabulary for how reading a book feels — "trostlos",
"exzentrische Figur", "gemächlich". Built on NoveList's appeal vocabulary, with
its five appeal factors (pace, storyline, tone, character, writing style),
translated, with near-synonyms merged into one term and quality verdicts
("well-developed", "engaging") left out, because every reader would choose them.

Together with the Appeal Families and the Story Patterns it is the part of the
Intake that is fixed in advance. Books and genres can never be listed
completely; these terms describe any book. The vocabulary names no taste, so it
lives in the repository beside the Rating Scheme.

A model assigns Appeal Terms to a book once, only from the vocabulary and each
with its evidence, and the result is stored with the book: the same book always
carries the same terms. Liked and disliked use the same words — a term that
holds one reader can lose another. The reader is not asked about the fine terms
but about their Appeal Families.

Not to be confused with **Keywords** (*Schlagwörter*): those are what publisher
and shop tag a book with, in their words.

**Reader-facing name: *Merkmal*.**

### Appeal Family
*deutsch: Merkmalsfamilie*

Appeal Terms a reader does not tell apart, grouped: "brutal", "verstörend" and
"schonungslos" are one family, "hart". The model assigns the fine terms, because
their precise descriptions keep it consistent; the reader is asked, and books
are compared, by family. A family may span appeal factors — NoveList files
"gritty" under style and "violent" under tone, and the reader feels them as one.

Families are derived and a **work in progress**. Only the fine terms are stored
with a book, so changing a family needs no book to be tagged again. A family
changes when a concrete book shows that it cuts wrong, and it names the book
that justifies it.

What may enter at all is decided by the **opposite test**: is there an opposite
another reader would want just as much? "rasant" passes (gemächlich),
"anschaulich" does not (blass) — that is praise, not taste. Absence is not the
opposite: Shakespeare carries no "lebendiger Schauplatz", but his readers seek
language, not placelessness; Kafka's readers do seek it ("parabelhaft").

**Reader-facing name: none.** The reader sees the families' own names, "hart"
or "witzig"; the word itself belongs to the documentation.

### Story Pattern
*deutsch: Erzählmuster*

A story pattern bound to a genre: "Katz und Maus", "race against time", "a
fellowship sets out against evil". NoveList calls them themes and keeps them
apart from appeal. Here they are treated like Appeal Terms — assigned by the
model, chosen by the reader, part of a Facet or a counterweight — because the
Intake experiment (#44) showed that the reason a book loses a reader can be
exactly such a pattern.

It enters a Facet only when the reader's own books share it. That is the
difference to the old axis "Katz und Maus", which was written into the profile
as a taste in its own right.

Its vocabulary is built like the Appeal Terms', in two levels: **NoveList's
themes**, listed per genre, are the fine level the model assigns; **Tobias'
twenty master plots** (*Quest*, *Pursuit*, *Revenge* …) are the families the
reader is asked about, across genres — "Katz und Maus" is *Pursuit* in a
thriller and in science fiction alike. The opposite test does not fit here: a
pattern is present or absent and has no opposite anyone seeks. What may enter
is decided by the **avoidance test** instead: are there readers who avoid
exactly this pattern?

Not a Thema: a Thema is the shop's category.

**Reader-facing name: *Erzählmuster*.**

### Portrait
*deutsch: Steckbrief*

What a model says about a book, **once** and independent of any reader: which
book it is (title, author, and the original title of a translation), its genre
and subgenre, its Appeal Terms — each with a sentence that could stand under no
other book and the evidence it rests on — and the pitch (ADR 33).

It is kept at the book's subject, the ISBN where there is one, append-only. The
same book always has the same Steckbrief: a new one is asked for only when the
instructions or the Appeal Terms change, never when the Appeal Families do,
because those are applied when it is read. Rules the answer breaks are kept
beside it rather than used to discard it. A book the model does not know gets a
Steckbrief too — *unbekannt*, without terms — so it is not asked again.

**Reader-facing name: *Steckbrief*.**

### Intake
*deutsch: Erstaufnahme*

How a Reading Profile comes into being for a reader who has none — and who
brings no history: no blurb, no record, nothing stored. The reader names three
to five books they loved and, if there are any, up to five that disappointed
them. A model identifies each book — original title, author — and the reader
confirms it; a book the model does not know contributes nothing. The model then
assigns Appeal Terms and Story Patterns to each book.

The tool looks across all loved books at once for the Appeal Families that
more than one of them carries and asks which of those carry the reader. It never
compares books pairwise and has no threshold for "similar". Families that are
common across books in general come last, marked as such, but are never hidden;
how common a family is is measured on the books the tool sees anyway, never on
the reader's own, which would punish exactly their taste. Afterwards **every
loved book must sit in a Facet**; one that does not is asked about on its own.
The disappointing books yield counterweights, and one that a loved book also
carries is not taken over silently: the reader is asked. The
result — Facets, Reference Authors, genres and counterweights — is presented as
a list to confirm or deselect. Deselecting everything starts over, with other
books or other answers.

It carries **no burden of proof**: there is nothing yet to contradict. What
follows it is Sharpening.

The same answers give the same profile. Which question comes next and which
Facet follows from the answers is decided by code, not by a model.

**Reader-facing name: *Erstaufnahme*.**

### Sharpening
*deutsch: Nachschärfen*

How an existing Reading Profile changes. It is triggered by every book the
reader marks *Mag ich* or *Doof* — verdicts after reading — and never by
*Ausschließen*, which says nothing about taste, nor by the reader's own stars,
which stay a display and the data weights may later be learned from.

What merely confirms a Facet happens silently: another loved book carrying it
makes it stronger, and that strength is derived, never stored. Everything new is
asked, in the same pattern as the Intake: a loved book that sits in no Facet,
families several loved books now share, a new author or genre, a counterweight
from a *Doof* book. A *Doof* book that fully hits a Facet yields a counterweight
only; the Facet stays as it is. On the profile page anything can be deselected
at any time; additions only ever come through books.

The burden of proof of ADR 17 is no longer a gate. Its asymmetry lives on —
confirming is cheap, changing asks — and how well something is evidenced is
shown by the strength scale.

**Reader-facing name: *Nachschärfen*.**

### Rating Scheme
*deutsch: Bewertungsschema*

How a book is held against a Reading Profile and turned into stars: what a star
means, what a justification has to contain, what `confidence` means and what a
merely-suspected judgement may be used for, the counter-check, and the rule
against inventing facts.

It names **no** axis of taste — it is the procedure, not the content, and it
would work unchanged for a different reader. It is therefore **not** versioned
alongside the profile: a change to the scheme invalidates no Rating (ADR 21).

Since ADR 33 it holds, machine-readable, how the code turns Facets into a
Rating: what a Facet hit in full or in part weighs, what a counterweight takes
off, where the star thresholds lie. It also holds the rules for what the model
writes once per book, the pitch among them.

**Reader-facing name: *Bewertungsschema*.**

### Evidence
*deutsch: Belege*

What a rater sees of a book beyond title, author and blurb, gathered right
before a Rating and never stored with the Observation: the **Sample**, the
**Keywords**, and the original title of a translation (#17). Only books about
to be rated get it, because it costs requests.

### Sample
*deutsch: Leseprobe*

The opening of the book itself, read from the EPUB sample that the shop and the
library link on the detail page — the first couple of thousand words after the
front matter. The only Evidence that shows *how* a book is written rather than
what it promises. Without it, a Rating is at most `teils`: `belegt` needs the
Sample.

### Keywords
*deutsch: Schlagwörter*

What publisher and shop tag a book with — motifs and comparable titles ("Space
Opera", "Dune"). From the shop's detail page and from the DNB record (MARC
`653`, the publisher's own words from the VLB), without trade codes.

### Deduction
*deutsch: Abzug*

A star taken off a machine Rating by the code, after the model has judged —
for a rule that hangs on a list rather than on judgement, so it applies the
same to every book (#28). The one today: **Selbstverlag**, when the publisher
is a self-publishing platform (neobooks, epubli, tredition, BoD, …). Small
presses are not on the list. The Rating keeps the model's own stars beside it,
and the page shows both.

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
| `settings.yaml` | **Live configuration, not seed.** There is no settings table; `load_settings()` reads the file on every request. Thresholds, the rating model, the sweep weekday and the sources all come from it at runtime. |
| `seed.yaml` | **Seed.** Imported once into Interests and Relations. Until #36 these fields sat in `profile.yaml` next to the live ones and looked exactly like them, although `configuration.load` overwrote them from the database on every run. |

Separate from all of these, and not in the data directory at all: the Reading
Profile and the Rating Scheme live under `docs/` and are read relative to the
package root. They are versioned with the code, not carried with the data.
