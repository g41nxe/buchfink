# 19. A rating gate in front of the discovery pile

Supersedes ADR 11's "no LLM and no classifier in v1". The shelf mechanism it
describes stays exactly as it is; what changes is that its output is now judged
before it reaches the reader.

## Context

ADR 11 decided to trust the shop's own shelving rather than classify anything,
on grounds of cost, caching and reliability. A day of real data shows what that
buys.

One Run (2026-09-04) produced 316 discoveries:

| Origin | Titles | Fit |
|---|---|---|
| Reference Authors | 122 | by construction |
| Two genre shelves | 194 | by coincidence |

The shelves are the newest hundred titles each, sorted by release date. "New,
and filed under Psychothriller" is not a statement about this reader. Sixty-one
percent of the pile is therefore untargeted, and the reader named it
unprompted — recommendations that are merely cheap are not recommendations.

Mechanical filters were measured before being proposed, and they are not the
lever: bundles (14), free filler (10) and single episodes (13) overlap to 29
titles, nine percent. A per-author cap inside a shelf would cut a further 35 —
ten writers supply 54 of the 194, one of them 20 — but the remainder is still
sorted by date rather than by taste.

The daily volume is not the problem. Run 3 brought **zero** new items; 316 is a
one-time backlog plus the fetch volume of each Run. What needed fixing was
relevance, not quantity.

## Decision

### The standing principle: quality before quantity

Few suggestions that fit well beat many that do not. Where a choice exists
between showing more and filtering harder, this project takes the stricter end.
An empty suggestion list is a good outcome, not a failure — the reader said so
in as many words, and it is the reason the threshold below is set generously
rather than cautiously.

This binds more than the gate. It rules out interface that presents volume as
achievement, and it is the tie-breaker for every later tuning decision.

### Three channels, two rules for reaching the reader

**A Watchlist Entry is always reported**, whatever it costs. Today its first
sighting is silent unless the price is already below the Strong Deal line,
which means putting a title on the watchlist and never being told it was even
found. That is a gap, not thrift.

**A discovery is reported only when it is a deal** — a new title from a
Reference Author on the same terms as one from a Thema. The reader chose this
after being shown what it costs (below), and chose it twice.

Two things follow, and the second is why the rule is better than it first
sounds.

*It means "under 5,00 €" on the day of discovery.* German fixed-book-price law
keeps beam from ever rendering a struck price, so the mid-band tier can only
recognise a discount against a *previous* Observation — and a newly discovered
book has none. On day one, only the Strong Deal line can fire.

*But nothing is thrown away.* Discoveries are still collected and still written
to the Snapshot; only the reporting is gated. A book found at 14,99 € waits
there silently and surfaces the day it drops — which is the mid-band tier
working exactly as designed, just later. The discovery pile stops being a pile
to work through and becomes a quiet watchlist that speaks up when something is
worth it.

The cost is a real one and is recorded rather than argued away: a new novel by
a Reference Author the reader follows closely stays silent at full price. Of
300 discoveries in a real Run, 65 sat at 10,00 € or more under an author the
reader reads. They are not lost — they are waiting for a price.

The gate below therefore runs *after* this rule, not before it: rating a book
nobody will be shown is waste.

> **Nachtrag aus dem Review (nach Ticket 23): die Ausnahme ist beendet.** Der
> Absatz oben stand von Anfang an so da — und der Code tat es nicht. Für
> Referenzautor:innen galt eine ausdrücklich als *vorläufig* bezeichnete
> Ausnahme: gemeldet zu jedem Preis, bis es ein Tor gibt, das nach Relevanz
> fragt statt nach dem Preis. Das Tor kam mit Ticket 12. Die Ausnahme blieb —
> im Code, im Docstring und im Namen ihres eigenen Tests
> (`..._until_the_gate_exists`).
>
> Sie ist jetzt entfernt: eine Entdeckung wird gemeldet, wenn sie ein
> Schnäppchen ist, von einer Referenzautorin wie aus einem Thema.
>
> Der Preis davon steht schon zwei Absätze weiter oben und gilt unverändert:
> ein neuer Roman einer Autorin, die die Leserin eng verfolgt, bleibt zum
> vollen Preis still. Solange kein Schlüssel gesetzt ist, urteilt auch niemand
> über ihn — dann ist der Preis wieder die einzige Regel, diesmal aber für alle
> drei Kanäle dieselbe. Verloren ist nichts: die Beobachtung steht im Snapshot
> und meldet sich an dem Tag, an dem der Preis fällt.
>
> **Und dieselbe Strenge gilt jetzt an der Hintertür.** Ein Preissturz einer
> Entdeckung lief am Tor vorbei — ein Buch, das mit einem Stern zurückgehalten
> worden war, meldete sich beim nächsten Nachlass doch. Das Tor misst einen
> Sturz nun am vorhandenen Urteil; ein *neues* holt es dafür nie ein, denn das
> Buch ist bereits beurteilt.

