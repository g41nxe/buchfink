# Leitfaden: was trägt und was nicht (#55)

Gelernt an 38 Motiven, 27./28.10.2026.

## Motiv

- **Das eine Ding finden und eine Szene darum bauen**: Bananenschale,
  Absperrband, Bombe mit Countdown, Lakenseil, Lupe. Abstrakte Symbole ohne
  Szene (Fragezeichen, Schlüssel, Kartenhaus) tragen nicht.
- **Gegen den Bestand abgrenzen.** Zu nah waren: Heldenreise und große Welt,
  Flucht und Fallen, Excalibur und Dolch, Drahtseil und Spannung.
- **Bild und Zeichen zusammen denken**: das Zeichen vereinfacht das Motiv
  (Tatort → Absperrband, Detektiv → Lupe).
- Bildausschnitt mitdenken: etwas weiter weg, ganzes Objekt, nicht zu zentriert.
- Negativraum gezielt einsetzen: Katz und Maus, Herz im Baum, Bühne.

## Prompt

- `stil.txt` **unverändert** voranstellen. Zusätze wie „full-bleed“, „fine
  detail“ oder ein eigener Stil (Siebdruck) verschieben ihn.
- Gegen Kästen genau dieser eine Satz: „Use the cream paper as negative space
  around the scene; no box, frame or rectangle behind it.“ Kastenszenen machen
  später ungleiche Ränder.
- **Nichts über Kanten schreiben.** „fades out softly into the cream paper“
  ergibt einen gesprühten Weichzeichner-Rand, „crisp, clean edges, no blur“
  einen harten Plakat-Look mit dicken Konturen. Beides weicht vom Stil ab.
- Kurz beschreiben; Details nur, wo die Szene sonst kippt. Bei Tatort, Duell,
  Bombe half am Ende *weniger* Vorgabe.

## Typische Bildfehler

- **Hände**: fehlender Daumen, zu viele Finger, ungleich gefärbt → „anatomically
  correct, with thumb“, „both hands in the same tone“.
- **Schatten**: falsche Richtung, je Fuß einer, dramatisches Licht macht
  Figuren schwarz → keine langen Schlagschatten, höchstens grob.
- **Farbe**: zu viel Petrol im Grund, zu viel Schwarz. Kleines lokal per
  Werkzeug (`umfaerben.py`, `fuellen.py`) statt neu erzeugen.

## Zeichen

- Prompt: „Drawn for a 24x24 pixel grid with 2-pixel strokes: at most N
  strokes …, Style like the Lucide icon set“.
- `vektor.py src dst 1.0` macht den Strich einheitlich 1,0/24; Flächenzeichen
  mit `fest`.
- Trägt: klare Silhouette, Kontrast über Negativraum oder umgekehrte Farbe.
- Scheitert: zu viel Detail (Schildkröte), zwei zu ähnliche Zeichen (skurril
  und schräge Figur).
