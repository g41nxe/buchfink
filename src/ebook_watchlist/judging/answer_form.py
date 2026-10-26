"""Die Grundlage des Fingerabdrucks: die Anweisung vom 26.09.2026 (ADR 43).

Bis #69 rechnete der Abdruck die lebende Anweisung (``TEMPLATE``) und das
Vokabular. Jede geschärfte Regel verwarf damit jeden gespeicherten
Steckbrief — am 26.10.2026 wären das 467 Bücher gewesen. Seitdem rechnet er
diesen eingefrorenen Wortlaut: die Steckbriefe des Bestands behalten ihren
Abdruck, und ``TEMPLATE`` darf sich ändern.

Hier ändert sich nichts. Wer eine neue *Bedeutung* einführt — ein anderes
Pflichtfeld, eine andere Antwortform —, legt eine ``ANSWER_FORM_V2`` an und
lässt ``fingerprint`` sie rechnen; damit gelten alle alten Steckbriefe als
veraltet, und das soll eine Entscheidung sein. Ein Test hält den Wortlaut
fest.
"""

#: Wort für Wort ``TEMPLATE`` vom 26.09.2026.
ANSWER_FORM_V1 = """\
Du legst den Steckbrief eines Buchs an. Er beschreibt, wie sich das Lesen
dieses Buches anfühlt, und gilt für jede Leserin gleich.

Zuerst: Welches Buch ist gemeint? Nenne Titel und Autor so, wie das Buch
wirklich heißt, und bei einer Übersetzung den Originaltitel. Ein Tippfehler im
Namen oder ein deutscher Titel darf dich nicht irreführen. Kennst du das Buch
nicht sicher und liegt kein Text bei, setze "bekannt" auf false und lass alles
andere weg. Liegt ein Klappentext bei, setzt du "bekannt" nie auf false: dann
beschreibst du das Buch nach dem, was dort steht, auch wenn du es nicht kennst.
Verwechsle es nicht mit einem ähnlich klingenden Buch.

Dann die Merkmale. Du wählst sie ausschließlich aus dem Vokabular unten und
gibst ihre id an; neue erfindest du nicht. Eine Leserin wird später sehen,
welche Merkmale du vergeben hast, und auswählen, welche davon sie an diesem Buch
gehalten oder verloren haben. Vergib also die Merkmale, die dieses Buch am
deutlichsten prägen.

Regeln:
- Vier bis acht Merkmale, ohne die Erzählmuster.
- Aus mindestens drei verschiedenen Dimensionen, höchstens drei aus derselben.
  Zähle vor der Antwort nach: hat eine Dimension mehr als drei, lass das mit dem
  geringsten Gewicht weg.
- Erzählmuster gehören nie unter "merkmale", sondern nur unter "erzaehlmuster".
  Was im Vokabular unter "Erzählmuster" steht, ist ein Muster, kein Merkmal.
- Was auf fast jedes Buch seines Genres zutrifft, nimmst du nur, wenn es hier
  deutlich stärker ausgeprägt ist als üblich. Ein Thriller ist nicht schon
  deshalb spannungsgeladen, weil er ein Thriller ist.
- Zu jedem Merkmal schreibst du einen Satz, der zeigt, wo es in DIESEM Buch
  steckt: eine Figur, eine Situation, eine Eigenart. Die Probe: Könnte derselbe
  Satz unter einem anderen Buch stehen, ist er falsch.
- Zu jedem Merkmal nennst du, worauf es beruht: "klappentext" (es steht im
  Text, der beiliegt) oder "wissen" (was du selbst über das Buch weißt). Das
  Wort genügt; zitiere keinen Satz.
- Zu jedem Merkmal nennst du sein "gewicht" in diesem Buch: "praegend" (es
  prägt das ganze Buch, ohne wäre es ein anderes), "deutlich" (es gehört klar
  dazu) oder "rand" (es kommt vor, trägt aber nicht). Meist prägen nur zwei
  oder drei das Buch; wer alles prägend nennt, unterscheidet nichts.
- Nichts erfinden.

Dann die Erzählmuster: was für eine Geschichte das Buch erzählt. Sie stehen
im Vokabular unter "Erzählmuster", jedes eingerückt unter seiner Grundhandlung.
- Ein bis drei, nur was die Geschichte als Ganzes trägt, nicht eine Episode.
- Das genaueste Muster, das zutrifft. Die Grundhandlung selbst vergibst du,
  wenn kein genaueres passt, oder zusätzlich, wenn sie das Buch als Ganzes
  trägt und das genauere Muster nur einen Teil davon.
- Zu jedem Muster ein Satz und ein Beleg wie bei den Merkmalen. Ein Muster
  hat kein Gewicht: es steht nur da, wenn es die Geschichte trägt.
- Ein Muster, das selbst die Wendung ist — etwa eine Erzählstimme, die sich
  erst spät als unzuverlässig erweist —, vergibst du nicht.

Keine Spoiler — die Leserin hat das Buch womöglich noch vor sich:
- Satz und Pitch verraten nichts, was nicht schon der Klappentext oder die
  ersten Seiten preisgeben: keine Wendung, keinen Täter, keinen Tod, kein
  Ende, keine Auflösung eines Rätsels, nicht wie ein Handlungsstrang ausgeht.
- Auch nichts, was die Figuren erst im Lauf der Handlung herausfinden — bei
  einem Krimi etwa, was die Opfer verbindet oder wie der Täter vorgeht.
- Bei einem Band aus einer Reihe auch nichts aus den früheren Bänden, was
  deren Ausgang verrät.
- Im Zweifel beschreibst du, wie es sich liest, statt was geschieht.

Nenne außerdem Genre und Untergenre auf Deutsch, so wie eine Buchhandlung das
Buch einordnen würde.

Und schreib den Pitch: ein bis zwei Sätze, höchstens 180 Zeichen. Zuerst, was
das Buch ist; dann, was es ausmacht. Wähle ein Bild, an dem dieses Buch hängt,
statt es zusammenzufassen. Beschreiben, nicht loben.

--- VOKABULAR ---
{vokabular}
--- ENDE VOKABULAR ---

--- BUCH ---
{buch}
--- ENDE BUCH ---

Antworte ausschließlich mit JSON in genau dieser Form:
{{"bekannt": true, "titel": "...", "autor": "...", "originaltitel": "... oder null",
  "genre": "...", "untergenre": "...", "pitch": "...",
  "merkmale": [{{"id": "...", "satz": "...", "beleg": "...",
                "gewicht": "praegend, deutlich oder rand"}}],
  "erzaehlmuster": [{{"id": "...", "satz": "...", "beleg": "..."}}]}}
"""
