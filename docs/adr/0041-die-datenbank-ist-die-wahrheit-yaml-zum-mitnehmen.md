# 41. Die Datenbank ist die Wahrheit, YAML ist zum Mitnehmen

Was eine Leserin einstellt, steht in der Datenbank und ist in der Oberfläche
änderbar. Dateien bleiben für den Betrieb, für Geheimnisse und zum Mitnehmen.
Löst ADR 32 ab (#104).

## Kontext

Nach ADR 32 lag die Konfiguration an drei Orten: `settings.yaml` (bei jedem
Lauf gelesen), `seed.yaml` (einmal beim Import) und die Datenbank. Wer eine
Schwelle ändern wollte, musste eine Datei bearbeiten — auf einem Server im
Container oder vom Telefon aus ging das praktisch nicht. Die Kommentare in
`examples/` widersprachen sich bereits darin, was wo gilt. Und der Schnellstart
begann mit dem Kopieren dreier Dateien.

## Entscheidung

**In der Datenbank, in der Oberfläche änderbar** — alles, was eine Leserin
einstellt:

- Watchlist, Besitz und die anderen Beziehungen (schon seit ADR 18),
- Autor:innen und **Themen**, denen sie folgt (Profilseite, „Genres und
  Autor:innen“),
- Kadenz, Startseitenzeilen, Startzahl des Stapels, Preisgrenzen, Budgets und
  die „Adresse von Buchfink“ (Übersicht, „Einstellungen“),
- Quellen an und aus (schon bisher auf der Übersicht).

Die gespeicherten Einstellungen liegen in der Tabelle `setting` und kommen in
`load_settings` *vor* der Prüfung über die Werte aus `settings.yaml`: es gelten
dieselben Regeln, und die Datei ist nur noch der Startwert. Gespeichert wird zur
Probe; ein Wert, an dem die Prüfung scheitert, wird zurückgenommen.

**In einer Datei oder der Umgebung** — was Betrieb oder Geheimnis ist:

- `data/secrets.env` oder die Umgebung: API-Schlüssel, Apprise-Adresse
  (`EBW_NOTIFY_URL`). Gelesen wird je Name, nicht die ganze Datei.
- Datenverzeichnis, Host und Port, das Vokabular.
- In `settings.yaml`: welche Quellen gebaut werden, mit ihren Bibliotheken und
  Sammlungen, Sprachen, Kontakt, der Wochentag des breiten Durchgangs. Die
  technische Seite der Quellen bleibt im Code.

**YAML zum Mitnehmen:** `ebw export [DATEI]` schreibt Einstellungen, Autor:innen,
Themen, Watchlist und Besitz in eine Datei; `ebw import DATEI` spielt sie über
denselben Weg wie das Saatgut ein — nichts doppelt, nichts zurückgesetzt.

**Erster Start:** Gibt es weder `settings.yaml` noch eine Datenbank, kopiert
Buchfink die Beispiele nach `data/` und spielt das Saatgut ein. Fehlt nur die
Datei, ist das weiterhin ein lauter Fehler.

## Konsequenzen

- Wer eine Einstellung ändert, tut das auf der Übersicht; die Zeile in
  `settings.yaml` gilt dann nicht mehr. Zurück zum Dateiwert geht es, indem man
  die Einstellung in der Datenbank zurücknimmt (`save_settings(..., None)`) —
  in der Oberfläche gibt es dafür noch keinen Knopf.
- `seed.yaml` und `ebw seed` bleiben für eine bestehende Erstbefüllung; neue
  Installationen brauchen sie nicht mehr selbst.
- Nicht im Export: Urteile, Steckbriefe, das Leseprofil und die
  Preisgeschichte. Die gehören in eine Sicherung der Datenbank
  (`scripts/sicherung.py`).
- Quellen-Sammlungen (OverDrive-Listen, Onleihe-Listen) stehen weiter in
  `settings.yaml`. Sie in die Oberfläche zu holen, wäre der nächste Schritt.
