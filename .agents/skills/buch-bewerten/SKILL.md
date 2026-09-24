---
name: buch-bewerten
description: Hält einzelne Titel oder eine YAML-Liste gegen das Leseprofil der Leserin — über `ebw judge`, der Code urteilt, nicht das Gespräch.
---

# Buch bewerten

Beantwortet „passt dieses Buch zu mir?" mit dem Urteil der Anwendung, nicht mit
einem eigenen: `ebw judge` (ausgeschrieben `uv run python -m ebook_watchlist.run
judge`) rechnet aus dem Steckbrief des Buchs und dem Leseprofil in der Datenbank
Sterne, Prozent und Begründung (ADR 33). Dieselbe Rechnung steht auf der
Buchseite und im Tagesbericht; was hier herauskommt, stimmt damit überein.

Dieser Skill **urteilt nicht selbst**. Er ruft den Befehl auf und liest das
Ergebnis vor. Er enthält keine Bewertungsregel, und er schreibt keine Sterne, die
der Befehl nicht ausgegeben hat.

## Ablauf

1. **Eingabeart bestimmen.**
   - **Einzelne Titel** (im Gespräch genannt): jeder Titel als eigenes
     Argument, die Autor:in nach einem senkrechten Strich.

     ```bash
     uv run python -m ebook_watchlist.run judge "Der Schwarm | Frank Schätzing" "Dark Matter | Blake Crouch"
     ```

   - **YAML-Datei** (Pfad genannt): eine Liste von Einträgen mit `title` und
     `author`. Der Befehl schreibt `stars` und `why` hinein; Kommentare,
     Reihenfolge und fremde Felder bleiben.

     ```bash
     uv run python -m ebook_watchlist.run judge --datei data/liste.yaml
     ```

2. **Entscheiden, ob das Modell gefragt werden darf.** Fehlt zu einem Titel der
   Steckbrief, legt ihn der Befehl an — ein Modellaufruf je Bündel von bis zu
   acht Büchern, einmal, gespeichert. Soll nichts angefragt werden (Kosten,
   kein Netz, nur nachsehen): `--nur-bekannte`. Dann bleibt ein Titel ohne
   Steckbrief als `fehlt` stehen.

3. **Ergebnis vorlesen.** Je Titel Sterne, Prozent mit Marken und den Kurztext,
   so wie der Befehl sie ausgibt. Dazu, woher das Urteil stammt:

   | Ausgabe      | Bedeutung                                                |
   |--------------|----------------------------------------------------------|
   | `vorhanden`  | Steckbrief war da; kein Modellaufruf                     |
   | `neu`        | Steckbrief eben angelegt und gespeichert                 |
   | `fehlt`      | kein Steckbrief, und nicht gefragt (oder kein Weg dahin) |
   | `unbekannt`  | das Modell kennt das Buch nicht; kein Urteil             |

   Ein `fehlt` oder `unbekannt` wird genannt, nicht ergänzt.

4. **Hinweise aus dem Befehl weitergeben.** „Kein Leseprofil": die Erstaufnahme
   unter `/intake` fehlt noch — ohne sie gibt es nichts, wogegen sich rechnen
   ließe. „Kein Weg zum Modell": weder `ANTHROPIC_API_KEY` noch eine angemeldete
   Claude-Code-Installation; es wird beurteilt, was einen Steckbrief hat.

## Richtlinien

- **Keine eigene Rechnung.** Kein Stern aus dem Bauch, keine Korrektur eines
  Ergebnisses, keine Begründung, die nicht aus dem Befehl stammt. Wirkt ein
  Urteil falsch, ist das ein Befund über Steckbrief oder Profil: melden und die
  Schärfung auf der Profilseite vorschlagen, nicht das Ergebnis anpassen.
- **Begriffe aus `CONTEXT.md`:** Steckbrief (Portrait), Urteil (Verdict),
  Übereinstimmung (Fit), Leseprofil (Reading Profile), Steckbrief-Ersteller
  (Portrayer).
- **Persönliche Lesedaten bleiben in `data/`.** Eine Buchliste liegt dort, nie
  unter `docs/` und nie in einem Commit, außer die Leserin verlangt es.
- **Profil und Vokabular werden nie angefasst.** Der Skill schreibt nur in die
  übergebene Liste.

<yaml-format>
Erwartetes Format einer Buchliste — `title` ist Pflicht, `author` hilft:

```yaml
# Bücher, die ich bewerten lassen will.
- title: Der Schwarm
  author: Frank Schätzing
- title: Dark Matter
  author: Blake Crouch
  hinweis: bleibt stehen, der Befehl kennt das Feld nicht
```

Nach dem Aufruf trägt jeder beurteilte Eintrag `stars` (1–5) und `why`
(Prozent und Marken, etwa `"63 % — hart, Katz und Maus"`).
</yaml-format>
