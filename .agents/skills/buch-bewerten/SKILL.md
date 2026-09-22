---
name: buch-bewerten
description: Bewertet Bücher mit 0-5 Sternen danach, wie gut sie zum Leseprofil passen. Nimmt einzelne Titel entgegen oder verarbeitet eine YAML-Datei und schreibt die Bewertung dort hinein.
---

# Buch bewerten

Beantwortet die Frage „passt dieses Buch zu mir?" gegen zwei Dokumente statt
gegen ein Bauchgefühl (ADR 21):

- [`docs/bewertungsschema.yaml`](../../../docs/bewertungsschema.yaml) — **wie**
  geurteilt wird. Sterne, Begründungspflicht, `confidence`, Gegenprobe. Nicht
  versioniert, gilt für jedes Profil.
- [`docs/leseprofil.yaml`](../../../docs/leseprofil.yaml) — **wonach**. Die
  Beschreibung des Geschmacks, versioniert.

Dieselben zwei Dokumente benutzt das Bewertungstor im Lauf. Bevor es sie gab,
hatten Skill und Tor verschiedene Regeln bei derselben Sternskala.

## Ablauf

1. **Beides laden.** Immer zuerst `docs/bewertungsschema.yaml` **und**
   `docs/leseprofil.yaml` vollständig lesen. Nichts davon aus dem Gedächtnis
   rekonstruieren — die Dateien sind die Wahrheit und ändern sich.

   Die Gegenanzeigen stehen in `docs/leseprofil.yaml` selbst, unter
   `genres.passt_nicht` — nicht in einer zweiten Datei (ADR 32).

   Ergänzend `data/seed.yaml` lesen (Reference Authors, `liked_books`) und,
   falls vorhanden, `data/owned.yaml`. Diese Listen liegen lokal und sind nicht
   im Repo; fehlen sie, wird ohne sie bewertet und das im Ergebnis vermerkt.
   Sie sagen, womit die Datenbank einmal befüllt wurde — was heute gilt, steht
   dort, nicht in der Datei.

2. **Eingabeart bestimmen.**
   - **Einzelne Titel** (im Gespräch genannt): bewerten und im Chat antworten.
     Keine Datei anfassen, außer der Benutzer verlangt es.
   - **YAML-Datei** (Pfad genannt): jeden Eintrag bewerten und `stars` sowie
     `why` **in die Datei zurückschreiben**. Bestehende Kommentare und die
     Reihenfolge der Einträge bleiben erhalten.

3. **Fehlendes Wissen auflösen, nicht etikettieren.** Bevor ein Buch bewertet
   wird, muss bekannt sein, was das Leseprofil verlangt — dort steht, worauf es
   ankommt. Ist etwas davon unklar, **erst nachschlagen**: Websuche, oder der
   Klappentext auf der Produktseite der Shop Source.

   Eine Bewertung mit dem Vermerk „dazu kann ich nichts sagen" ist kein
   Ergebnis, sondern eine ausgelassene Arbeit.

4. **Bewerten.** Sterne strikt nach der Tabelle in `docs/bewertungsschema.yaml`.
   Für jedes Buch festhalten, welche Teile des Leseprofils tragen und welche
   nicht — das ist die Grundlage der Begründung und entscheidet die Sterne.

5. **Begründen.** Nach den vier Anforderungen aus Abschnitt 5 des
   Bewertungsschemas: benannter Teil des Profils, konkreter Beleg aus dem Buch,
   Brücke zum Leser, und bei allem unter fünf Sternen die ausdrückliche Angabe,
   was den Stern kostet.

6. **Belastbarkeit und Version festhalten.** Jede Bewertung trägt `confidence`
   (Bedeutung im Bewertungsschema, Abschnitt 3) und die **Profilversion**,
   gegen die sie entstand. `vermutet` ist hier ein Fehler: wer recherchieren
   kann, muss es — und dieser Skill kann.

7. **Ergebnis sichern.** Bei einer YAML-Datei nach dem Schreiben einmal einlesen
   und prüfen, dass die Datei gültig ist und alle Einträge eine Bewertung haben.
   Im Chat die Verteilung nennen, damit auffällt, wenn alles gleich bewertet
   wurde — eine Bewertung, die nicht unterscheidet, ist wertlos.

## Richtlinien & Best Practices

- **Nichts erfinden.** Lieber eine Recherche mehr als eine plausible Behauptung.
  Bleibt etwas nach der Recherche offen, wird es benannt und *nicht* in die
  Bewertung eingerechnet.
- **Keine Gefälligkeitsbewertung.** Wenn die Verteilung keine Bücher unter vier
  Sternen kennt, unterscheidet die Bewertung nicht mehr. Gegenanzeigen ziehen
  wirklich auf null.
- **Widersprüche melden, nicht glattbügeln.** Passt ein Buch, das der Benutzer
  offensichtlich mag, schlecht zum Profil, ist das ein Befund über das
  *Profil*. Melden und `leseprofil-schaerfen` vorschlagen, nicht die Bewertung
  hochdrehen.
- **Begriffe aus `CONTEXT.md`** verwenden: Reading Profile, Rating Scheme,
  Watchlist, Watchlist Entry, Reference Author, Source, Observation, Digest.
- **Profil und Schema werden nie angefasst.** Dieser Skill schreibt
  ausschließlich in die übergebene Buchliste — nie ins Leseprofil, nie ins
  Bewertungsschema, nie in `data/settings.yaml` oder `data/seed.yaml`. Ein Messgerät, das sich selbst
  kalibriert, misst nichts mehr. Änderungen am Profil gehören zu
  `leseprofil-schaerfen`.
- **Persönliche Lesedaten bleiben in `data/`.** Nie nach `docs/` oder in einen
  Commit schreiben, außer der Benutzer verlangt es ausdrücklich.

<yaml-format>
Erwartetes und erzeugtes Format einer Buchliste:

```yaml
- title: 1942 - Das Labor
  author: Paul Schüler
  stars: 3            # 0-5, null nur solange unbewertet
  why: >
    Begründung nach den vier Regeln aus docs/bewertungsschema.yaml.
  confidence: belegt   # belegt | teils | vermutet
  profilversion: 2     # Version aus docs/leseprofil.yaml
  hinweis: optional - Unklarheiten, abweichende Titelvarianten, Rückfragen
```

`title` und `author` sind Pflicht, alles andere wird vom Skill ergänzt.
Ein Eintrag ohne `author` wird vor der Bewertung recherchiert.
</yaml-format>
