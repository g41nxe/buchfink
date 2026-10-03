# 36. Ein Werk, ein Urteil

Übersetzungen und Originalausgabe sind ein Werk. Steckbrief und Sterne gelten
für das Werk, nicht für die Ausgabe; die Bücher selbst bleiben getrennt. Die
Einzelheiten stehen in #80.

## Kontext

*Gestohlene Erinnerung* und *Recursion* (Blake Crouch) standen als zwei Bücher
mit verschiedenen Sternen im Werkzeug. Jede Ausgabe bekam einen eigenen
Steckbrief, und das Modell streut stark: zwei Steckbriefe derselben Eingabe
teilen im Mittel 41 % der Merkmale (`docs/research/sprachfassungen-experiment.md`,
#81). Die Sprache selbst macht dabei keinen Unterschied (0,40 zwischen den
Sprachen, 0,41 innerhalb einer); es liegt am Verlagstext.

Schlimmer: der neueste Steckbrief der deutschen Ausgabe entstand ohne Text und
beschreibt *Dark Matter* („Ein Mann wacht auf und erkennt sein eigenes Leben
nicht wieder"). Der ältere, mit Text, beschreibt *Recursion*.

Die DNB nennt den Originaltitel einer Übersetzung (MARC 240) bei 36 ISBNs,
16 davon an Büchern. Englische Ausgaben kennt sie meist nicht.

## Entscheidung

### Was ein Werk ist

Normalisierte Autor:in („Crouch, Blake" → `blake crouch`) und normalisierter
Originaltitel. Der Originaltitel kommt bei einer Übersetzung aus der DNB; eine
Ausgabe ohne DNB-Originaltitel trägt ihren eigenen Titel als Originaltitel. So
treffen sich die deutsche Ausgabe (über die DNB) und die englische (über ihren
Titel) bei `blake crouch` + `recursion`.

Wo die DNB keinen Originaltitel nennt, bleibt jede Ausgabe ihr eigenes Werk —
der Zustand von heute. Der Originaltitel aus dem Steckbrief zählt nicht: das
Modell hat dort schon *Dark Matter* statt *Recursion* geschrieben.

Gebaut wie die Reihe (ADR 35): ein Schlüssel nach fester Regel, eine Zuordnung
je ISBN mit Herkunft.

### Welcher Steckbrief gilt

- Der Steckbrief hängt am Werk, sobald eines bekannt ist (`work:<schlüssel>`),
  sonst wie bisher an der ISBN. Eine zweite Ausgabe findet ihn und kostet
  keinen Aufruf.
- Unter mehreren gilt der neueste **mit Text**. Einer ohne Text gilt nur,
  solange es keinen mit Text gibt, und ersetzt nie einen mit Text.
- Kein Mittel über mehrere Steckbriefe (#81).
- Beim Umstellen wird je Werk nach dieser Regel einer gewählt; die anderen
  bleiben gespeichert und gelten nicht. Neu beschrieben wird nichts.

### Sterne, Watchlist, Stapel

- **Sterne** — die der Leserin und die des Modells — gelten für das Werk.
- **Die Bücher bleiben getrennt**: eigene ISBN, eigener Preis, eigene
  Verfügbarkeit.
- **Watchlist:** Besitz einer Ausgabe schaltet die Beobachtung einer anderen
  **nicht** ab. Die Zeile zeigt „hast du schon als …"; entfernen ist ihre
  Entscheidung. Wer das Werk auf Deutsch hat und im Original lesen will, hat
  eine Absicht, keinen Fehler — und mit weiteren Sprachen wird das häufiger.
- **Stapel:** ein Fund, dessen Werk sie schon hat, gemocht, doof gefunden oder
  ausgeschlossen hat, wird nicht vorgeschlagen. Unterscheiden nach Sprache lässt
  sich hier später, wenn weitere Sprachen dazukommen.

## Erwogen und verworfen

- **Den Originaltitel aus dem Steckbrief**: geraten, und nachweislich falsch.
- **Zwei Watchlist-Einträge zusammenführen**: verliert, welche Ausgabe wo zu
  haben ist.
- **Besitz beendet die Beobachtung des ganzen Werks**: still und falsch, sobald
  sie bewusst zwei Sprachen will.
- **Der Steckbrief mit dem längsten Text** oder **das Mittel**: der Text sagt
  über die Güte wenig, das Mittel half nicht (#81).