### Every discovery is rated once, and the rating is stored

A discovered book is scored against `docs/leseprofil.md` on the 0-5 star scale
that rubric defines (ADR 17). The stars, the justification and the rubric
version are kept in a table of their own.

> **Nachtrag aus der Umsetzung (Ticket 12):** *Nicht* an der `book`-Zeile, wie
> dieser Absatz zunaechst sagte. ADR 18 haelt fest, dass ein Buch nur entsteht,
> wo die Leserin eine Beziehung hat; ein Urteil dorthin zu schreiben haette pro
> Lauf dreihundert ungepruefte Buch-Zeilen erzwungen — genau das, was ADR 18
> abgelehnt hat. Der Schluessel ist deshalb der Fund: die ISBN, wo es eine gibt,
> sonst `(Quelle, Item-Id)`. Dasselbe Buch bei zwei Shops kostet damit ein
> Urteil, nicht zwei, und ein Buch, das spaeter eine Beziehung bekommt, findet
> sein Urteil ueber die ISBN wieder.

> **Nachtrag aus der Umsetzung (Ticket 21): wer geurteilt hat, steht im
> Schlüssel.** Solange es nur das Tor gab, war die Frage entbehrlich. Mit den
> dreizehn Urteilen aus `owned.yaml` und den Sternen, die die Leserin selbst
> vergibt, sind es drei Herkünfte — `model`, `conversation`, `reader` — und der
> Unterschied trägt ADR 17: eine 4 von ihr ist eine Tatsache, eine 4 vom Modell
> ein Vorschlag. Der Schlüssel ist deshalb `(subject, origin)` und nicht
> `subject` allein: beide dürfen nebeneinander stehen, keines überschreibt das
> andere, und die Seite zeigt sie getrennt statt gemittelt.
>
> Dazu kommt eine dritte Form von `subject`: `book:<id>`. Was ein Mensch sagt,
> gilt dem Buch, nicht dem Fund — er vergibt seine Sterne auf der Buchseite, und
> sie sollen gelten, egal über welche Quelle das Buch das nächste Mal
> hereinkommt. Das Tor fragt deshalb erst am Buch (Leserin, dann Gespräch) und
> erst danach am Fund; ein menschliches Urteil erspart den Aufruf ganz.
>
> Und es verfällt nicht mit einer neuen Maßstabsversion. Die Regel im Absatz
> unten gilt für Maschinenurteile: dass die Leserin ihren Maßstab schärft, ist
> kein Grund, ihre eigene Aussage für ungültig zu erklären.

Below a threshold the book never reaches the triage list.

> **Nachtrag aus der Nachschau (Ticket 20):** Und was durchkommt, trägt sein
> Urteil sichtbar mit — Sterne, Konfidenz und Begründung stehen im Digest unter
> dem Vorschlag. Gespeichert und nie gezeigt war die Begründung für niemanden
> nachprüfbar, obwohl sie der Grund ist, den ein Vorschlag mitbringt
> (Ticket 14). Die Triage-Oberfläche zeigt sie noch nicht; das gehört zu der
> Überarbeitung, die dieser ADR unter "Consequences" ohnehin verlangt.

Rating is keyed to the book and its rubric version, so a Run re-rates nothing:
a book already judged under the current rubric is passed over. Raising the
rubric version invalidates the cached judgements deliberately — that is the one
event that should cause a re-rating, and it is the reader's own act.

### A model does the rating, not a rule set

The rubric's axes are cat-and-mouse structure, isolated settings, tone and pace.
These are judgements, not keywords, and the only text available is a teaser the
shop truncates at 219 characters. A keyword rule over that would produce
confident nonsense — the failure mode this project has spent its effort avoiding
(ADR 7, ADR 8).

The reader settled the underlying question during the ADR 17 grilling: the
machine may award stars. This is where that is honoured.

Claude Haiku is the default: a few hundred tokens per book, some tens of new
books a day, and the judgement is a bounded one against a rubric supplied in
full. The model is named in configuration, not in code.

### What leaves the machine, and what does not

The prompt carries the rubric and the book's public metadata — title, author,
blurb, shelf, price. The rubric is the reader's taste, written down. That is
personal data leaving a machine that otherwise deliberately holds no
credentials and talks to nobody (ADR 1, ADR 6).

The reader was told this before choosing and chose the model. It is recorded
here because a later reader of this repository would otherwise not know the
trade was made knowingly. No watchlist, no owned books, no e-mail address and
no library identity are ever sent.

### An unrated book is shown, never swallowed

No key, no network, a refusal, a malformed answer: the book is marked unrated
and goes into the triage list regardless. A gate that fails closed would hide
arrivals silently, which is the one behaviour this tool must never have — the
same reasoning that makes a broken Source an error rather than a quiet day
(ADR 7, ADR 15).

