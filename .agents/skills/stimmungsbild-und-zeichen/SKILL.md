---
name: stimmungsbild-und-zeichen
description: Legt für eine Familie des Vokabulars ein Stimmungsbild und ein Familienzeichen an — Motiv mit der Leserin klären, über Gemini im Browser erzeugen, nachbearbeiten, auf der Kachelseite prüfen (#55).
---

# Stimmungsbild und Zeichen

Jede Familie des Vokabulars — Merkmalsfamilien, Merkmale ohne Familie (sie
sind ihre eigene) und Grundhandlungen der Erzählmuster, zusammen 64 Karten —
trägt ein **Stimmungsbild** (Karte der Erstaufnahme) und ein
**Familienzeichen** (24er-Raster, überall vor dem Namen; `CONTEXT.md`, *Family
Sign*). Dieser Skill legt beides für neue oder misslungene Familien an, im Stil
der vorhandenen. Erzeugt wird über **Gemini im Browser**, nicht über die API.

Gelernt an der zweiten Runde mit 38 Motiven (27./28.10.2026). Was dabei trug und was nicht, steht in
[leitfaden.md](leitfaden.md) — vor jeder Runde lesen.

## Ablauf

1. **Fehlende Karten bestimmen.** Bilder und Zeichen liegen im Ordner der
   geltenden Fassung des Vokabulars, sonst in dem der bisherigen
   (`family_art.PICTURES_DIR`, `family_art.SIGNS_DIR`). Fehlende finden:

   ```bash
   uv run python -c "from ebook_watchlist.judging.portrait import load_vocabulary as l; from ebook_watchlist.web import family_art as a; v=l(); art=a.load(); print(sorted(f for f in {v.family_of(t).id for t in v.terms} if art.picture(f) is None or not art.sign(f)))"
   ```

   Gilt eine eigene Fassung, `EBW_VOCABULARY_DIR` dabei setzen. Einzelne
   Erzählmuster haben kein eigenes Bild; sie zeigen das ihrer Grundhandlung.

2. **Erst die Motivliste, dann Bilder.** Je Familie eine Idee mit Begründung:
   das *eine Ding* und eine Szene darum (Leitfaden, „Motiv“). Gegen den Bestand
   abgrenzen — die Kachelseite (Schritt 6) daneben legen. Gegenderte Bilder
   ausdrücklich ansprechen. **Die Leserin streicht und wählt, bevor erzeugt
   wird**; die meisten verlorenen Runden lagen am Motiv, nicht am Stil.

3. **Empfänger starten**, damit Bilder aus dem Browser auf die Platte kommen:

   ```bash
   uv run python .agents/skills/stimmungsbild-und-zeichen/werkzeug/empfaenger.py
   ```

   Im Hintergrund laufen lassen; er legt nach `.scratch/gemini/<id>.jpg` ab.

4. **In Gemini erzeugen** (eingebauter Browser, gemini.google.com, angemeldet
   ist die Leserin):
   - Prompt = Inhalt von [stil.txt](stil.txt) **unverändert**, dann die Szene.
     Regeln für den Szenentext im Leitfaden.
   - Eingabe: Feld `[aria-label="Einen Prompt für Gemini eingeben"]`
     fokussieren, tippen, `button[aria-label="Nachricht senden"]`.
   - Abholen: das Bild ist ein Blob-`img`; über ein Canvas als Data-URL lesen
     und `http://127.0.0.1:8455/x#name=<dataurl>` in einem neuen Tab öffnen.
     `name` nur `[a-z_]`, keine Ziffern. Danach zurück in den Chat.
   - Zeichen im selben Chat oder neu: Prompt aus dem Leitfaden, „Zeichen“.
   - Lehnt Gemini ab, umformulieren. Hat sich ein Bild in der Nacharbeit
     verrannt, von vorn — Nacharbeit im selben Chat ändert oft mehr als gewollt.
   - Eine Vorlage einfügen geht nur mit echtem Strg+V der Leserin.

5. **Nachbearbeiten** (je Aufruf `uv run --with numpy --with pillow python …`,
   Werkzeuge in `werkzeug/`):
   1. `creme.py quelle ziel [ids]` — Papier auf #F4ECDD.
   2. `rand.py quelle ziel 512 0.06` — einheitlicher Rand; Kastenszenen vorher
      in `QUADRAT`, `AUSSCHNITT` oder `STRECKEN` eintragen.
   3. `randmass.py ordner` — Ränder nachmessen.
   4. Kleine Farbfehler lokal statt neu erzeugen: `umfaerben.py` (Fläche ab
      Saatpunkt in Petrol), `fuellen.py` (Flächen eines Zeichens füllen).
   5. Endgültig: `rand.py … <PICTURES_DIR> 176 0.06` als `<id>.jpg`.
   6. Zeichen: `uv run --with numpy --with pillow --with potracer python
      werkzeug/vektor.py bild.jpg ziel.svgpath 1.0` (Strich 1,0/24; Flächen-
      zeichen `fest`), das Fragment als `<SIGNS_DIR>/<id>.svg`.

6. **Auf der Kachelseite prüfen**, hell und dunkel, gewählt und nicht gewählt:

   ```bash
   uv run --with numpy --with scipy --with pillow python .agents/skills/stimmungsbild-und-zeichen/werkzeug/kachelseite.py
   ```

   Ergebnis `.scratch/frontend/kacheln/index.html`, anzusehen über den
   Vorschau-Server „prototyp“ (`file://` geht nicht). Die Leserin entscheidet;
   oft erneuern, nicht erst am Ende.

## Richtlinien

- **Bilder und Zeichen bleiben lokal.** Ihre Dateinamen sind die Ids des
  Vokabulars (#59); nie committen, nie pushen. Die Werkzeuge in diesem Ordner
  dagegen sind Teil des Repos.
- **Kein Stil-Experiment ohne Auftrag.** `stil.txt` ist der Stil der Serie; wer
  ihn ändert, muss alle 64 neu machen.
- **Begriffe aus `CONTEXT.md`:** Stimmungsbild, Familienzeichen (*Family
  Sign*), Merkmalsfamilie (*Appeal Family*), Grundhandlung (*Master Plot*),
  Fassung des Vokabulars.
- **Die Leserin wählt.** Motive, Bilder und Zeichen werden ihr gezeigt, bevor
  etwas in den Ordner der Fassung kommt.
- **Kein API-Schlüssel, keine Kosten.** Der Weg geht über die angemeldete
  Gemini-Seite im Browser; die Sitzung gehört der Leserin und wird nicht
  verändert.
