# 40. Ein Hintergrunddienst holt nach

Alle Arbeit außerhalb einer Anfrage — der Lauf, der enge Lauf, der Steckbrief —
wird ein **Auftrag** in einer Warteschlange, und ein eigener **Hintergrunddienst**
arbeitet sie ab. Einen festen Termin gibt es nicht: der Dienst **holt nach**, was
nach der **Kadenz** fällig ist. Einzelheiten in #99, #100 und #98.

## Kontext

Buchfink soll an zwei Orten gleich gut laufen: lokal auf einem Rechner, der oft
zugeklappt ist, und dauerhaft auf einem Server. Bisher brauchte beides
verschiedene Wege, und die Hintergrundarbeit lief über drei Mechanismen:

- der **Lauf** als Kindprozess der Oberfläche, mit Dateisperre und
  Prozessnummer-Verfolgung (`web/runs.py`). Die Prozessnummer erzwang einen
  einzigen Container (docs/betrieb.md), sonst stand „läuft“ für längst
  beendete Läufe da;
- der **enge Lauf** als Thread *im* Webprozess — gegen ADR 3;
- der **Steckbrief-Auftrag** über den `Rechecker`, ebenfalls im Webprozess, mit
  eigenem Abfragen per htmx.

Gestartet wurde der Lauf von außen (Cron, Aufgabenplanung, systemd), dazu kam
intern `run_every_hours` — drei Betriebsanleitungen für dieselbe Sache. Ein
Zeitplaner mit festen Uhrzeiten verpasst seinen Termin, wenn der Rechner
schläft.

## Entscheidung

### Warteschlange und Dienst

- **Huey mit SQLite** (`SqliteHuey`) in einer eigenen Datei `data/jobs.db`,
  nicht in der Hauptdatenbank — sie soll nicht um Sperren konkurrieren. Keine
  eigene Job-Tabelle: Huey bringt Consumer, Wiederholungen und periodische
  Aufgaben mit.
- **Zwei Prozesse, ein Befehl.** `ebw serve` startet Oberfläche und
  Hintergrunddienst (Huey-Consumer) und beendet beide gemeinsam. `ebw web` und
  `ebw worker` gibt es zusätzlich einzeln, für Docker oder zwei systemd-Dienste.
- **Im Webprozess läuft keine Arbeit mehr.** Die Oberfläche stellt Aufträge ein
  und liest ihren Stand; der enge Lauf und der Steckbrief werden Aufträge wie
  der große Lauf. ADR 3 gilt damit strenger als bisher.
- **Unter Windows Thread-Worker** — Prozess-Worker brauchen `SIGALRM`.

### Nachholen statt Termin

- Eine periodische Aufgabe prüft **alle 15 Minuten**: ist der letzte *fertige*
  Lauf älter als die Kadenz? Dann stellt sie einen Lauf ein.
- Die **Kadenz** ist eine Einstellung („Lauf alle N Stunden“, Voreinstellung
  24), steht in der Datenbank und ist auf der Übersicht änderbar. Das
  Prüfintervall ist fest. Eine Ruhezeit gibt es nicht.
- `ebw run` läuft sofort; mit `--wenn-faellig` prüft es dieselbe Kadenz, damit
  ein Cron-Aufruf jede Stunde nie doppelt läuft. `--fruehestens-nach` geht
  darin auf.

### Abstürze

Huey stellt **höchstens einmal** zu: ein Auftrag, der beim Absturz oder
Zuklappen gerade lief, ist verloren, und verpasste periodische Termine werden
nicht nachgeholt. Das Nachholen deckt beides ab:

- Ein verlorener Lauf ist beim nächsten Prüfen wieder fällig, denn der letzte
  *fertige* Lauf ist noch alt.
- Ein verlorener Steckbrief-Auftrag heißt: den Hammer noch einmal drücken.
- Einträge im Laufjournal, die auf „läuft“ stehen, ohne dass ein Dienst sie
  bearbeitet, markiert der Dienst beim Start als **abgebrochen** — dasselbe Wort
  wie bisher, nur ohne Prozessnummer.

Voraussetzung bleibt, dass jeder Auftrag **idempotent** ist: ein Lauf vergleicht
Stände, nicht Termine (ADR 4), ein Steckbrief wird nie überschrieben (ADR 5).

### Was die Oberfläche anzeigt

Den Stand eines Laufs liest die Oberfläche aus dem bestehenden **Laufjournal**,
nicht aus Hueys Speicher. Hueys Format bleibt ein Detail der Warteschlange.

### Benachrichtigung

Nach einem Lauf, dessen Tagesbericht etwas zu sagen hat, verschickt der Dienst
eine Nachricht über **Apprise** (#98). Die Adresse ist ein Geheimnis und steht
in `data/secrets.env` oder der Umgebung.

## Konsequenzen

- Die Prozessnummer-Verfolgung in `web/runs.py`, der Thread des engen Laufs und
  der `Rechecker` entfallen. Der Ein-Container-Zwang in docs/betrieb.md fällt
  weg; Oberfläche und Dienst können getrennt laufen.
- Lokal heißt Betrieb: `ebw serve` starten. Ein äußerer Zeitplaner ist nicht
  mehr nötig, aber möglich.
- Neue Abhängigkeiten: `huey`, `apprise`.
- Die Dateisperre aus ADR 4 bleibt als letzte Sicherung, falls `ebw run` und
  der Dienst gleichzeitig starten.
- Ein Auftrag, der während eines Absturzes lief, wiederholt sich nicht von
  selbst — das ist gewollt und durch das Nachholen gedeckt, nicht durch
  Wiederholungslogik.

## Nachtrag 25.10.2026: Umsetzung

- Der Dienst startet den Lauf weiterhin als **eigenen Prozess** und wartet auf
  ihn: der Lauf behält seine Ausgabe (`data/run-ui.log`), seine Sperre und seinen
  Rückgabewert, und ein Absturz darin reißt den Dienst nicht mit. Enger Lauf,
  Steckbrief und Erkennen laufen in den Fäden des Dienstes.
- Der Stand kleiner Aufträge und die Anforderung eines Laufs liegen in Hueys
  Schlüsselablage (`put`/`get`), nicht in seinen Ergebnissen. So können
  Oberfläche und Dienst getrennte Prozesse sein.
- Der Dienst meldet sich jede Minute. Ist die letzte Meldung älter als drei
  Minuten, stellt die Oberfläche nichts ein und sagt „Kein Hintergrunddienst“.
- „Abgebrochen“ setzt, wer die Lauf-Sperre hält: jeder Lauf beim Start und der
  Dienst beim Start und bei jedem Prüfen. Die Prozessnummer wird noch ins
  Journal geschrieben, aber nicht mehr gelesen.
- In Tests arbeitet ein Faden jeden Auftrag gleich nach dem Einstellen ab, durch
  dieselbe Schlange (`EBW_JOBS_INLINE`).