Rating happens after the Snapshot is written, so a rating outage costs judgement
and never costs history.

### Ein Lauf hat ein Budget

> **Nachtrag aus der Nachschau (Ticket 20):** Die Zahl der Urteile je Lauf ist
> begrenzt (`rating_budget` in `profile.yaml`, Voreinstellung 40). Der erste
> Lauf mit einem Schlüssel trifft den einmaligen Rückstand von 316 Entdeckungen
> und feuerte sonst 316 Aufrufe am Stück — dieselbe Zurückhaltung, die ADR 7
> jeder anderen ausgehenden Anfrage auferlegt, gilt auch hier. Was das Budget
> nicht mehr abdeckt, ist **unbewertet und wird gezeigt**, nie verworfen: sonst
> verschluckte ausgerechnet das Sparen die Neuzugänge. Ein gespeichertes Urteil
> kostet keinen Aufruf und deshalb kein Budget, also arbeitet sich der Rückstand
> über die nächsten Läufe von selbst ab.
>
> Der Digest nennt beides — wie viele Vorschläge unter dem Schwellwert
> zurückgehalten wurden und wie viele das Budget ungeprüft durchgelassen hat.
> Vorher stand das auf stderr, wo ein Cron-Job es wegwirft; ein zu scharf
> gesetzter Schwellwert sah damit aus wie ein ruhiger Tag. Ein Digest, der nur
> diesen Satz enthält, gilt deshalb nicht als leer.
>
> Ebenfalls entschieden: der Schlüssel wird weiterhin **nur** aus der Umgebung
> gelesen. Die Secrets-Datei aus ADR 6 gehört zur Bibliothekskennung — die ist
> die Identität der Leserin und gehört zum Profil. Dieser Schlüssel gehört dem
> Host, den ein Cron-Job ohnehin einrichtet; ein zweiter Ablageort im
> Datenverzeichnis wäre eine weitere Stelle, an der ein Geheimnis in ein Backup
> geraten kann.

> **Nachtrag aus #84 (03.10.2026): der Rückstand arbeitet sich nicht von
> selbst ab, und 40 bleiben.** Der Satz oben stimmt nicht: das Tor sieht nur
> die Änderungen eines Laufs, und ein Fund ist genau einmal eine Erstsichtung.
> Was über dem Budget lag, kommt im nächsten Lauf nicht wieder vorbei; es
> bleibt unbewertet in der Oberfläche stehen, bis es von Hand nachgeholt wird
> (Hammer-Knopf, `ebw rate --anzahl N`) oder sein Preis fällt.
>
> Zurückhalten, bis es beurteilt ist, wurde erwogen und verworfen: das
> verlangte eine eigene Warteschlange, einen neuen Zustand im Store — für einen
> Fall, der im Betrieb nicht mehr vorkommt. Der Anlass war der erste volle Lauf
> mit den Bibliotheksquellen (26.09.2026, 34 über dem Budget), und der lag an
> einer Aussaat, die nur je Interesse galt statt je Quelle und Interesse (#74,
> inzwischen behoben). Die Läufe danach blieben weit darunter: am 02.10. nach
> vier Tagen Pause 19 Steckbriefe, nichts über dem Budget. Ein höheres Budget
> hätte nur den Sonderfall verbilligt und den nächsten Ausreißer teurer gemacht
> (30–45 s je Steckbrief).

### The cheap filters stand in front of the gate

Bundles and collections, and anything priced at zero, are dropped before the
model sees them — they are junk by shape, and paying a model to say so is
waste. The Deal badge stops firing at zero cents for the same reason: free
filler was being decorated as a bargain.

These are ten lines and they are worth having on their own. They are not the
gate, and the numbers above are the reason they must not be mistaken for it.

## Consequences

- The Run gains a network dependency and a key. Both are optional by
  construction: without them the tool degrades to exactly today's behaviour.
- Genre shelves become useful rather than noisy, so they stay. Switching them
  off would have been the cheap fix and would have cost the only channel through
  which an unknown author can be found.
- The gate needs somewhere to keep a rating, which is a table of its own (see
  the Nachtrag above), and it needs the identity work of ticket 04 to key it
  on an ISBN — so it follows 04 rather than preceding it.
- The triage screen is designed against a pile of dozens, not hundreds. The
  prototype was built against 316 and that shaped its options; it should be
  revisited once the gate is in.
- A rating is a judgement about a book, so it belongs in the same place as the
  reader's own stars on owned books (ADR 17). Machine and human stars must stay
  distinguishable — a machine 4 is a suggestion, a human 4 is a fact.
- ADR 11's "genuinely reliable genre classification remains a possible v2
  feature" is discharged here, earlier than planned, because the measured noise
  justified it.
