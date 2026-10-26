# 42. Eine Seite je Werk; das Werk bleibt ein Schlüssel

Jeder Fund gehört über seine Ausgabe zu einem Werk, und jedes Werk hat eine
Seite mit allen Ausgaben und Quellen. Das Werk bleibt dabei, was ADR 36 aus ihm
gemacht hat: ein berechneter Schlüssel, kein eigener Datensatz. Die Sprachen,
die die Leserin liest, werden eine geordnete Einstellung. Einzelheiten in #114
und #111.

## Kontext

Ein Fund hing an *einer* Quelle und *einer* Produktnummer (ADR 18). Dasselbe
Buch bei beam und in der Onleihe hatte deshalb zwei Fundseiten, die je nur ihre
Hälfte zeigten: Preis hier, Ausleihbarkeit dort. Gemessen am 26.10.2026: 60
ISBNs stehen bei mehr als einer Quelle, 29 Werke haben mehr als eine Ausgabe.
Die Lücke aus #96 ist geschlossen: nur noch 5 von 1019 Funden haben keine ISBN.

Die Begriffe folgen dem bibliothekarischen Schichtenmodell (FRBR, IFLA LRM,
RDA): **Werk** ist die Schöpfung an sich, über Sprachen hinweg; was eine ISBN
bezeichnet, ist dort die *Manifestation* — hier **Ausgabe** (Edition), wie schon
in ADR 18. Die Sprachfassung (*Expression*) bekommt kein eigenes Wort, solange
niemand sie braucht.

## Entscheidung

### Werk und Ausgabe

- **Ausgabe** ist, was eine ISBN bezeichnet; ohne ISBN „Quelle + Nummer“.
- **Werk** ist der Schlüssel aus `work_entry` (ADR 36): je ISBN eine Zuordnung
  mit Herkunft. Jeder Fund hat damit schon ein Werk, ohne Migration.
- **Unter dem Werk-Schlüssel wird nichts gespeichert.** Steckbriefe, Sterne und
  Beziehungen bleiben an ISBN oder Buch und werden über das Werk nachgeschlagen.
  So schadet es nicht, wenn sich ein Schlüssel ändert — und er ändert sich
  regelmäßig: die DNB nennt einen Originaltitel oft erst Tage nach dem ersten
  Fund (ADR 25), und erst dann wissen wir, dass zwei Ausgaben ein Werk sind.
- **Adressen und Verweise nennen eine Ausgabe**, nie den Werk-Schlüssel:
  `/work/<isbn>`. ISBNs ändern sich nicht.
- **ADR 18 bleibt:** eine Buchzeile entsteht erst mit einer Beziehung.

Erwogen und verworfen: eigene Tabellen `work` und `edition` mit Nummern. Feste
Adressen und sichtbare Handkorrekturen sprächen dafür; dagegen standen eine
Migration über Beobachtungen, Steckbriefe, Sterne und Beziehungen, ein Bruch mit
ADR 18 und vor allem das Verschmelzen: Werke wachsen im Betrieb zusammen, und
alles, was am Werk gespeichert wäre, bräuchte dann Regeln, welcher von zwei
Einträgen gilt. Der Weg dorthin bleibt offen — `work_entry` ist schon die
Zuordnung Ausgabe → Werk.

### Eine Seite je Werk (#111)

- `/work/<isbn>` zeigt das Werk dieser Ausgabe: oben das Urteil in Stufen
  (#110), dann „Was du dazu sagst“ wie heute, dann **Ausgaben und Quellen** —
  je Ausgabe ihre Kacheln mit Preis und Verfügbarkeit. Beobachtungen, Reihe und
  Nachschärfen über alle Ausgaben.
- `/book/<id>` und `/discovery/<quelle>/<nummer>` leiten dauerhaft dorthin.

### Eine Zeile je Werk

Stapel, Startseite und Tagesbericht zeigen eine Zeile je Werk. Sie vertritt die
Ausgabe in der bevorzugten Sprache, darunter ausleihbar vor günstig; die anderen
stehen als „auch als …“ dabei. Die Watchlist bleibt je Ausgabe (ADR 36).

### Die Sprachen der Leserin

- `languages` wird eine **geordnete Liste** und eine Einstellung der Leserin,
  auf der Übersicht änderbar (ADR 41); die Datei ist nur Startwert.
- **Funde** in nicht gewählten Sprachen erscheinen nicht (wie #10). Unbekannt
  ist nie fremd.
- **Die Watchlist** ordnet nach der Rangfolge zu: zuerst eine Ausgabe in der
  ersten Sprache, dann der zweiten, erst danach irgendeine — und sagt dann „nur
  auf Englisch zu haben“, statt den Titel zu verlieren. Angebote anderer
  Ausgaben desselben Werks meldet sie nur in gewählten Sprachen. Eine
  ausdrücklich festgelegte Ausgabe wird geprüft, in welcher Sprache auch immer.
- Gesucht wird weiter überall; gefiltert wird danach.

## Konsequenzen

- Die Fundseite als eigene Vorlage entfällt; Buch- und Fundseite werden eine.
- Handkorrekturen („dasselbe Werk“, „nicht dasselbe“) wären Einträge in
  `work_entry` mit Herkunft `manual`. Gebaut wird das erst, wenn eine falsche
  Zuordnung stört (eigenes Ticket).
- Die feste Reihenfolge „erst Deutsch, dann jede Sprache“ der Zuordnung (#77)
  geht in der Rangfolge auf.
