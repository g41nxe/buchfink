# 7. Source Interface and Scraping Robustness

All Sources sit behind a common interface; HTTP politeness and failure handling
are framework concerns, not per-Source code.

## Context

Output is silent unless there are Deltas, so a silently-broken scraper is
indistinguishable from "nothing changed." Robustness and loud failure matter more
than coverage.

## Decision

### Interface

- **`LibrarySource`**
  - `check(entry) -> AvailabilityObservation | None` — public availability, no
    login. `None` = not found.
  - `check_holds(credentials) -> list[HoldObservation]` — **v2 only**
    (authenticated; see ADR 6). Not implemented in v1.
- **`ShopSource`**
  - `check(entry) -> PriceObservation | None` — one watched title. beam:
    `GET /search?sSearch=<title> <author>&n=48` + strict ADR 8 re-match of tiles
    (search relevance is noisy).
  - `by_author(author) -> list[PriceObservation]` — catalogue by Reference
    Author, for discovery. beam: `/autor-innenwelt/<slug>/` for the ~30 curated
    authors, otherwise `GET /search?sSearch=<author>&n=100` + client-side
    `.product--author` filter.

### Cross-cutting (framework-enforced)

- Serial requests per server, fixed 2-4 s delay between them (since #101 each
  Source has its own client and the Sources run side by side), descriptive `User-Agent` with
  contact info, one retry with backoff on 5xx/timeout, hard stop on HTTP 429.
- A Source **raises** only on "site structure changed / unparseable response",
  including login failure. Per-item "not found" returns `None`.
- A raised Source error fails that Source for the Run, lets the other Sources
  finish, and is reported in the Digest and Dashboard. Never silent.
- **Broken-parser guard:** a Source that extracts zero fields from inputs that
  previously worked raises instead of returning an empty result.
- **`ebw doctor` self-check (Phase 1):** each Source declares a hard-coded
  known-good probe (a title that certainly exists, a category that is certainly
  populated). `doctor` runs every probe and asserts the expected fields still
  parse; it runs at the start of every Run and on demand. A failure aborts that
  Source loudly and names the broken selector.
- **Selectors live in one place per Source** (a `selectors` block/module), so a
  fix is a single-file edit.

## Consequences

- A dead scraper produces a visible error, not a false "no deals."
- Per-Source code is small: fetch + parse + map to `Observation`.
- Politeness is consistent across Sources by construction.
