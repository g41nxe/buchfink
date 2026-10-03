# 35. Eine Reihe ist eine Sache, und man kann sie beobachten

Die Reihe bekommt einen eigenen Platz im Datenmodell: eine Zeile je Reihe mit
normalisiertem Schlüssel, und eine Zuordnung je ISBN mit Band und Herkunft. Eine
Reihe kann man beobachten; ihre Bände stehen dann auf der Watchlist. Die
Einzelheiten stehen in #83 und #85.

## Kontext

Reihe und Band lagen an drei Stellen, keine davon normalisiert:

| wo | Reihe | Band | Bestand (03.10.2026) |
|---|---|---|---|
| `book` | `series` | `series_index` | 15 von 108, aus der DNB |
| `dnb_record` | `series` | `series_index` | 85 von 258 |
| `observation` | `series` | — | 7, nur Onleihe |

Jede Quelle schreibt den Namen anders: „Ein Wayward-Pines-Thriller" (DNB),
„Die Lincoln-Rhyme-Reihe" (Onleihe), „Red Rising Saga" (OverDrive). `MidSeries`
verglich nur kleingeschrieben; die Ausnahme „eine Reihe, die sie verfolgt" griff
deshalb über Quellen hinweg nicht. Und wer eine Reihe lesen will, musste jeden
Band einzeln auf die Watchlist setzen — die Watchlist beginnt mit einem
Abschnitt „Reihen-Einstiege".

Was die Quellen können (je eine Probe am 03.10.2026):

- **OverDrive** filtert nach `seriesId` und liefert die ganze Reihe mit
  `readingOrder` (Red Rising: 26 Titel, auch Teilbände wie „6.1"). Die
  `seriesId` steht schon in jedem Treffer.
- **Onleihe** hat eine Reihenliste (`simpleMediaList,…`), erreichbar über den
  Link „Reihe:" auf der Detailseite; die Karten nennen den Band.
- **beam** hat keine Reihenseite.

## Entscheidung

### Die Reihe und ihre Bände

- **Tabelle `series`**: ein Schlüssel, ein Anzeigename, und je Quelle ihre
  Adresse (OverDrive-`seriesId`, Onleihe-Reihen-ID).
- **Zuordnung je ISBN**: ISBN, Reihe, Band (als Text, wie `series_index`:
  „2", „6.1", „Sonderband"), Herkunft (`dnb`, `overdrive`, `onleihe`, `title`).
  Je ISBN und nicht am Buch, weil ein Buch erst durch eine Entscheidung der
  Leserin entsteht (ADR 18) und die Reihe schon für Funde gebraucht wird —
  dieselbe Begründung wie bei der Seitenzahl (ADR 34). Die Herkunft bleibt,
  weil die Rangfolge beim Lesen entschieden wird: DNB, dann OverDrive, dann
  Onleihe, dann Titel. Keine Angabe geht verloren, eine Abweichung bleibt
  sichtbar.
- `book.series`/`series_index` werden zu einer Ansicht darauf; die geplante
  Band-Spalte an `observation` aus #83 entfällt.

### Wann zwei Namen dieselbe Reihe sind

1. **Feste Regel für den Schlüssel:** kleinschreiben, Bindestriche zu
   Leerzeichen, vorn „Die/Der/Das/Ein/Eine" weg, hinten „Reihe/Serie/Trilogie/
   Saga/Zyklus/Thriller/Krimi/Roman/ermittelt/ermitteln" weg. „Die
   Cormoran-Strike-Reihe" → `cormoran strike`.
2. **Zusammenführen über die ISBN:** nennen zwei Quellen für dieselbe ISBN zwei
   Schlüssel, ist es eine Reihe. Das fängt „Ein Hunter-und-Garcia-Thriller"
   (DNB) gegen „Robert Hunter" (OverDrive).

Gleiche Schlüssel verschiedener Autor:innen werden nicht zusammengeführt.
Zusammenführen von Hand gibt es erst, wenn ein Fall beide Stufen verfehlt.

### Eine Reihe beobachten

- Die Reihe bekommt eine Beziehung zur Leserin, `watching`, über einen Knopf
  an der Reihenangabe im Kopf von Buch- und Fundseite.
- Jeder bekannte Band bekommt eine Buchzeile und `watching` mit der Herkunft
  „über die Reihe" — außer, sie hat schon eine Beziehung zu ihm (gekauft,
  gemocht, doof, ausgeschlossen). „Nicht mehr beobachten" schaltet nur die
  Beziehungen ab, die über die Reihe entstanden sind.
- Gefegt wird jede beobachtete Reihe bei jedem Lauf, je Quelle, die ihre
  Adresse kennt: OverDrive über `seriesId`, Onleihe über die Reihenliste, beam
  über eine Suche nach dem Namen, behalten wird nur, was von derselben
  Autor:in ist. Eine Adresse wird nicht gesucht; sie fällt an, sobald die Quelle
  einen Band zeigt.
- Ein neuer Band ist ein Watchlist-Treffer: gemeldet zu jedem Preis, ohne Tor
  (sie hat die Reihe selbst gewählt). Die Formregeln gelten weiter — keine
  fremdsprachigen Ausgaben, keine Kurzgeschichten. Der Folgeband-Filter
  natürlich nicht.
- Die Watchlist bekommt einen Filter nach Reihe; jede Zeile, jede Karte im
  Stapel und der Kopf von Buch- und Fundseite zeigen „Reihe · Band n".

## Erwogen und verworfen

- **Nur normalisierte Spalten an `observation` und `book`**: einfacher, aber
  ohne einen Ort, an dem „das ist dieselbe Reihe" einmal steht.
- **Die Reihe als Entdeckungskanal** neben Autor:in und Thema: Bände kämen als
  Vorschläge durchs Tor. Sie hat die Reihe aber gewählt wie einen Titel; ein
  Band gehört auf die Watchlist.
- **Eine Reihenseite** mit allen Bänden und Vorschau: vorerst nicht; der
  Filter auf der Watchlist reicht.
- **Den Band im Steckbrief erfragen**: siehe ADR 34, Nachtrag.
