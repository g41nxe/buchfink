# 20. Frontend stack: Tailwind, Alpine, and a build step after all

Amends ADR 3, which said "no frontend build step". There is one now, and it
runs at development time only.

## Context

ADR 3 chose FastAPI, Jinja and HTMX and ruled out a build step. That was
decided before a single screen existed. One screen later the picture is
clearer:

- The Dashboard's styling is about forty lines of hand-written CSS inlined in
  the base template. The triage prototype needed roughly two hundred.
- Seven more screens are planned — watchlist, book page, triage, profile,
  run-now, plus what those pull in.
- Hand-written CSS across seven screens, inlined in templates, with no shared
  vocabulary, is how a codebase ends up with four slightly different card
  styles and nobody willing to touch any of them.

The reader's instruction was to do this properly rather than half-way, and to
follow common practice. That settles it: ad-hoc CSS scaling to seven screens
is the half-way option, not the disciplined one.

## Decision

### Tailwind CSS, built by a standalone binary, no Node

`pytailwindcss` installs the official Tailwind standalone executable through
pip, so it joins the project the same way `ruff` and `pytest` do — a
development dependency in `pyproject.toml`, resolved by `uv`. No Node, no
`package.json`, no `node_modules`.

The build produces one static stylesheet, and **build output is not committed**.
Checked-in artifacts drift apart from their sources the first time someone edits
the source and forgets the build, and nothing says so. `web/static/` is
gitignored and produced by `uv run python -m ebook_watchlist.web.build`.

The cost is that a fresh checkout must build before it can serve. The web app
therefore refuses to start with a plain message naming the command, rather than
serving an unstyled page that reads like a CSS bug.

The Tailwind Play CDN was rejected. It ships a compiler to the browser, it is
explicitly not for production, and it is a third-party request on every page
load — which contradicts the decision taken about covers, that nothing on these
pages tells an outside party what the reader is looking at.

### Alpine.js for browser state, HTMX for server state

The two have a clean division, and stating it is the point of naming both:

> **HTMX** when the server owns the answer — a row is dismissed, a book is
> watched, a Run is started. The server re-renders the fragment.
> **Alpine** when nothing outside the browser cares — which rows are ticked,
> which panel is open, keyboard navigation through a stack.

Bulk triage is the case that needs both: Alpine holds the selection, HTMX posts
it and swaps in the result.

> **Nachtrag aus der Umsetzung (Ticket 23):** Diese Arbeitsteilung stand acht
> Tickets lang nur auf dem Papier. HTMX ist seit Ticket 10 im Einsatz; Alpine
> wurde vom Build geholt, mit einer SHA gepinnt — und von **keinem** Template
> geladen. 55 KB Abhängigkeit ohne Nutzen, und niemandem fiel es auf, weil
> nichts fehlte.
>
> Jetzt trägt es den Fall, den dieser Absatz selbst nennt: die Vorschlagsseite
> zählt, wie viele Zeilen angehakt sind, schaltet die Knöpfe frei, sobald es
> eine ist, und kennt "alle" und "keine". Bei fünfzig Zeilen ist das die Frage
> vor jedem Knopfdruck, und kein Server hat mit ihr zu tun.
>
> Eine Abweichung von der Vorhersage oben: abgeschickt wird mit einem
> gewöhnlichen Formular, nicht mit HTMX. Die Entscheidung führt zu einer neuen
> Seite, nicht zu einem ausgetauschten Fragment — dafür ist ein Formular das
> richtige Werkzeug, und HTMX hätte nichts hinzugefügt.
>
> Alles, was ohne Alpine sinnlos wäre, trägt `x-cloak` und ist ohne das Skript
> unsichtbar: fällt es aus, ist die Seite ein gewöhnliches Formular und kein
> Zähler, der auf null stehenbleibt.

Both are fetched once by the build into the static directory, pinned by version
and checked against a SHA-256, and served from there — never loaded from a CDN
at page load. Same reason as above, plus the tool then works on a network that
cannot reach out at all.

### Design tokens are Tailwind's, not a second system

Colours, spacing and type scale live in the Tailwind theme. The prototype's
custom properties were a stand-in for exactly that and are replaced rather than
kept alongside — two token systems is worse than either.

Dark mode stays media-query driven, as it is today. *(Zurückgenommen — siehe Nachtrag unten.)*

### Icons stay an inline SVG sprite

No icon font, no CDN, no per-icon request. The sprite lives in the base
template and icons are referenced by id.

## Consequences

- The build job is a deployment step, not just a development one. ADR 12's
  "copy the repo, `uv sync`, no build step" no longer holds for the web
  process; the Run entrypoint is untouched and still needs nothing.
- The build needs network access once: Tailwind's binary arrives with
  `uv sync`, the two libraries are fetched by the build. Both are pinned by
  version and verified by SHA-256, so a silently swapped file fails the build
  instead of reaching a page.
- ADR 3's "no build step" no longer holds literally. Its substance — no
  websocket, no client-side framework owning the page, server-rendered HTML —
  does.
- Alpine is a client-side framework in the narrow sense. It is bounded to
  ephemeral view state by the rule above; the moment application state starts
  living in Alpine rather than the database, this decision has been misused.
- The prototype's hand-written CSS is a throwaway and does not migrate.

## Nachtrag (22.09.2026, #19): Dunkel ist eine Wahl, keine Messung

Oben stand „Dark mode stays media-query driven, as it is today." Das galt
zwei Monate und hatte eine Folge, die erst auffiel, als jemand einen Knopf
wollte: **eine Regel unter `@media (prefers-color-scheme: dark)` lässt sich
nicht wegklicken.** Wer die Anwendung dunkel will, während sein System hell
steht, hatte keine Möglichkeit — und ein Schalter hätte sie ihm auch nicht
geben können, ohne die Palette an eine andere Bedingung zu hängen.

Jetzt gilt: **die Palette hängt an `color-scheme`, nicht an der Medienabfrage.**
Jede Farbe trägt beide Werte in einem `light-dark()`, und welcher gilt,
entscheidet ein Attribut am Wurzelelement — ohne Attribut steht
`color-scheme: light dark`, also weiterhin „dem System folgen" als
Voreinstellung.

Zwei Gewinne, die nicht der Anlass waren:

- Die dunklen Werte standen vorher **zweimal** da, in einem eigenen Block mit
  denselben dreizehn Namen. Eine neue Farbe dort zu vergessen war ein stiller
  Fehler. Jetzt steht jede Farbe einmal, und ein Test hält es fest.
- `color-scheme` färbt auch, was der Browser selbst zeichnet: Auswahlfelder,
  Bildlaufleisten, Datumswähler. Das Sortierfeld aus #37 folgt der Wahl,
  ohne dass eine Zeile dafür geschrieben wurde.

`light-dark()` setzt Chrome/Edge 123, Safari 17.5 und Firefox 120 voraus
(alle Frühjahr 2024). Das Werkzeug läuft im eigenen Netz auf den eigenen
Geräten; ein älterer Browser bekäme die hellen Werte und eine lesbare Seite.

Die Wahl selbst gehört zu Alpine und in den Browserspeicher, nicht in die
Datenbank: sie ist keine Aussage über den Geschmack der Leserin, sondern
darüber, wie hell das Zimmer gerade ist.
