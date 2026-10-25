# 3. Local Web UI

> **Nachtrag (ADR 40):** Der Lauf ist kein Kindprozess der Oberfläche mehr. Alle
> Hintergrundarbeit — Lauf, enger Lauf, Steckbrief — ist ein Auftrag für einen
> eigenen Hintergrunddienst; im Webprozess läuft keine Arbeit mehr.

> **Nachtrag:** Die Konfiguration wandert **nicht vollständig** in die
> Datenbank. `docs/leseprofil.md` bleibt Repo-Datei mit eigenem
> Änderungsverfahren (ADR 17), und Selektoren bleiben beim Parser (ADR 18).
> Die UI zeigt das Profil an; bearbeitet wird es über `leseprofil-schaerfen`.

v1 ships a thin local web application for viewing Run results and editing the
Profile and Watchlist.

## Context

The original spec was a silent cron script with hand-edited YAML. The user wants
a surface to watch results over time and to edit config through forms rather than
a text editor. Options researched: Streamlit (rejected — re-runs whole script per
interaction, weak at CRUD), NiceGUI (pure-Python app UI, but persistent
websocket per tab, heavier runtime, opaque state, worst fit for a Pi Zero W),
FastAPI + Jinja + HTMX (server-rendered, no build step, no websocket, testable),
and auto-admin libraries like sqladmin (free CRUD screens from SQLAlchemy
models).

## Decision

- **Stack:** FastAPI + Jinja templates + HTMX. Server-rendered, no frontend build
  step, no websocket.
- **Pages:** Dashboard (Deltas + per-Watchlist-Entry status) — hand-rolled;
  Watchlist editor and Profile editor — hand-rolled forms, with `sqladmin`
  mounted at `/admin` as a fallback accelerator if hand-rolling the forms proves
  wasteful during implementation.
- **Store:** SQLite via SQLAlchemy models is the single source of truth for
  Profile, Watchlist, and Snapshot. YAML is demoted to an optional Seed file for
  import/bootstrap only.
- **Separation:** the scraper is a separate entrypoint invoked by cron/CLI/the
  UI button. The web app only reads Snapshot and writes config. No scheduler runs
  inside the web process in v1.
- **Auth:** none in v1. Bind to the LAN on a trusted home network. Add basic auth
  only if exposed beyond the LAN.
- **Notification:** a `notifier` module (mail/push) exists but is disabled by
  default; the UI is the primary surface.

## Consequences

- Custom code is spent on the bespoke Dashboard; generic CRUD stays cheap.
- Zero websockets and a small runtime — hostable on any Pi.
- The web app is restartable and stateless; killing it never affects a Run.
- If a Source later needs JS rendering or real-time Run progress, that is a new
  decision, not covered here.
