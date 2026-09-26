# Versuch: Deutsch und Englisch desselben Buchs

Stand 26.09.2026. Anlass: *Recursion* und *Gestohlene Erinnerung* (Blake Crouch)
standen mit verschiedenen Sternen im Werkzeug. Skript:
[`prototyp/sprachfassungen.py`](prototyp/sprachfassungen.py), Rohdaten unter
`data/experimente/sprachfassungen/` (nicht in Git).

## Aufbau

Je Werk drei Steckbriefe aus dem deutschen, drei aus dem englischen Titel mit
Klappentext, dazu je einer ohne Text. Geurteilt hat die echte Geschmacksform der
Leserin. Die Wiederholungen trennen das Rauschen des Modells (gleiche Eingabe,
anderes Ergebnis) vom Unterschied zwischen den Fassungen.

Nur drei Werke kamen zustande. Der VÖBB-Katalog bei OverDrive führt viele
Ausgaben nur in einer Sprache (Gegenprobe: „Scalzi“ auf Englisch liefert acht
Titel, *Old Man's War* ist nicht darunter). Die deutschen Texte kommen deshalb
teils von beam aus dem eigenen Speicher; dann unterscheiden sich Sprache **und**
Verlagstext, wie im echten Fall.

| Werk | deutscher Text | englischer Text | Sterne DE | Sterne EN | Prozent DE ⌀ | Prozent EN ⌀ |
|---|---|---|---|---|---|---|
| *Dark Matter* | OverDrive, 249 Zeichen | OverDrive, 208 | 4 · 3 · 4 | 2 · 3 · 2 | 57 | 43 |
| *Recursion* | beam, 767 | OverDrive, 218 | 3 · 3 · 4 | 4 · 3 · 4 | 53 | 52 |
| *We* (Samjatin) | beam, 5673 | OverDrive, 240 | 4 · 3 · 4 | 4 · 4 · 3 | 59 | 59 |

Übereinstimmung der Merkmale (Jaccard), gemittelt über alle Paare:

| | innerhalb einer Sprache | zwischen den Sprachen |
|---|---|---|
| Merkmale | 0,41 | 0,40 |
| Familien | 0,50 | 0,51 |

## Befunde

1. **Die Sprache selbst macht keinen messbaren Unterschied.** Zwischen den Sprachen
   stimmen die Steckbriefe genauso gut (oder schlecht) überein wie zwischen zwei
   Durchgängen derselben Sprache. Bei *Recursion* und *We* liegen die Urteile im
   Mittel gleich.
2. **Das Modell streut stark.** Dreimal dieselbe Eingabe teilt im Mittel nur 41 %
   der Merkmale. Innerhalb jeder Dreiergruppe schwankt das Urteil um einen Stern —
   und die Schwelle liegt bei drei Sternen: ein Buch an der Grenze kann je nach
   Durchgang im Stapel stehen oder nicht.
3. **Wo die Fassungen auseinanderliegen, liegt es am Text.** *Dark Matter*: der
   deutsche Klappentext führt jedes Mal zu *fremd in einer neuen Welt* (3 von 3)
   und öfter zu *bedrohlich* und *vielschichtige Figur* — alles Merkmale, die die
   Leserin mag. Der englische erzählt anderes; seine Durchgänge landen bei 2 bis 3
   Sternen.
4. **Ohne Text kennt das Modell die Bücher**, mit richtigem Originaltitel, und
   urteilt vorsichtiger (2 bis 3 Sterne). Im Werkzeug selbst ging das schief: der
   Steckbrief ohne Text von 18:49 nannte für *Gestohlene Erinnerung* den
   Originaltitel *Dark Matter* — eine Verwechslung, keine Sprachfrage.

## Was das für das Werkzeug heißt

- **Der Unterschied im Werkzeug kam nicht von der Sprache**, sondern von zwei
  getrennten Büchern mit je eigenem Steckbrief, die neuesten ohne Text und einer
  davon verwechselt. Ein Steckbrief ohne Text darf keinen mit Text verdrängen.
- **Übersetzungen sollten sich einen Steckbrief teilen** (ein Werk, ein Urteil) —
  sonst würfelt das Werkzeug je Ausgabe neu.
- **Das Rauschen ist die größere Frage.** Ein Urteil an der Schwelle hängt vom
  Zufall eines einzelnen Aufrufs ab. Möglich: mehrere Steckbriefe je Werk und
  deren Mittel, Merkmale nur übernehmen, wenn sie in der Mehrheit der Durchgänge
  vorkommen, oder ein Modellaufruf mit Temperatur 0 (wo der Weg es erlaubt).

Drei Werke sind wenig; die Befunde 1 und 2 stützen sich auf 18 Steckbriefe mit
Text, Befund 3 auf ein Werk.
