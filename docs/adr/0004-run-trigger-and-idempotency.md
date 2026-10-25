# 4. Run Trigger and Idempotency

> **Nachtrag (ADR 40):** Statt Cron holt ein Hintergrunddienst nach, was nach der
> Kadenz fällig ist; `ebw run --wenn-faellig` bleibt für Cron. Die Idempotenz
> dieses ADR ist die Voraussetzung dafür, dass Huey höchstens einmal zustellt.

A Run can be fired three ways and must be correct regardless of when the last Run
happened.

## Context

The host machine may be off or asleep, so cron runs are not guaranteed. The tool
must not depend on a regular daily cadence for correctness.

## Decision

- **One entrypoint**, three triggers: cron (best-effort), the UI "Run now"
  button (shells out, streams status via HTMX), and the CLI
  (`python -m ebook_watchlist.run`).
- **Schedule-stateless:** a Run scrapes current state, diffs against the Snapshot
  as last written, emits the accumulated Deltas, then rewrites the Snapshot.
  Skipped runs lose nothing; the next Run reports everything that changed since.
- **No double-fire:** Deltas come from the Snapshot diff, not from a
  "last run date," so re-running produces no output when nothing changed.
- **Digest wording:** "changes since last check on <date>", never "today."
- **Locking:** a lock (filelock or a SQLite advisory row) serialises Runs. A
  second concurrent Run waits briefly or exits with "already running."

## Consequences

- Cron is a convenience, not a dependency.
- Manual and scheduled runs share one code path.
- Long gaps between Runs produce larger Digests, which is acceptable.
