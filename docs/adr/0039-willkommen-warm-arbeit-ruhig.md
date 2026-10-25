# 39. Willkommen warm, Arbeit ruhig

Buchfink bekommt eine Bildsprache: warm, wo man ankommt oder nichts zu tun hat,
ruhig, wo man arbeitet. Die Farben tragen je eine Bedeutung. Einzelheiten und
Prüfwerte stehen in #112.

## Kontext

Das Banner und der Fink sind warm und verspielt gemalt (Petrol, Orange, Creme),
die Oberfläche war nüchtern (Georgia, neutrales Papier). Der Slogan stand in
zwei Reihenfolgen. Bernstein bedeutete zugleich „über ein Thema gefunden“
(Pille) und „Schnäppchen“ (Abzeichen am Cover).

Verglichen wurden vier Wärmestufen am Prototyp (`.scratch/frontend/waerme/`).
Die dezente Stufe war kaum vom Bestand zu unterscheiden, die kräftige setzte
Handschrift in die Navigation — dort, wo man am häufigsten liest.

## Entscheidung

- **Slogan:** „Weniger suchen. Mehr lesen.“ — in Satzschreibung, überall.
- **Wärme nach Häufigkeit:** Illustrationen und Bewegung gehören an seltene
  Stellen — Logo, erster Besuch, leere Zustände, Bestätigungen, README. Zeilen,
  Navigation und Knöpfe bleiben ruhig.
- **Zielbild ist die mittlere Stufe (A2′):** warmes Papier mit leichtem Korn,
  Kopf in Petrol, Fraunces für Überschriften, Titel und Preise (selbst
  ausgeliefert, keine fremden Server), Fließtext in der Systemschrift.
  Dunkelmodus in der Petrol-Familie, nicht in Braun.
- **Eine Farbe, eine Bedeutung:**
  - Orange — alles, was den Preis betrifft: Betrag und Schnäppchen-Abzeichen.
  - Gelb — nur die Sterne.
  - Petrol — Marke und Handlung (Knöpfe, Links, Zeichen); Abschnittstitel
    stehen in Textfarbe, damit sie nicht wie Links aussehen.
  - Das Thema einer Pille trägt das Wort, nicht die Farbe.
- **Bewegung** nur ohne Wunsch nach reduzierter Bewegung, sonst eine Blende;
  Knöpfe geben beim Drücken auf 0,96 nach.

## Konsequenzen

- Die Tokens in `app.css` ändern sich; jedes Textpaar ist hell und dunkel
  gemessen (mindestens 4,5:1, Zeichen 3:1) und liegt in sRGB.
- Umgesetzt wird über die Bausteinseite `/_design` (#113), nicht Seite für
  Seite.
- Das Banner muss mit dem neuen Slogan neu entstehen.
- Die Knopfrahmen bleiben schwach (1,45:1), wie bisher — die Knöpfe erkennt man
  an ihren Zeichen. Wird das ein Problem, ist es eine Frage der Barrierefreiheit,
  nicht dieser Entscheidung.
