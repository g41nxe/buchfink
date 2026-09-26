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
- **Reading Profile** (*Leseprofil*) — in the database, see below.

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

A Watchlist Entry typed in the original language resolves in three steps, the
cheapest first (#77):

1. The Source's own search — German only where the Source filters by language.
2. If that leaves the entry unresolved (no match, or a title score below the
   threshold), the **Original Title** of every candidate by the same author
   that carries an ISBN is held against the typed title, with the same
   thresholds as a title. *Scythe* finds *Die Hüter des Todes* this way. One
   book is accepted; two different books with that original title become a
   question for the reader, never a silent pick. A title that already matches
   costs no DNB request.
3. If still nothing is accepted, the same search **without the language
   filter** — the English edition, if the library only has that one. An
   accepted edition in a language the Profile does not name is marked with
   that language on the Watchlist row ("englisch").

Discoveries keep the language filter: this is only for a title the reader
named herself.

### Original Title
*deutsch: Originaltitel*

The title of the work a translation was made from, as the DNB records it for
the translation's ISBN (MARC `240`). Stored in `dnb_record` like every DNB
answer, asked for at most once per ISBN and within the per-Run `dnb_budget`
(ADR 25). Used twice: as Evidence for a Portrait (#17), and to resolve a
Watchlist Entry typed in the original language (#77). Not every record of a translation
carries it: *Scythe* has none, but its DNB title reads „Scythe – Die Hüter des
Todes". Resolution therefore compares the typed title with every name the DNB
gives the book, and with each part of a title split at a dash or colon.

### Library Collection
*deutsch: Sammlung*

A list a library curates itself, used as a source of Discoveries (#74): OverDrive's
*Lucky Day* (instantly borrowable, seven days, no holds), and the Onleihe's
*zuletzt zurückgegeben* (just returned, hence free; fiction recognised from subtitle
and teaser, the ISBN read from the cover address). One request per Run; only
German e-books, fiction by default (BISAC `FIC`, configurable per collection in
`settings.yaml`). A find from a collection counts as a shelf find (Thema) named
after the collection, passes the same Rating Gate, and reads "sofort ausleihbar aus
„Lucky Day"". Taste is judged by the gate, never filtered at the source.

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
language (#10) — and its search is not limited to German either: if the German
search finds nothing, it is searched once more in every language (#77, see
Resolution).

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
shown anyway. It holds back a find that fits under three stars, judged by the
code from the find's Portrait (ADR 33). A find without a judgement — no Reading
Profile, no Portrait yet, a book the model does not know — is shown, never
dropped. Without an API key it still judges the finds that already have a
Portrait; the rest is shown unrated. That is the intended degraded state, not
an outage.

Its standing principle: **quality before quantity.** A handful of well-fitting
suggestions beats a pile of poor ones, and an empty pile is a good result.

**Reader-facing name: *Bewertungstor*.**

### Rating
*deutsch: Urteil*

What a person says about a book, on a 0–5 scale: the reader's own stars, or the
average of foreign readers (the Onleihe). A Rating carries an **Origin** — who
said it: `reader` or `onleihe_readers`. The Origin is part of the key: a 4 from
the reader is a fact, a foreign average says something about the book and not
about the fit to the reader. Both may stand side by side, neither overwrites the
other, and they never render the same.

A Rating is keyed to the **Book**, because that is where a person gives it and it
should hold whichever Source the book next arrives through. What the application
itself thinks of a book is not stored as a Rating: it is a **Verdict**, computed
by the code from the Portrait and the Reading Profile (ADR 33, #52). The old
machine origins (`model`, `conversation`) were deleted with #52.

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

**Reader-facing name: *Leseprofil*.**

### Facet
*deutsch: Facette*

One named way a book can suit this reader. A Reading Profile holds several, and
each is an **independent reason** to like a book: a Facet hit in full counts
strongly, and several reasons strengthen each other without ever passing
certainty (a noisy-OR, ADR 33). A book that hits two Facets in full outranks
one that hits a single Facet. A book that carries only part of a Facet earns
no credit for the Facet — its single Liked Terms count on their own instead
(24.09.2026); what must never happen is what the weighted axes it replaces
did: partial hits collected until a book looked right while suiting nobody.

It is the counterpart to a Genre Category: a Thema says where a shop shelves a
book, a Facet says what the book carries. Confusing the two is what put "Katz
und Maus" — a convention of the crime genre — into the profile as though it were
a matter of taste.

A Facet consists of **at least two Appeal Families** that the reader's loved
books carry together — never Story Patterns (those count on their own, never
inside a Facet). The tool derives Facets **automatically and invisibly** from
which Appeal Families the reader tapped as Liked: it looks across the loved
books at once for families several of them carry together, and every such
combination becomes a Facet. The reader never confirms a Facet and is never
asked about one directly — only about single Appeal Families and Story
Patterns (24.09.2026); a Facet is simply what several Liked Terms turn out to
share. A single family is too wide to be a Facet on its own: in the Intake
experiment (#44) "große Ideen" alone let in a disliked science thriller. A
Liked Term that no other loved book shares forms no Facet — it stays a Liked
Term.

A Facet keeps **how many loved books it rests on**. The reader does not see the
number but a scale (schwach, mittel, stark, sehr stark): a Facet from a single
book is a weak one, and it grows as sharpening adds books.

Facets are **derived from the books the reader already loved**, not invented for
them, and they are **re-derived whenever the Liked Terms change** — tapping a new
Appeal Family, or removing one, can create, widen or dissolve a Facet without the
reader ever being asked about the Facet itself. A Facet is named by its Appeal
Families — "gezeichnete Figur · hart" — so its families choose its name.

What a disappointing book yields is its mirror image, a **Counterweight**: it
weighs against a book and never excludes it.

In library classification a "facet" is a dimension to sort by. Here it is the
reader's own combination of terms; the dimensions are the five appeal factors
the Appeal Terms belong to.

Resemblance to a particular loved book is **evidence inside a justification**
("carries the way David Hunter does"), never a Facet of its own and never itself
worth a star: resemblance narrows, a Facet generalises.

**Reader-facing name: *Facette*.**

### Liked Term
*deutsch: gemochtes Merkmal / gemochtes Erzählmuster*

An Appeal Family or Story Pattern the reader tapped as counting for them,
directly — not part of a Facet. Every loved book shows all of its own families
and patterns, ranked, and the reader taps what holds for them (24.09.2026);
what several loved books carry together is additionally bundled into a Facet
by the tool, but the tap itself is never undone by that — a Liked Term keeps
counting on its own even while it also sits inside a Facet.

A Liked Term is a **starting value of the Taste Form** (#79): the form begins
where the reader tapped, and her rated books move it from there. Up to three
Liked Terms can be **boosted** (*verstärkt*): the reader marks the ones that
matter most, and a boosted term starts further out. Untapping a Liked Term also removes its boost.

**Reader-facing name: none as a category** — the reader sees the Appeal Family
or Story Pattern by its own name, tapped or not.

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
only together with a genre. That answer is its **scope** (*Umfang*): `here`
counts against nothing, `general` everywhere, `genre` only in that genre.

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

### Master Plot
*deutsch: Grundhandlung*

One of Tobias' twenty master plots — *Heldenreise*, *Katz und Maus*, *Rache* …
— serving as the family of Story Patterns (`vocabulary/erzaehlmuster.yaml`). Unlike
an Appeal Family it is assignable itself: a book can be a *Heldenreise* without
any finer pattern, as *Otherland* is. Facets and counterweights compare on it,
across genres.

**Reader-facing name: *Grundhandlung*** — where the reader sees it at all; on
the book page it simply heads its patterns.

### Fit
*deutsch: Übereinstimmung*

How well a book suits the reader, computed by the code from the book's
Steckbrief and her Taste Form (ADR 33): since 26.09.2026 by **Form Overlap**
(#79); until then a noisy-OR over Facets, Liked Terms and Counterweights. The
percentage orders; stars summarise it. No model is asked, so a new profile
version or a newly rated book recomputes every Fit at once. Shown the same way on the book
page, in the Pile and in the Digest: stars with the percentage beside them (#54).
The reader's own stars stand apart as *deine Sterne* and override it (ADR 17). The
strength scale (*schwach* … *sehr stark*) belongs to Facets and families, never to
a Fit — one scale for two different things would read as one.

Not a **Profile Match** (*Profiltreffer*): that is the older, author-based way a
Discovery came in.

**Reader-facing name: *Übereinstimmung*.**

### Taste Form
*deutsch: Geschmacksform*

*In the code since 26.09.2026 (`taste_form.py`, #79).* The reader's
taste as a shape over the axes of the vocabulary (Appeal Terms and Story
Patterns), like a spider graph (*Spinne*): on a dashed ring where she is
indifferent, outward where she likes something, inward where she rejects it;
a family she has said nothing about gets no axis. Drawn on the profile page as
two spiders (Appeal Terms and Story Patterns, at most twelve axes each), and on
a book page with the book laid over it on the same scale (`web/spider.py`). How far it reaches is
**learned from her books** (*Mag ich* and *Doof*, weighted by each term's weight
in the book, and her own reasons for a book she has read), with what she tapped
or boosted as the starting value. She never states a strength herself.

### Form Overlap
*deutsch: Formüberdeckung*

*In the code since 26.09.2026 (#79).* The method that computes the Fit: how
much of a book's shape — its terms, each as strong as the model weighs it in the
book — lies inside the reader's Taste Form, less what lies in its rejecting part;
the Story Patterns form a second spider with the same computation, and a full
Facet adds a bonus. What the form knows nothing about counts neither way, and a
thin Steckbrief stays careful. Deliberately asymmetric: a book is not expected
to carry everything the reader likes. Rejection is averaged over the
disappointing books and weighs a third of agreement (Rocchio, γ/β = 0.33).

### Reader's Reasons
*deutsch: deine Sicht (Gründe der Leserin)*

What the reader says about a book she has read and rated, where the Steckbrief
sees it differently (#79): families the Steckbrief names that did not hold for
her (*Der Schwarm* was not *spannungsgeladen* for her), families it misses
(*gemächlich*), and families that bothered her only in this book (*nur hier*
when she takes a Counterweight). Kept at her rating, not in the Reading
Profile; the Taste Form learns from them before the model's description. A
family she adds counts like a tapped one. Chosen from the vocabulary, never
free text — the code decides, no model is asked.

**Reader-facing name: *deine Sicht*** — the section asks "Sieht das Modell
dieses Buch anders als du?"

### Owned Books
*deutsch: Meine Bücher*

Every book the reader keeps as *Hab ich* (`owned`), as one page (`/owned`,
#71): cover, title, author, her own stars or else the Fit, searchable and
sortable. Not *Bibliothek* — that word means the Library Sources (Onleihe,
OverDrive).

### Portrayer
*deutsch: Steckbrief-Ersteller*

The one place that asks a language model (*deutsch: das Modell*): a book goes in
(title, author, blurb — for a find also original title and keywords), a Portrait
comes out. It holds the vocabulary, the instruction and the reading of the
answer; how the text reaches the model — through the API with a key from the
environment, or through the locally signed-in Claude Code installation — is its
own business (#52). It describes several finds per call (up to eight, #66): the
vocabulary and the rules go out once instead of once per book, and a book the
answer skips or writes crookedly costs only itself. Without either it does not exist, and everything stays
undescribed and is shown (ADR 7).

### Verdict
*deutsch: Urteil (des Tors)*

What the Rating Gate, the pile, the Watchlist and the Digest know about a find:
the Fit (stars, percentage, reasons) computed from its Portrait and the reader's
Reading Profile, together with the Portrait's pitch — or, where she has rated the
book herself, her own stars. Computed on demand and never stored, so a new
Reading Profile version applies to everything at once without asking a model
(ADR 33, #48). A find without a Verdict — no Reading Profile, no Portrait yet, a
book the model does not know — is shown and never held back. Not a Rating: a
Rating is what a person or a reader-average says and is stored (ADR 17).

### Portrait
*deutsch: Steckbrief*

What a model says about a book, **once** and independent of any reader: which
book it is (title, author, and the original title of a translation), its genre
and subgenre, its Appeal Terms — each with a sentence that could stand under no
other book, the evidence it rests on (*klappentext* or *wissen*, never a
sample the model was not given) and, for a term but not for a story pattern, its
**weight** in this book: *prägend* (it makes the book what it is), *deutlich*
(it clearly belongs) or *am Rand* (it occurs but does not carry) — and the pitch
(ADR 33, #62).

It is kept at the book's subject, the ISBN where there is one, append-only. The
same book always has the same Steckbrief: a new one is asked for only when the
instructions or the Appeal Terms change, never when the Appeal Families do,
because those are applied when it is read. Rules the answer breaks are kept
beside it rather than used to discard it. A book the model does not know gets a
Steckbrief too — *unbekannt*, without terms — so it is not asked again.

**Reader-facing name: *Steckbrief*.**

### Strength
*deutsch: Stärke*

How firmly a Facet or an Appeal Family stands in the Reading Profile: *schwach*,
*mittel*, *stark*, *sehr stark*. Derived every time, never stored (ADR 16): the
number of loved books that carry it, one step more if it is *prägend* in at
least one of them (for a Facet: all its families at once), at most *sehr stark*.
So a single book in which a family defines the book is not called weak. It says
how much the profile rests on something, not how much a book fits: the Fit is
computed separately and does not use the weight (#62).

### Intake
*deutsch: Erstaufnahme*

How a Reading Profile comes into being for a reader who has none — and who
brings no history: no blurb, no record, nothing stored. The reader names three
to five books they loved and, if there are any, up to five that disappointed
them. A model identifies each book — original title, author — and the reader
confirms it; a book the model does not know contributes nothing. The model then
assigns Appeal Terms and Story Patterns to each book.

Each named title is an **`IntakeEntry`** (*Eintrag*), saved the moment it is
typed; only when the reader confirms it does it become a book on the shelf,
marked *Mag ich* or *Doof*.

The reader is shown **every** Appeal Family and Story Pattern the loved books
carry, ranked by how many of them carry it, and taps what counts for them —
up to three of those taps can be boosted. Families that are common across
books in general come last, marked as such, but are never hidden; how common a
family is is measured on the books the tool sees anyway, never on the reader's
own, which would punish exactly their taste. The tool derives Facets from the
tapped Appeal Families by itself, invisibly (see Facet); the reader never
confirms one. The disappointing books yield counterweights, and one that a
loved book also carries is not taken over silently: the reader is asked. The
result — Liked Terms, Facets and Counterweights — is presented as an overview
next to the questions; deselecting everything starts over, with other books
or other answers.

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
makes it stronger, and that strength is derived, never stored. Everything new
is asked, in the same pattern as the Intake: a *Mag ich* book shows its own
Appeal Families and Story Patterns, ranked, for the reader to tap and
optionally boost — Facets are re-derived from all Liked Terms afterwards,
never asked about themselves. A *Doof* book instead offers what it lost the
reader as a counterweight; one that fully hits a Facet yields a counterweight
only, and the Facet stays as it is. On the profile page anything can be
deselected at any time; additions only ever come through books.

The burden of proof of ADR 17 is no longer a gate. Its asymmetry lives on —
confirming is cheap, changing asks — and how well something is evidenced is
shown by the strength scale.

**Reader-facing name: *Nachschärfen*.**

### Rating Scheme
*deutsch: Bewertungsschema*

The numbers with which the code learns the Taste Form and computes the Fit
(ADR 33, #79): how much a term weighs in the book, how strongly a disappointing
book rejects, how much the tapped profile weighs as a start, how a thin
Steckbrief is smoothed, what a full Facet adds, where the star thresholds lie,
and from how many stars the Rating Gate lets a find through.

It names **no** axis of taste and would work unchanged for a different reader.
The instructions to the old star-giving model that once stood here are gone
(#52); the instruction for the model that describes a book lives with the
vocabulary, in the Portrait prompt.

**Reader-facing name: *Bewertungsschema*.**

### Evidence
*deutsch: Belege*

What the Portrayer sees of a book beyond title, author and blurb, gathered right
before a Portrait is made and never stored with the Observation: the
**Keywords** and the original title of a translation (#17), and the full blurb. The
reading sample is no longer fetched (#68): the Portrait does not read it, and the
finds on the pile, mostly small and self-publishers, carry none.
Only books about to be described get it, because it costs requests.

### Keywords
*deutsch: Schlagwörter*

What publisher and shop tag a book with — motifs and comparable titles ("Space
Opera", "Dune"). From the shop's detail page and from the DNB record (MARC
`653`, the publisher's own words from the VLB), without trade codes.

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
