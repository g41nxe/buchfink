# Die Geschmacksform im Kreis zeichnen

Stand 26.09.2026, Recherche. Die Frage: Wie zeichnet man die Geschmacksform so als
Spinne oder Kreisdiagramm, dass **alle** Merkmale sichtbar und lesbar sind, und wie
legt man auf der Buchseite ein Buch darüber? Die Leserin schlägt vor, die Sektoren
nach Familien oder Dimensionen zu bilden und die einzelnen Merkmale darin aufgehen
zu lassen. Diese Notiz prüft den Vorschlag an den Quellen und an den echten Daten und
endet mit einer Empfehlung für `web/spider.py`. **Nichts davon ist umgesetzt.**

**Kurz:** Ja zu Sektoren, aber **ein Sektor je Dimension**, darin **ein Platz je
Familie**, und statt eines Polygons ein **Balken je Familie, der vom Ring „egal“ nach
außen oder innen reicht**. Alle 44 Familien haben einen festen Platz; was die Form
nicht kennt, bleibt als leerer Platz sichtbar. Das Buch liegt nicht als zweites
Polygon darüber, sondern als **Spur außerhalb des Randes**, und was es nicht trägt,
tritt zurück. Merkmale und Erzählmuster bleiben **zwei Figuren**. Auf dem Telefon
trägt der Kreis nur die Dimensionen; die Namen stehen in einer Liste darunter, mit
kleinen Balken auf einer gemeinsamen Skala. Die Fragen der ersten Fassung sind in
Abschnitt 7 nachgerechnet und entschieden. Für die Leserin bleibt eine
Geschmacksfrage mit Voreinstellung (Abschnitt 6).

---

## 1. Die Daten, nachgezählt

Gezählt mit `load_vocabulary()` und `load_judge()` gegen die lokale Datenbank
(26.09.2026, Skript nur lesend).

| | Merkmale | Erzählmuster |
|---|---|---|
| Wörter im Vokabular | 72 | 147 |
| Familien (Einzelwort = eigene Familie) | 44 (18 mit mehreren Mitgliedern) | 20 Grundhandlungen (18 mit mehreren; größte hat 24 Muster) |
| davon kennt die Form | 29 | 13 |
| davon \|Wert\| ≥ 0,15 | 24 | 11 |
| davon abgelehnt (< 0) | 7 (−1,0; −0,89; −0,51; −0,45; −0,19; −0,16; −0,15) | 2 (−1,0; −0,37) |
| genau am Anschlag +1,0 | 7 | 1 |
| Merkmale mit eigenem Wert (`TasteForm.term`) | 36 von 72 | — |

**Dimensionen**, nach dem ersten Mitglied einer Familie (so rechnen `spider.py` und
`Vocabulary.is_pattern` heute):

| Dimension (Frage) | Familien | davon bekannt |
|---|---|---|
| Tempo (wie es vorangeht) | 3 | 3 |
| Handlung (was passiert) | 6 | 5 |
| Stimmung (die Stimmung) | 16 | 10 |
| Figuren (die Figuren) | 12 | 7 |
| Stil (wie es geschrieben ist) | 7 | 4 |
| **zusammen** | **44** | **29** |

Die im Auftrag genannten Zahlen (8 / 9 / 17 für Handlung, Stil, Stimmung) zählen eine
Familie in **jeder** Dimension, in der sie ein Mitglied hat; das ergibt 49, nicht 44.
Fünf Familien liegen quer über zwei Dimensionen:

| Familie | Mitglieder nach Dimension | heute zugeordnet |
|---|---|---|
| rasant | Tempo + Handlung | Tempo |
| nervenaufreibend | Tempo + Stimmung | Tempo |
| anspruchsvoll | Stil (2) + Handlung (1) | Stil |
| witzig | Stimmung (4) + Stil (2) | Stimmung |
| hart | Stimmung (2) + Stil (1) | Stimmung |

Die Zuordnung „nach dem ersten Mitglied“ und „nach der Mehrheit der Mitglieder“ ergibt
bei allen 44 Familien dasselbe.

**Was die heutige Spinne zeigt:** höchstens 12 Achsen (`MOST_AXES`), die stärksten.
Von 29 bekannten Merkmalsfamilien fehlen also **17**, darunter 12 mit \|Wert\| ≥ 0,15.
Die 15 unbekannten Familien fehlen ohnehin. Nichts im Bild sagt, dass etwas fehlt.

**Familie gegen Merkmal:** Meist liegen die Merkmalswerte nahe am Familienwert. Die
deutliche Ausnahme ist *große Welt*: Familie −0,15, ihre beiden Merkmale +0,23 und
−0,47 (der Fall Z11 aus [urteil-methode.md](urteil-methode.md): *episch angelegt*
abgelehnt, *Weltenbau* nicht). Ein Balken für die Familie allein verschweigt das.

---

## 2. Was die Quellen sagen

Gelesen im Volltext: Few 2005, Diehl/Beck/Burch 2010, Cleveland/McGill 1984,
Heer/Bostock 2010, Miller et al. 2019, Waldner et al. 2019, Gleicher et al. 2011,
die d3- und Vega-Lite-Dokumentation, Bostocks Observable-Quelltext. Nur Zusammenfassung
oder Titel zugänglich (IEEE- und Springer-Bezahlschranke): Albo et al. 2016,
Draper et al. 2009, Burch & Weiskopf 2014, Heijungs 2022, Noble et al. 1987. Aus
diesen wird nichts behauptet, was über ihre Zusammenfassung hinausgeht.

### 2.1 Grenzen der Spinne

- **Few (2005)**: Spinnen sind schwerer zu lesen als Balken; Positionen lassen sich
  entlang einer gemeinsamen linearen Achse viel leichter vergleichen (S. 2). Eine
  Rangfolge kann eine Spinne nicht zeigen, weil unklar ist, wo sie beginnt und in
  welcher Richtung man liest (S. 2). Wir bevorzugen symmetrische Polygone, egal was
  sie bedeuten (S. 3). Mehrere gefüllte Polygone übereinander nennt er unlesbar (S. 3).
  Als Rechtfertigung lässt er nur zyklische Daten gelten, etwa Tagesstunden (S. 4–5).
  Eine feste Obergrenze für die Zahl der Achsen nennt er **nicht** (eine
  automatische Zusammenfassung behauptete „4–5 Achsen“; im Text steht das nicht).
- **Albo, Lanir, Bak, Rafaeli (2016)**, laut Zusammenfassung: Im Vergleich mit
  Flower-Chart (OECD Better Life Index) und Circle-Chart war die Spinne am wenigsten
  wirksam und am wenigsten beliebt; die beiden anderen hingen von der Aufgabe ab,
  die Blume wurde klar bevorzugt.
- **Diehl, Beck, Burch (2010)**, zwei Studien (674 Teilnehmende in der ersten):
  Kartesische Darstellungen sind meist genauer und deutlich schneller. Radial ist
  aber eine **einzelne** Stelle besser zu merken (Beobachtung 2), und **Sektoren
  merkt man sich leichter als Ringe** (Beobachtung 7). Ihre Leitlinien: die
  wichtigere Dimension in Sektoren legen, eine erkennbare lokale Orientierung geben,
  Randbereiche für das Wichtigste nutzen (Abschnitt 6). Positionen auf Ringen etwa
  auf halbem Radius waren am schwersten zu merken (Beobachtung 5), und radial
  lernten die Teilnehmenden etwas langsamer, holten dann aber auf (Beobachtung 3).
- **Waldner et al. (2019)**, 92 Teilnehmende: Selbst für Tagesmuster, den
  klassischen Fall für Kreise, war das lineare 24-Stunden-Balkendiagramm am
  genauesten, schnellsten und beliebtesten (Abstract).
- **Reihenfolge der Achsen**: Miller, Zhang, Fuchs, Blumenschein (2019): Die Form
  eines Sternglyphen hängt stark von der Reihenfolge der Achsen ab; wird nach
  Unähnlichkeit sortiert, entstehen Stacheln, die beim Gruppieren helfen (Abstract).
  Sie berichten die Befunde von Klippel et al. (2009), wonach auffällige Formen das
  Urteil lenken und farbige Achsen helfen (Abschnitt 2). Für uns heißt das: Bei einem
  Polygon bestimmt die Reihenfolge das Bild, nicht nur die Daten.

**Flächenverzerrung durch das Polygon**, selbst nachgerechnet: Bei *n* gleich
verteilten Achsen mit Radien r₁ … rₙ ist die Fläche des Polygons
½ · sin(2π/n) · Σ rᵢ · rᵢ₊₁. Die Fläche wächst also mit dem **Produkt benachbarter
Werte** und hängt von der Reihenfolge ab: dieselben zwölf Werte ergeben je nach
Anordnung verschieden große Formen. Eine Ablehnung (heute Radius 0 in der Mitte)
reißt beide Nachbardreiecke auf fast null herunter, auch wenn die Nachbarn stark
gemocht sind. Der Eindruck „große Form = viel Geschmack“ ist deshalb falsch.

**Draper, Livnat, Riesenfeld (2009)** und **Burch & Weiskopf (2014)** sind die
üblichen Übersichten zu radialen Verfahren. Ihr Volltext war nicht zugänglich; diese
Notiz stützt keine Aussage auf sie.

### 2.2 Wahrnehmung: Position, Länge, Winkel, Fläche

- **Cleveland & McGill (1984)**, Abschnitt 3, Rangfolge von genau nach ungenau:
  (1) Position auf einer gemeinsamen Skala, (2) Positionen auf nicht ausgerichteten
  Skalen, (3) Länge, Richtung, Winkel, (4) Fläche, (5) Volumen, Krümmung,
  (6) Schattierung, Farbsättigung. Flächen werden systematisch unterschätzt
  (Exponent des Potenzgesetzes unter 1, S. 537 f.); die Werte per Potenz zu
  verzerren, lehnen sie ab, weil der Exponent von Mensch zu Mensch schwankt.
  Positionen auf nicht ausgerichteten Skalen schneiden besser ab als nackte Längen,
  weil ein Rahmen zusätzliche Anhaltspunkte gibt (S. 538).
- **Heer & Bostock (2010)** haben den Versuch über Mechanical Turk wiederholt: Die
  Rangfolge blieb erhalten, Position schlug Länge weiterhin deutlich.

Für einen Kreis heißt das: Die Speichen einer Spinne sind **Positionen auf nicht
ausgerichteten Skalen** (Rang 2), und nur, wenn jede Speiche einen erkennbaren Rahmen
hat (Ringe). Ein gefülltes Polygon oder ein Keil liest sich als **Fläche** (Rang 4).
Eine Liste mit Balken auf einer gemeinsamen Nulllinie ist Rang 1.

### 2.3 Gruppierte radiale Formen

- **Aromaräder**: Das Wine Aroma Wheel ordnet Begriffe nach Ähnlichkeit in drei
  Stufen, allgemein innen, genau außen (Noble et al. 1987, Abstract). Beim
  Coffee Taster's Flavor Wheel (SCAA/WCR 2016) wurden die Begriffe durch freies
  Sortieren und Clusteranalyse in Klassen und Ebenen gebracht; die neun Klassen
  stehen so im Rad, dass **ähnlichere Klassen näher beieinander** liegen
  (Spencer et al. 2016, Ergebnisse und Diskussion). Wichtig: **Diese Räder zeigen
  keine Werte.** Sie sind Landkarten eines Vokabulars, zum Nachschlagen des richtigen
  Worts. Als Vorbild taugen sie für die **Anordnung** (Gruppe → Mitglied,
  Ähnliches nebeneinander), nicht für die Kodierung von Stärke.
- **Sunburst**: d3 erzeugt Kreis- und Ringsektoren mit `d3.arc`; der Winkel 0 zeigt
  nach 12 Uhr, positive Winkel laufen im Uhrzeigersinn; `padAngle` zieht zwischen
  Nachbarn einen Abstand ab und hält die Kanten parallel (d3-shape, *arc*). Bostocks
  „Zoomable sunburst“ beschriftet einen Sektor nur, wenn er groß genug ist
  (`(d.y1 - d.y0) * (d.x1 - d.x0) > 0.03`), und dreht die Schrift entlang der
  Speiche, auf der linken Hälfte um 180° gewendet, damit sie nie auf dem Kopf steht:
  `rotate(x - 90) translate(y,0) rotate(x < 180 ? 0 : 180)`.
- **Kreisförmiges Balkendiagramm** (circular barplot): Holtz' Katalog data-to-viz
  (Praxisquelle, keine Studie) empfiehlt es nur bei vielen Kategorien (etwa über
  40) mit klarem Muster, rät zu einem großen inneren Loch (mehr als die Hälfte des
  Radius), weil die Balken sonst verzerrt wirken, und nennt als Stärke, dass sich
  Gruppen und die Einträge innerhalb einer Gruppe gut vergleichen lassen.
- **Rose / Polarflächendiagramm** (Nightingale): Hier trägt die **Fläche** eines
  Keils den Wert. Damit das stimmt, muss der Radius mit der **Wurzel** des Werts
  wachsen: d3 hat dafür `scaleRadial`, dessen Bereich intern quadriert wird, „so dass
  der Eingabewert der Fläche entspricht“ (d3-scale); das Vega-Lite-Beispiel
  *Radial Plot* setzt den Radius auf eine `sqrt`-Skala. Eine Rose mit negativen
  Werten gibt es nicht: eine negative Fläche lässt sich nicht zeichnen.
- **Keile aus einem Ring heraus** haben dasselbe Problem in kleinerem Maß. Ein
  Ringsektor zwischen den Radien a und b hat die Fläche θ/2 · (b² − a²). Mit dem
  Nullring bei 60 und ±1 bei 96 bzw. 24 wiegt ein Keil für +1 5616 Einheiten, einer
  für −1 nur 3024: **Gemochtes sähe fast doppelt so schwer aus wie gleich starkes
  Abgelehntes.** Balken mit **gleichbleibender Breite** haben das nicht, ihre
  Fläche ist proportional zur Länge.

### 2.4 Divergierende Werte im Kreis

Keine der Quellen behandelt −1 … +1 im Kreis eigens. Aus 2.2 und 2.3 folgt:

- Die **Null als Ring** ist eine gemeinsame Basislinie für alle Speichen; Ausschläge
  nach außen und innen sind dann Längen von einer Basis (Rang 2–3), keine Flächen.
- Der Radius muss **linear** sein, gerade nicht Wurzel: kodiert wird eine Länge,
  keine Fläche. Wurzelskalen gehören zu Keilen aus der Mitte (Rose).
- Ringe bei −1, 0 und +1 geben den lokalen Rahmen, den Diehl et al. und Cleveland &
  McGill fordern. Der Ring „egal“ liegt nahe dem halben Radius, dort, wo Diehl et al.
  Positionen am schlechtesten gemerkt fanden; der Ring muss deshalb deutlich
  gezeichnet sein, nicht nur angedeutet.

### 2.5 Ein zweites Objekt darüberlegen

- **Gleicher et al. (2011)** ordnen Vergleiche in Nebeneinander (juxtaposition),
  Übereinander (superposition) und ausdrückliche Kodierung des Unterschieds
  (explicit encoding). Übereinanderlegen setzt einen erkennbar **gleichen Raum**
  voraus; halbtransparentes Überblenden hat Probleme mit Durcheinander und trägt
  kaum mehr als zwei oder drei Objekte (Abschnitt 3.3). Übereinander wird oft mit
  ausdrücklicher Kodierung verbunden, um das Durcheinander zu beherrschen.
- **Few (2005)**: Mehrere gefüllte Polygone übereinander sind unlesbar (S. 3).

Heute liegen Leserin und Buch auf **derselben** Skala, obwohl sie verschiedene Dinge
messen: die Leserin einen Wert −1 … +1 (mag / lehnt ab), das Buch ein Gewicht 0 … 1
(wie stark es die Familie trägt). Ein Merkmal, das das Buch „am Rand“ trägt
(Gewicht 0,4), liegt so bei +0,4 und sieht aus wie „leicht gemocht“; eine Familie, die
das Buch nicht trägt, liegt auf dem Ring und sieht aus wie „egal“. Der gleiche Raum,
den Gleicher voraussetzt, ist nur scheinbar gleich.

### 2.6 Beschriftung vieler Sektoren

- Waagerechte Beschriftung (heute) funktioniert bis etwa ein Dutzend Achsen; bei 44
  überlappen sich die Namen oben und unten, wo sie nebeneinander stehen. Entlang der
  Speiche gedrehte Schrift braucht quer zur Speiche nur eine Zeilenhöhe; Bostocks
  Regel oben wendet sie links, damit man nie kopfüber liest.
- SVG `<title>`: wird nicht gezeichnet, Browser zeigen es „üblicherweise als
  Tooltip“, und es liefert eine zugängliche Kurzbeschreibung; es soll das erste Kind
  seines Elternelements sein (MDN). Auf Touchgeräten gibt es kein Überfahren mit der
  Maus; ein Tooltip ist dort keine Beschriftung, sondern bestenfalls ein Zusatz.
- Heute stehen auf dem Telefon Nummern an den Achsen und die Namen als Liste, weil
  die Namen sonst unter sieben Pixel fielen (Kommentar in `_spider.html`). Bei 44
  Plätzen wären es 44 Nummern im Kreis und eine lange Zuordnungsliste.

---

## 3. Die Ansätze im Vergleich

Geprüft an genau diesen Daten: 44 + 20 Familien, fünf Dimensionen, Werte −1 … +1,
„unbekannt ≠ egal“, ein Buch darüber, Telefon mit ~343 px Zeichenbreite.

| Ansatz | alle sichtbar? | negative Werte | unbekannt ≠ egal | Buch darüber | Telefon |
|---|---|---|---|---|---|
| A. Heute: Spinne, 12 stärkste Achsen | nein (17 von 29 fehlen) | Polygon zur Mitte | nicht darstellbar | zweites Polygon, falsche Skala | Nummern + Liste |
| B. Spinne mit allen 44 Achsen | ja, aber unlesbar | Polygon kollabiert an jeder Ablehnung | nur durch Lücke | zwei Polygone mit 44 Ecken | nein |
| C. Gruppierte Spinne (Polygon je Sektor) | ja | wie B, aber nur im Sektor | Lücke | wie B | nein |
| D. Aromarad / Sunburst Familie → Merkmal | ja (72 Merkmale!) | nur als Farbe | als leeres Feld | Markierung am Feld | nein |
| E. **Sektor je Dimension, divergierender Balken je Familie** | **ja** | **Balken nach innen** | **leerer Platz vs. Punkt auf dem Ring** | **Spur außerhalb des Randes** | **Kreis als Überblick + Liste** |
| F. Rose (Polarfläche) | ja | nicht möglich | leerer Keil | schwierig | nein |
| G. Kein Kreis: Liste mit divergierenden Balken | ja | ja | ja | ja | ja |

**A. Heute.** Hat die Probleme, die Few und Albo et al. beschreiben, und verschärft
sie durch die Auswahl: Die Form zeigt 12 von 29 bekannten Familien und sagt nicht,
dass sie auswählt. Die Reihenfolge nach Dimension ist gut, aber die Achsen wandern
mit jeder neuen Bewertung, weil sich die Auswahl ändert.

**B. Alle 44 Achsen als Spinne.** 8,2° je Achse; Beschriftung nur gedreht möglich.
Das Polygon hat 44 Ecken, seine Fläche hängt vom Produkt benachbarter Werte ab
(2.1), und jede der 7 Ablehnungen zieht eine Kerbe bis zur Mitte. Unbekannte Achsen
müssten auf irgendeinen Radius; jeder Radius behauptet einen Wert.

**C. Gruppierte Spinne.** Sektoren je Dimension mit Lücken, ein Polygon oder
Linienzug je Sektor. Besser als B, weil die Reihenfolge fest und gruppiert ist, aber
Kerben und Flächeneindruck bleiben. Ein Linienzug über unbekannte Plätze hinweg muss
unterbrochen werden, dann zerfällt die „Form“ in Stücke.

**D. Aromarad mit Merkmalen.** Innen die Familie, außen ihre Merkmale; das ist die
wörtlichste Umsetzung von „Merkmale darin aufgehen lassen“. Gegen die Daten spricht:
72 Merkmalsfelder, von denen nur 36 einen eigenen Wert haben; die übrigen erben den
Familienwert (`TasteForm.value`) und würden eine Genauigkeit vortäuschen, die es
nicht gibt. Die Leserin wird nach Familien gefragt, nicht nach Merkmalen (CONTEXT.md,
*Appeal Family*). Werte ließen sich nur als Farbe zeigen (Rang 6 bei Cleveland &
McGill), und die Aromaräder selbst zeigen keine Werte (2.3).

**E. Sektor je Dimension, Balken je Familie.** Siehe Empfehlung. Hält die Stärke der
Kreisform, die Diehl et al. belegen (Sektoren merkt man sich gut, eine Stelle findet
man wieder), und ersetzt das, was die Studien an der Spinne bemängeln (Polygon,
Fläche, Reihenfolge), durch Längen von einer gemeinsamen Basis.

**F. Rose.** Flächentreu nur mit Wurzelradius (d3 `scaleRadial`, Vega-Lite `sqrt`);
negative Werte sind unmöglich. Für eine Form, die ablehnen kann, ungeeignet.

**G. Kein Kreis.** Was Few, Diehl et al. und Waldner et al. für Genauigkeit
empfehlen würden. Verliert aber das Bild der Form, das im Glossar steht
(*Geschmacksform*: „like a spider graph“) und die Buchseite trägt. Als **Telefonansicht
unter dem Kreis** ist G die richtige Ergänzung (siehe 5.7).

---

## 4. Die Idee der Nutzerin, bewertet

**Sektor je Dimension, Familien darin: ja.** Das ist die Empfehlung. Belege: Diehl
et al. (die wichtigere Gruppierung in Sektoren), Spencer et al. (Ähnliches
nebeneinander), Miller et al. (feste, sinnvolle Reihenfolge statt einer, die das Bild
von den Daten abhängig macht). Die fünf Dimensionen sind die Fragen, die die Leserin
kennt („wie es vorangeht“, „die Stimmung“ …).

**Sektor je Familie, Merkmale als Speichen darin: nein.** Aus drei Gründen:

1. Die Leserin unterscheidet die Merkmale einer Familie nicht; genau deshalb gibt es
   Familien (CONTEXT.md). Eine Speiche je Merkmal zeigt eine Auflösung, in der sie
   nie gefragt wurde.
2. Die Hälfte der Merkmale (36 von 72) hat keinen eigenen Wert und erbt den der
   Familie; die Speichen einer Familie wären meist gleich lang.
3. Familien sind verschieden groß (1 bis 6 Merkmale, bei den Erzählmustern bis 24).
   Ein Sektor, der mit der Zahl der Merkmale wächst, gibt *witzig* sechsmal so viel
   Kreis wie *gemächlich*, obwohl beide für die Leserin eine Sache sind. Winkel je
   Sektor sollen mit der **Zahl der Familien** wachsen, nicht der Merkmale.

Der richtige Kern der Idee, „Merkmale gehen in der Familie auf“: **Die Familie ist
die Achse, ihre Merkmale sind Marken auf dieser Achse**, und zwar nur dort, wo ein
Merkmal der Familie widerspricht (heute *große Welt* und *Katz und Maus*). Siehe 5.4
und 7.4.

**Familien über zwei Dimensionen.** Sie gehören wie bisher zur Dimension ihres ersten
Mitglieds (entspricht hier auch der Mehrheit). Zusätzlich lässt sich die Reihenfolge
der Sektoren so wählen, dass vier der fünf Grenzgänger **an der Grenze** zu ihrer
zweiten Dimension stehen: **Tempo · Handlung · Stil · Stimmung · Figuren**
(statt der Dateireihenfolge Tempo · Handlung · Stimmung · Figuren · Stil). Dann steht
*rasant* am Ende von Tempo neben Handlung, *anspruchsvoll* am Anfang von Stil neben
Handlung, *witzig* und *hart* am Anfang von Stimmung neben Stil. Nur
*nervenaufreibend* (Tempo + Stimmung) bleibt ohne Nachbarn. Die Dateireihenfolge
schafft nur einen von fünf (nachgezählt in 7.2).

**Familienwert und Merkmalwert.** Beide gibt es. Der Balken zeigt auf **beiden**
Seiten den **Familienwert**, damit dieselbe Familie überall gleich lang ist. Auf der
Buchseite zeigt ein bernsteinfarbener Querstrich den Wert, mit dem das Urteil für
dieses Buch gerechnet hat (stärkstes Merkmal des Buchs in der Familie), wo er
sichtbar abweicht. So widerspricht das Bild der Begründung nicht, und die Balken
bleiben gleich (7.5).

---

## 5. Empfehlung: Geometrie für `spider.py`

### 5.1 Plätze und Winkel

- **Ein Platz je Familie, alle 44**, auch die unbekannten. Feste Plätze: eine Familie
  springt nicht, wenn sie bekannt wird oder die Form sich ändert (Diehl et al.:
  Positionen werden gemerkt und gelernt).
- **Ein Sektor je Dimension**, im Uhrzeigersinn **Tempo · Handlung · Stil ·
  Stimmung · Figuren**. Innerhalb des Sektors eine **feste** Reihenfolge, nicht nach
  Wert und nicht alphabetisch: Grenzgänger an die Grenze zu ihrer zweiten
  Dimension, Gegensatzpaare nebeneinander, der Rest in Dateireihenfolge (7.2).
- **Winkelmaß**: jede Familie eine Einheit, jede Lücke `GAP = 1,5` Einheiten.

  ```
  u   = 360° / (N + GAP · K)          # N Plätze, K Sektoren (= K Lücken)
  φ_k = (GAP · k + Σ_{m<k} n_m) · u   # Mitte der Lücke vor Sektor k
  θ_j = (GAP · k + GAP/2 + j + 0,5) · u   # Mitte von Platz j (fortlaufend), in Sektor k
  ```

  Winkel im Uhrzeigersinn ab 12 Uhr (wie `d3.arc`). Die erste Lücke liegt genau oben
  und markiert den **Anfang** (Few: bei der Spinne ist unklar, wo sie beginnt).
  Merkmale: N = 44, K = 5 → u = 6,99°, Lücke 10,49°. Erzählmuster: N = 20, K = 1
  (nur die Anfangslücke) → u = 16,74°.
- Umrechnung wie heute in `_point`: `x = C + r·sin θ`, `y = C − r·cos θ`.

### 5.2 Radius

Linear, mit dem Ring „egal“ als Basis, symmetrisch nach innen und außen:

```
R_ZERO = 60      # Ring „egal“ (gestrichelt, wie heute)
SCALE  = 36      # Einheiten je Wertpunkt
r(v)   = R_ZERO + SCALE · v     # +1 → 96, −1 → 24
R_RIM  = 100     # äußerer Kreis (Rahmen), 4 Einheiten Luft über +1
```

Dünne Hilfsringe bei 24 (−1) und 96 (+1), der Ring „egal“ kräftiger als heute
(2.4). Das Loch innen (Radius 24) ist 40 % des Radius; kleiner geht nicht, weil
sonst die Balken an der Innenkante aneinanderstoßen (Bogen je Platz bei r = 24:
2,9 Einheiten).

### 5.3 Marken

- **Balken statt Polygon**: je bekannte Familie eine `<line>` von `r(0)` nach `r(v)`,
  **gleichbleibende Breite** 2,4 Einheiten, `stroke-linecap="butt"`. Gemocht
  `stroke-accent`, abgelehnt `stroke-danger`. Gleiche Breite heißt: gleich starke
  Ablehnung und Zuneigung sehen gleich schwer aus (Keile täten das nicht, 2.3). Und
  es ist das, was das Template schon kann: Linien zwischen zwei Punkten.
- **Kein Polygon und kein Umriss**, auch nicht je Sektor (7.3).
- **Bekannt und egal** (\|v\| < 0,05): ein kleiner Punkt auf dem Ring (`fill-soft`).
- **Unbekannt**: **keine Marke**; nur die Beschriftung, blass (`fill-hair`), im
  Tooltip „noch unbekannt“. So unterscheidet sich *weiß nichts* sichtbar von *egal*.

### 5.4 Merkmale in der Familie

Wo ein Merkmal der Familie **widerspricht** (anderes Vorzeichen, beide Beträge
mindestens 0,15), ein kurzer Querstrich (5 Einheiten, quer zur Speiche) bei
`r(Merkmalwert)`, dünn, in der Farbe seines Vorzeichens. Heute träfe das zwei
Familien: *große Welt* (Balken −0,15, Strich *Weltenbau* +0,23) und *Katz und Maus*
(Balken +0,21, Strich *Ungeheuer* −0,17). Bloße Abstufungen innerhalb einer
Familie bekommen keinen Strich (7.4). Der Tooltip nennt immer alle Merkmale mit
Wert.

### 5.5 Das Buch darüber

- **Buchspur** außerhalb des Randes: je Familie, die das Buch trägt, ein
  bernsteinfarbener Strich (`stroke-amber`, Breite 3,5) auf der Speiche von
  r = 102 nach r = 102 + 7 · Gewicht. Mit den heutigen Gewichten (prägend 1,0,
  deutlich 0,7, am Rand 0,4) also 7 / 4,9 / 2,8 Einheiten lang.
- **Der Wert, mit dem das Urteil rechnet**: Der Balken bleibt der Familienwert wie
  auf der Profilseite. Weicht der Wert des stärksten Buchmerkmals der Familie um
  mindestens 0,1 davon ab (3,6 Einheiten, am Schreibtisch etwa 5 px), ein
  bernsteinfarbener Querstrich bei `r(Urteilswert)` (7.5).
- Familien des Buchs, die **die Form nicht kennt**: ein hohler bernsteinfarbener
  Kreis auf der Spur. Damit wird sichtbar, was heute nur ein Satz in der Legende ist
  („… kennt dein Profil noch nicht, sie zählen nicht“).
- **Was das Buch nicht trägt, tritt zurück**: diese Balken mit 35 % Deckkraft. Die
  getragenen bleiben voll und ihre Namen fett (wie heute). Das Auge liest: *wo landet
  dieses Buch in meiner Form, und landet es in einer Einbuchtung?* Das ist
  Übereinanderlegen mit ausdrücklicher Kodierung (Gleicher et al.), ohne zwei Skalen
  zu vermischen.
- Erzählmuster: im Urteil zählt ein Muster ohne Gewicht (`overlap`: `p_mass += 1`);
  die Spur hat dort eine feste Länge.

### 5.6 Beschriftung am Schreibtisch

- **Familiennamen entlang der Speiche**, ab r = 112, Schriftgröße 9 Einheiten, mit
  Bostocks Drehung und `text-anchor` `start` rechts bzw. `end` links:
  `rotate(θ−90) translate(112,0) rotate(θ<180 ? 0 : 180)` um den Mittelpunkt.
  Abstand zweier Namen quer zur Speiche bei r = 112: 13,5 Einheiten, genug für eine
  Zeile. Der längste Name (*nichtmenschliche Figur*, 22 Zeichen) braucht etwa 105
  Einheiten; die Zeichnung ist damit etwa **434 Einheiten** breit.
- **Dimensionsnamen in den Lücken, innen**: in jeder Lücke ein Name entlang der
  Lückenmitte φ_k, von r ≈ 30 nach außen, klein, Großbuchstaben, `fill-soft`. Die
  Lücke ist bei r = 60 rund 11 Einheiten breit, genug für 7,5 Einheiten Schrift. So
  kollidieren sie nicht mit den Familiennamen außen.
- **Breite**: Damit 9 Einheiten nicht unter 11 px fallen, braucht die Figur etwa
  **34–38 rem**. Auf der Profilseite heißt das `max-w-2xl` statt `max-w-lg`; auf der
  Buchseite die Merkmalsfigur über die volle Breite statt zwei Figuren nebeneinander
  (`lg:grid-cols-2`), die Erzählmuster darunter oder daneben erst ab `xl`.
- **Tooltip** je Platz: `<g><title>witzig: gemocht (+1,0) · heiter +0,58 …</title>
  …</g>`, `<title>` als erstes Kind (MDN). Weil ein 2,4 breiter Strich schwer zu
  treffen ist, eine unsichtbare, platzbreite Trefferlinie (`stroke="transparent"`,
  `pointer-events="stroke"`) dazulegen. Das `aria-label` der ganzen Figur bleibt wie
  heute die vollständige Aufzählung.

### 5.7 Auf dem Telefon

- Dieselbe Zeichnung, **ohne Familiennamen**. Stattdessen die fünf
  **Dimensionsnamen waagerecht** außen an der Sektormitte (die heutige
  Anker-Logik aus `_spider`: `start`/`end`/`middle` nach der x-Richtung), 12 px.
  Breite etwa 2 × (100 + 6 + 56) ≈ 324 Einheiten → rund 1,06 px je Einheit bei
  343 px. Balken 2,6 px breit, Plätze am Rand 13 px auseinander: als **Gestalt**
  lesbar, nicht als einzelne Zahl.
- Darunter eine **Liste, nach Dimension gruppiert** in derselben Reihenfolge wie die
  Sektoren im Uhrzeigersinn. Je Zeile Name und ein kleiner divergierender Balken auf
  einer **gemeinsamen** Nulllinie (Cleveland & McGill Rang 1), innerhalb der Gruppe
  nach Wert sortiert. Unbekannte Familien je Gruppe in einer blassen Zeile
  („noch unbekannt: …“). Auf der Buchseite ein bernsteinfarbener Punkt an den
  Zeilen, die das Buch trägt.
- Keine 44 Nummern im Kreis. Wer mehr will: Antippen eines Sektors hebt seine
  Gruppe in der Liste hervor (Alpine, reiner Ansichtszustand, ADR 20). Nicht nötig
  für den ersten Schritt.

### 5.8 Merkmale und Erzählmuster: zwei Figuren

Zwei, wie heute und wie in der Rechnung (`overlap` rechnet die Muster als zweite
Spinne und hebt oder senkt das Urteil anders als die Merkmale). Eine Figur mit 64
Plätzen hätte 4,9° je Platz; die Namen stünden bei r = 112 nur noch 9,6 Einheiten
auseinander, und die Erzählmuster hätten als eine Dimension ohne Unterteilung einen
Sektor so groß wie zwei andere zusammen. Die Musterfigur nutzt dieselbe Geometrie
mit K = 1 (nur die Anfangslücke), Reihenfolge der Grundhandlungen wie in der Datei.

### 5.9 Skizze (Ausschnitt oben, Merkmale)

```
                    ·  ·  Lücke  ·  ·
          Figuren  /        |        \  Tempo
                  /   (12 Uhr: Anfang) \
      ─ Name ─   |          ┆           |   ─ Name ─          außen: Buchspur ▮ (amber)
               ▮ |  ▌   ▌   ┆   ▌  ▌    | ▮                   Rand      r = 100
               ▌ |  ▌   ▌   ┆   ▌  ▌  · |  ▌                  +1        r =  96
  - - - - - - - -┼--▌---▌---┆---▌--▌--●-┼--- - - - - -        egal      r =  60 (gestrichelt)
                 |      ▐   ┆          |                      −1        r =  24
                 |      ▐   ┆   (leer) |                      Loch
                      abgelehnt      ● egal   (leer) unbekannt
```

`▌` Balken nach außen (gemocht, Petrol), `▐` nach innen (abgelehnt, rot), `●` bekannt
und egal, leerer Platz: unbekannt, `┆` Lücke mit Dimensionsnamen innen, `▮` Buchspur.

### 5.10 Was sich in `spider.py` ändert

- `MOST_AXES` und die Auswahl der stärksten entfallen; `AXIS_FROM` wird höchstens
  noch die Schwelle für eine blasse Beschriftung.
- `Axis` bekommt: `dimension`, `angle`, `known`, die beiden Balkenenden
  (`bar_from`, `bar_to`), `label_transform` + `anchor`, `term_ticks`
  (Liste von Punktpaaren), `track_from`/`track_to` für die Buchspur, `carried`,
  `book_tick` (Querstrich beim Urteilswert, nur auf der Buchseite).
- `Spider` bekommt `sectors` (Name, Lückenwinkel, Punkt für den Namen innen und den
  Punkt für den waagerechten Namen auf dem Telefon); `reader_points` und
  `book_points` entfallen.
- Das Template zeichnet nur `<line>`, `<circle>` und `<text>`; keine Bögen, kein
  `<path>` nötig. Die Legende ändert ihre Wörter (Balken statt Fläche, Spur statt
  gestricheltes Polygon, leerer Platz = noch unbekannt).

---

## 6. Was die Leserin noch entscheiden muss

Die sieben Fragen der ersten Fassung sind in Abschnitt 7 recherchiert und
nachgerechnet. Sechs davon entscheiden Quellen und Daten; sie sind oben in die
Empfehlung eingearbeitet. Übrig bleibt **eine** Sache, die wirklich Geschmack ist, und
auch sie hat eine Voreinstellung:

- **Stört dich die Krone bei +1?** Sieben Merkmalsfamilien stehen genau am Rand,
  weil das Urteil jedes typische Gemochte voll zählt (7.6). Die Figur zeigt das
  ehrlich. *Voreinstellung: so lassen.* Sieht sie beim ersten Anschauen lieber
  Unterschiede zwischen diesen sieben, gibt es mit einer weichen Sättigung (tanh)
  einen Weg, der das Urteil kaum ändert, aber über den Prüfstand und ins
  Bewertungsschema muss. Das wäre ein eigenes Ticket, keine Frage der Zeichnung.

Alles andere steht fest, bis ein Blick auf den Entwurf etwas anderes zeigt. Dafür
gehört vor die Umsetzung eine Bildprobe mit ihrem echten Profil.

---

## 7. Die offenen Fragen, recherchiert

Stand 26.09.2026. Die Zahlen sind mit Skripten nachgerechnet, die die Datenbank nur
lesend öffnen (`sqlite:///file:…?mode=ro&uri=true`). Der Pool sind alle Steckbriefe
zum geltenden Vokabular, je Titel der jüngste: 278 Bücher (die Methodennotiz nennt 78,
der Pool ist seitdem gewachsen). `learn` wurde für Frage 6 aus seinem Quelltext mit
austauschbarer Skalierung nachgebaut, ohne den Code im Repo zu ändern.

### 7.1 Alle 44 Plätze oder nur die bekannten?

**Quellen.**

- Song & Szafir (2019, VIS 2018) haben 14 Darstellungen unvollständiger Daten
  verglichen. Wird Fehlendes **weggelassen**, sinken wahrgenommene Datenqualität und
  Vertrauen, und wenn das Weglassen die visuelle Kontinuität bricht, kommt es sogar zu
  **falschen Antworten**. Wird es **hervorgehoben**, gilt die Darstellung als
  verlässlicher. Mit Nullen aufzufüllen schnitt am schlechtesten ab (Abschnitt
  „Conclusion“). Übertragen: „unbekannt“ als „egal“ zu zeichnen ist Auffüllen mit
  Null, und Unbekanntes wegzulassen ist Weglassen. Die Studie untersuchte
  Zeitreihen, nicht Kreise; die Richtung des Befunds passt trotzdem.
- Diehl et al. (2010): Positionen im Kreis werden gelernt; nach der Lernphase holt
  die radiale Form auf (Beobachtung 3). Das setzt voraus, dass die Positionen
  bleiben.
- Misue, Eades, Lai, Sugiyama (1995) haben für Graphen den Begriff der **mentalen
  Karte** geprägt: Eine Änderung der Anordnung soll die Karte der Betrachterin nicht
  zerstören (Abstract; Volltext nicht gelesen).

**Daten.** Wie viele Merkmalsfamilien kennt die Form?

| Stand | bekannt (Merkmale / Muster) | Winkel je Platz, wenn nur Bekanntes |
|---|---|---|
| erste Erstaufnahme (Profil v1), keine Bücher | 13 / 4 | 17,6° |
| jüngstes Profil (v7), keine Bücher | 17 / 5 | 14,7° |
| jüngstes Profil + 3 Bücher | 21 / 6 | 12,6° |
| jüngstes Profil + 10 Bücher | 26 / 11 | 10,7° |
| jüngstes Profil + alle 24 Bücher | 29 / 13 | 9,9° |

Die Bücher in der Reihenfolge, in der sie bewertet wurden. Zum Vergleich tragen 10
zufällige Bücher aus dem Pool zusammen im Median 20 Merkmalsfamilien (10–90 %: 17–24),
20 Bücher 26 (23–29). Zwei Familien (*keusch*, *offenes Ende*) trägt kein einziges
der 278 Bücher; sie blieben lange leer.

**Empfehlung: alle 44, fest.** Eine Figur nur aus dem Bekannten hätte in den ersten
Wochen 13, dann 17, 21, 26, 29 Plätze, und jede neue Familie würde alle anderen
verschieben. Die leeren Plätze sind die ehrliche Auskunft „darüber weiß die Form noch
nichts“, und genau das fehlte der heutigen Spinne. Der Preis: 7° statt bis zu 17,6°
je Platz. Das reicht für die Balken (Abschnitt 5) und die Beschriftung.

### 7.2 Reihenfolge der Sektoren und innerhalb

**Quellen.** Die Arbeiten zur Achsenordnung ordnen **datengetrieben**: Peng, Ward,
Rundensteiner (2004) suchen für Sternglyphen die Reihenfolge, die möglichst
monotone und symmetrische Formen ergibt (Abschnitt 5.1–5.2, die „Tropfenform“),
Miller et al. (2019) vergleichen Ordnung nach Ähnlichkeit mit Ordnung nach
Unähnlichkeit und finden die zweite beim Gruppieren vieler Glyphen besser. Beide
sortieren neu, sobald sich die Werte ändern, und dienen dem Vergleich vieler Glyphen
nebeneinander. Hier gibt es **eine** Form, die sich mit jeder Bewertung ändert. Eine
datengetriebene Ordnung würde die Plätze wandern lassen, was 7.1 gerade vermeiden
will. Passend ist die **inhaltliche** feste Ordnung der Aromaräder: Ähnliches
nebeneinander (Spencer et al. 2016). Albo et al. (2016) äußern sich laut Abstract
nicht zur Ordnung.

**Daten: Sektoren.** Von den 12 Reihenfolgen der fünf Dimensionen im Kreis (Tempo
fest oben, Spiegelungen gleichgesetzt) bringen drei **vier von fünf** Grenzgängern
an die Grenze zu ihrer zweiten Dimension; mehr geht nicht, weil die fünf Paare
(Tempo–Handlung, Tempo–Stimmung, Handlung–Stil, Stil–Stimmung zweimal) einen Kreis
aus vier Dimensionen bilden, in den *Figuren* eingefügt werden muss:

| Reihenfolge | an der Grenze | ohne Nachbarn |
|---|---|---|
| **Tempo · Handlung · Stil · Stimmung · Figuren** | hart, witzig, rasant, anspruchsvoll | nervenaufreibend |
| Tempo · Stimmung · Stil · Handlung · Figuren | hart, witzig, nervenaufreibend, anspruchsvoll | rasant |
| Tempo · Stimmung · Stil · Figuren · Handlung | hart, witzig, nervenaufreibend, rasant | anspruchsvoll |
| Dateireihenfolge Tempo · Handlung · Stimmung · Figuren · Stil | rasant | vier |

Empfohlen ist die erste: Sie beginnt wie die Datei mit Tempo und Handlung, und der
eine Verlierer, *nervenaufreibend*, gehört mit seinem ersten Mitglied ohnehin zu
Tempo.

**Daten: Gegensatzpaare.** Zehn Familien nennen ein `gegenteil`, aber nur **drei
Paare** stehen beide im Vokabular: *rasant ↔ gemächlich* (Tempo), *anspruchsvoll ↔
locker erzählt* (Stil), *düster ↔ warmherzig* (Stimmung). Die übrigen sieben
Gegenteile (*sanft*, *ernst*, *entspannt*, *geborgen*, *geradlinig* …) sind Wörter,
die es als Merkmal nicht gibt. Alle drei Paare liegen **innerhalb einer Dimension**.
Gegenüber (180°) ginge also nur, wenn man die Sektoren aufbricht. Nebeneinander
zeigen sie dagegen, was sie aussagen: ein Balken nach außen, der andere nach innen,
„rasant ja, gemächlich nein“ als ein Bild.

**Empfehlung.** Sektoren Tempo · Handlung · Stil · Stimmung · Figuren. Innerhalb eines
Sektors drei Regeln in dieser Folge: (1) ein Grenzgänger steht am Rand zu seiner
zweiten Dimension, (2) Gegensatzpaare stehen nebeneinander, (3) sonst gilt die
Reihenfolge des ersten Mitglieds in `merkmale.yaml`. Alphabetisch hilft beim Suchen
eines Namens, verstreut aber Verwandtes. Am Schreibtisch stehen die Namen ohnehin
dran, und auf dem Telefon sortiert die Liste nach Wert. Tempo ergibt damit
*nervenaufreibend · gemächlich · rasant*, Stil beginnt mit *anspruchsvoll · locker
erzählt*, Stimmung mit *witzig · hart*.

### 7.3 Umriss ja oder nein?

**Quellen.**

- Fuchs, Isenberg, Bezerianos, Fischer, Bertini (2014) haben in drei Experimenten
  Sternglyphen **nur mit Speichen**, **Speichen mit Umriss** und **nur Umriss**
  verglichen. Ohne Umriss erkannten die Teilnehmenden Ähnlichkeit in den **Daten**
  am besten. Mit Umriss urteilten sie nach der **Form** statt nach den Daten, und
  zwar in allen Experimenten. Ihre erste Gestaltungsregel lautet sinngemäß: Wo
  Datenähnlichkeit beurteilt wird, keine Umrisse (Abschnitt 7). Nur bei etwa vier
  Dimensionen war jede Variante unbedenklich.
- Few (2005): Symmetrische Polygone gefallen, unabhängig davon, was sie bedeuten
  (S. 3).
- Miller et al. (2019) berichten nach Klippel et al.: Auffällige Formen lenken das
  Gruppieren.

**Anwendung.** Die Buchseite stellt genau die Frage nach Datenähnlichkeit: Liegt
das, was dieses Buch trägt, dort, wo meine Form ausschlägt? Ein Umriss je Sektor
mildert den Flächeneffekt über die Sektorgrenzen hinweg, bleibt aber ein Umriss in
Fuchs' Sinn: fünf Teilformen statt einer, mit 3 bis 16 Ecken. Die Balken sind
Fuchs' „Speichen“, die Variante, die am besten abschnitt.

**Empfehlung: kein Umriss, auch nicht je Sektor.** Die „Form“ entsteht aus der
Krone der Balken und dem Ring „egal“; das Wort *Geschmacksform* bleibt richtig.
Hilfslinien als Ringe statt als Striche an den Speichen: Fuchs et al. fanden Gitter
hilfreicher als Teilstriche (Abschnitt 7), und die Ringe bei −1, 0 und +1 sind ein
solches Gitter.

### 7.4 Querstriche für einzelne Merkmale?

**Daten** (echte Form, `TasteForm.term` gegen `TasteForm.family`, nur Familien mit
mehr als einem Mitglied):

| | Merkmale mit eigenem Wert | Abweichung ≥ 0,1 | ≥ 0,2 | ≥ 0,3 | Familien mit ≥ 0,2 |
|---|---|---|---|---|---|
| Merkmale | 24 | 12 | 10 | 6 | 5 |
| Erzählmuster | 23 | 8 | 3 | 1 | 3 |

Die großen Abweichungen sind fast alle **Abstufungen in dieselbe Richtung**:
*witzig* 1,0 mit *heiter*, *Sprachwitz*, *Wortgefechte* je 0,58, *rasant* 0,98 mit
*actionreich* 0,57, *traurig* 0,68 mit *melancholisch* 0,42. Das folgt aus der
Rechnung: Ein Merkmal wird zur Hälfte zur Familie hin geglättet
(`merkmal_zur_familie: 1.0`, also `(e_t + n·F)/2n`). Seine eigenen Belege sind
kleiner als die der Familie, weil sie sich auf mehrere Wörter verteilen. Und die
Familie wird oben bei 1,0 gekappt (7.6), das Merkmal nicht. Eine neue Aussage
enthalten diese Abstufungen nicht: Die Familie zählt, ihre Wörter etwas weniger.

**Widersprüche** (anderes Vorzeichen, beide Beträge mindestens 0,15) gibt es genau
zwei: *große Welt* −0,15 mit *Weltenbau* +0,23 (und *episch angelegt* −0,47, gleiche
Richtung), und *Katz und Maus* +0,21 mit *Ungeheuer* −0,17. Das sind die Fälle, in
denen der Familienbalken etwas Falsches über ein Wort sagt (Z11).

**Quellen.** Fuchs et al. (2014): Zusätzliche Marken (dort Teilstriche) halfen bei
Glyphen ohne Umriss nicht und bringen mehr Tinte ins Bild. Bei Überlagerung
empfehlen sie, darauf zu verzichten (Abschnitt 6–7). Peng et al. (2004) nennen
Unordnung (clutter) alles, was das Verständnis der Daten stört (Abstract). Zehn
Striche, die „etwas weniger als die Familie“ sagen, wären genau das.

**Empfehlung: Querstrich nur bei Widerspruch** (heute 2 Familien), Abstufungen nur
im Tooltip und in der Telefonliste. Das hält die Idee der Nutzerin („Merkmale gehen
in der Familie auf“) sichtbar, wo sie etwas bedeutet.

### 7.5 Welcher Wert auf der Buchseite?

**Daten** (278 Steckbriefe, echte Form; „Urteilswert“ = Wert des stärksten
Buchmerkmals der Familie, wie `book_spiders` und `overlap` ihn nehmen):

| | Anzahl |
|---|---|
| Bücher mit mindestens einer bekannten Familie | 277 |
| getragene bekannte Familien (Buch × Familie) | 1613 |
| \|Urteilswert − Familienwert\| ≥ 0,05 | 426 (26 %) |
| ≥ 0,1 (etwa 5 px am Schreibtisch) | 302 (19 %) |
| ≥ 0,2 | 148 (9 %) |
| ≥ 0,3 | 104 (6 %) |
| Bücher mit mindestens einer Abweichung ≥ 0,1 | 191 von 277 |
| **anderes Vorzeichen** | 62 (47 × *große Welt*, 15 × *Katz und Maus*) |

Mit der heutigen Regel (Balken = Urteilswert) wäre *große Welt* auf der Profilseite
ein Balken nach innen und auf 47 Buchseiten einer nach außen. Dieselbe Familie
wechselte zwischen zwei Ansichten die Richtung.

**Quellen.** Qu & Hullman (2018) zeigen, dass Ansichten, die einzeln gut gestaltet,
aber untereinander inkonsistent sind (ihr Beispiel: dasselbe Feld mit
verschiedenen Achsenbereichen), das Lesen langsam und fehleranfällig machen
(Abstract). Ausnahmen ließen die Teilnehmenden nur mit Begründung zu.

**Empfehlung.** Der Balken zeigt **überall den Familienwert**. Der Urteilswert
erscheint auf der Buchseite als bernsteinfarbener Querstrich, wo er um mindestens 0,1
abweicht (19 % der getragenen Familien). So zeigt das Bild, warum die Begründung
„dagegen“ oder „gemocht“ sagt, ohne dass der Balken seine Bedeutung wechselt. Das
ersetzt die Regel im Docstring von `book_spiders` (Balken = Urteilswert), die aus
der Zeit ohne Querstriche stammt.

### 7.6 Sieben Familien bei +1,0

**Ursache, genau.** `learn` rechnet je Familie einen Rohwert
`(e_f + k·Startwert) / (n + k)` und teilt dann alle Werte durch `top`, den Wert am
Quantil `voll_ab_quantil: 0.75` der **positiven** Familienwerte (Merkmale **und**
Muster zusammen, > 0,02). Am Ende kappt es bei ±1. Bei der Leserin sind es 32
positive Familien. Index `int(32 · 0,75) = 24` ergibt `top = 0,208`. Alles ab 0,208
wird 1,0: 8 Familien, davon 7 Merkmale und 1 Muster. Ihre Rohwerte reichen von 0,208
bis 0,404, unterscheiden sich also um den Faktor 2 und sind danach gleich. Das ist
**Absicht** („ein typisches Gemochtes zählt voll“, Methode 3.2 Punkt 5). Bei jeder
Leserin landet so rund ein Viertel ihrer Vorlieben am Anschlag.

Nebenbefund: `voll_ab_quantil: 1.0` würde nicht „auf das Maximum“ skalieren, sondern
mit einem `IndexError` abbrechen (`positive[len(positive)]`).

**Gemessen: Anzeige.** Familien bei ≥ 0,99 (Merkmale / Muster):

| Skalierung | am Anschlag | verschiedene Werte ≥ 0,9 |
|---|---|---|
| heute: Quantil 0,75, gekappt | 7 / 1 | 3 |
| Quantil 0,9, gekappt | 4 / 0 | 1 |
| durch das Maximum | 1 / 0 | 1 |
| Quantil 0,75, weich: `tanh(atanh(0,9) · x / top)` | 1 / 0 | 5 |

**Gemessen: Urteil, echte Leserin.** Jedes bewertete Buch ohne sich selbst gelernt
(17 der 22 gemochten und 1 der 2 enttäuschenden ließen sich über den Titel einem
Steckbrief im Pool zuordnen), dazu die 5 Gegenproben und die 260 übrigen Bücher als
Stapel:

| Skalierung | gemocht ≥ 3★ | Gegenproben < 3★ | Stapel durchs Tor | Rangkorrelation zu heute | mittlere Änderung |
|---|---|---|---|---|---|
| heute | 14 / 17 | 4 / 5 | 182 | 1,000 | – |
| Quantil 0,9 | 12 / 17 | 5 / 5 | 150 | 0,987 | −4,5 Punkte |
| Maximum | 6 / 17 | 5 / 5 | 95 | 0,970 | −9,8 Punkte |
| tanh weich | 15 / 17 | 4 / 5 | 183 | 0,994 | +0,7 Punkte |

Das eine enttäuschende Buch kommt in allen Varianten durchs Tor.

**Gemessen: Urteil, synthetische Leserinnen** (Regeln aus
`prototyp/synthetische_leser.py`, k = 10, 40 Durchgänge, Pool 278 + 5;
Treffsicherheit / Ausbeute / Ablehnung in %):

| Leserin | heute | Quantil 0,9 | Maximum | tanh weich |
|---|---|---|---|---|
| Krimi | 94 / 93 / 87 | 96 / 85 / 92 | 96 / 77 / 94 | 93 / 94 / 86 |
| Zwei Richtungen | 98 / 86 / 80 | 99 / 74 / 94 | 100 / 54 / 100 | 98 / 87 / 79 |
| Ideen | 99 / 81 / 94 | 100 / 67 / 99 | 100 / 41 / 100 | 99 / 83 / 92 |
| Figuren | 81 / 63 / 76 | 88 / 44 / 88 | 92 / 24 / 94 | 81 / 64 / 75 |
| Erzählmuster | 100 / 86 / 95 | 100 / 70 / 100 | 100 / 51 / 100 | 99 / 87 / 94 |

(Die Spalte „heute“ weicht von der Tabelle in Methode Abschnitt 13 ab, weil der Pool
seitdem von 78 auf 278 Bücher gewachsen ist.)

**Bewertung.**

- **Das Urteil anders skalieren (Quantil 0,9, Maximum)**: Das kostet Ausbeute, bei
  den synthetischen Leserinnen 8 bis 40 Punkte, an der echten bis zu 8 von 17
  gemochten Büchern. Das widerspricht der Eichung. Verworfen.
- **Nur die Anzeige anders skalieren** (etwa durch das Maximum): Dann zeigte der
  Balken nicht mehr, was zählt. Ein typisch Gemochtes stünde bei 0,5, obwohl das
  Urteil es voll rechnet. Das ist der Widerspruch zwischen Ansichten, den 7.5
  vermeidet (Qu & Hullman). Verworfen.
- **Weich sättigen (tanh) im Urteil selbst**: Fast neutral (Rangkorrelation 0,994,
  synthetisch überall innerhalb von ±2 Punkten, an der echten Leserin ein gemochtes
  Buch mehr). Die sieben unterscheiden sich wieder (5 verschiedene Werte ≥ 0,9).
  Möglich, aber eine Änderung am Urteil: Sie gehört mit einem eigenen Schlüssel ins
  Bewertungsschema und über den Prüfstand.

**Empfehlung.** Die Zeichnung zeigt die Werte, mit denen das Urteil rechnet, und
damit die Krone. Die Legende sagt, was der Rand heißt: „zählt voll“. Ob die Krone
aufgelöst werden soll, ist die eine verbleibende Frage an die Leserin (Abschnitt 6);
wenn ja, dann über tanh im Urteil, als eigenes Ticket.

### 7.7 Glossar

`CONTEXT.md` führt Einträge als `### English Name`, darunter `*deutsch: Wort*`, eine
Definition und `**Reader-facing name: …**`. ADR 22 verlangt genau ein deutsches Wort
je englischem Begriff; wer ein Wort einführt, trägt es ein.

**Neu vorgeschlagen:**

- **Dimension** — *deutsch: Dimension*. One of the five appeal factors NoveList
  sorts its terms into (pace, storyline, tone, character, style; German: Tempo,
  Handlung, Stimmung, Figuren, Stil), each with the question the reader knows it by
  („wie es vorangeht“ …). In the code `Term.dimension` and
  `Vocabulary.dimensions`. An Appeal Family belongs to the dimension of its first
  member, though it may span two. **Reader-facing name: the dimension's own name**
  („Tempo“) or its question. Der Eintrag fehlt heute: Das Glossar sagt im Fließtext
  „appeal factors“, der Code `dimension`.
- **Spider** — *deutsch: Spinne*. The drawing of a Taste Form (`web/spider.py`):
  one **sector** (*Sektor*) per Dimension, one fixed place per Appeal Family or
  Master Plot, a bar from the ring *egal* outward (liked) or inward (rejected), an
  empty place where the form knows nothing. On a book page the book is a **track**
  (*Spur*) outside the rim. Two spiders: Appeal Terms and Story Patterns. The words
  *Sektor* und *Spur* bekommen damit keine eigenen Einträge; sie sind Teile dieses
  einen Begriffs und erscheinen in der Oberfläche nicht (die Legende sagt „dieses
  Buch“, „egal“, „noch unbekannt“). **Reader-facing name: none** — die
  Oberfläche nennt die Figur „Geschmacksform“ (Kartentitel auf der Profilseite).

**Nachzuziehen:**

- *Taste Form*: „on a dashed ring where she is indifferent, outward where she likes
  something, inward where she rejects it; a family she has said nothing about gets
  no axis. Drawn on the profile page as two spiders (…, at most twelve axes each)“.
  Neu: Jede Familie hat einen festen Platz, eine unbekannte bleibt leer, gezeichnet
  als Balken statt als Netz, mit Verweis auf *Spider*.
- *Taste Form*: „a book page with the book laid over it on the same scale“. Neu:
  das Buch als Spur außerhalb des Randes, nicht auf derselben Skala.
- *Form Overlap*: „the Story Patterns form a second spider“ bleibt richtig.
- Docstrings in `web/spider.py` und der Kopfkommentar in `_spider.html` („höchstens
  `MOST_AXES` Achsen“, „Das Buch liegt auf derselben Skala“, „Wo das Buch eine
  Familie trägt, zeigt die Achse den Wert, mit dem das Urteil gerechnet hat“) bei
  der Umsetzung.

---

## Quellen

Im Volltext gelesen:

- Stephen Few, *Keep Radar Graphs Below the Radar – Far Below*, DM Review, Mai 2005.
  <https://www.perceptualedge.com/articles/dmreview/radar_graphs.pdf>
- Stephan Diehl, Fabian Beck, Michael Burch, *Uncovering Strengths and Weaknesses of
  Radial Visualizations – an Empirical Approach*, IEEE TVCG 16, 2010, 935–942.
  <https://www.st.uni-trier.de/diehl/pubs/infovis10.pdf>
- William S. Cleveland, Robert McGill, *Graphical Perception: Theory,
  Experimentation, and Application to the Development of Graphical Methods*, JASA
  79(387), 1984, 531–554. <https://doi.org/10.1080/01621459.1984.10478080>
- Jeffrey Heer, Michael Bostock, *Crowdsourcing Graphical Perception*, CHI 2010,
  203–212. <http://idl.cs.washington.edu/files/2010-MTurk-CHI.pdf>
- Matthias Miller, Xuan Zhang, Johannes Fuchs, Michael Blumenschein, *Evaluating
  Ordering Strategies of Star Glyph Axes*, 2019. <https://arxiv.org/abs/1908.00576>
- Manuela Waldner et al., *A Comparison of Radial and Linear Charts for Visualizing
  Daily Patterns*, 2019. <https://arxiv.org/abs/1907.13534>
- Michael Gleicher et al., *Visual Comparison for Information Visualization*,
  Information Visualization 10(4), 2011, 289–309.
  <https://graphics.cs.wisc.edu/Papers/2011/GAWJHR11/>
- Molly Spencer, Emma Sage, Martin Velez, Jean-Xavier Guinard, *Using Single Free
  Sorting and Multivariate Exploratory Methods to Design a New Coffee Taster's Flavor
  Wheel*, J. Food Sci. 81, 2016, S2997–S3005.
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC5215420/>
- d3-shape, *Arcs*: <https://d3js.org/d3-shape/arc> ·
  d3-scale, `scaleRadial`: <https://d3js.org/d3-scale/linear#scaleRadial>
- Vega-Lite, *Arc* und Beispiel *Radial Plot*:
  <https://vega.github.io/vega-lite/docs/arc.html>,
  <https://vega.github.io/vega-lite/examples/arc_radial.html>
- Mike Bostock, *Zoomable sunburst* (Observable, Quelltext über
  <https://api.observablehq.com/@d3/zoomable-sunburst.js?v=3>)
- MDN, SVG `<title>`:
  <https://developer.mozilla.org/en-US/docs/Web/SVG/Reference/Element/title>
- Yan Holtz, data-to-viz, *Circular barplot* (Praxisquelle):
  <https://www.data-to-viz.com/graph/circularbarplot.html>

Für Abschnitt 7 im Volltext gelesen:

- Hayeong Song, Danielle Albers Szafir, *Where's My Data? Evaluating Visualizations
  with Missing Data*, IEEE TVCG 25(1), 2019 (VIS 2018).
  <https://cmci.colorado.edu/visualab/papers/song_VIS_2018.pdf>
- Johannes Fuchs, Petra Isenberg, Anastasia Bezerianos, Fabian Fischer, Enrico
  Bertini, *The Influence of Contour on Similarity Perception of Star Glyphs*, IEEE
  TVCG 20(12), 2014, 2251–2260.
  <https://inria.hal.science/hal-01023867/file/Fuchs_2014_TIO.pdf>
- Wei Peng, Matthew O. Ward, Elke A. Rundensteiner, *Clutter Reduction in
  Multi-Dimensional Data Visualization Using Dimension Reordering*, IEEE InfoVis
  2004, 89–96. <https://davis.wpi.edu/~xmdv/docs/infovis04_clutter.pdf>

Für Abschnitt 7 nur Zusammenfassung:

- Zening Qu, Jessica Hullman, *Keeping Multiple Views Consistent: Constraints,
  Validations, and Exceptions in Visualization Authoring*, IEEE TVCG 24(1), 2018.
  <https://doi.org/10.1109/TVCG.2017.2744198>
- Kazuo Misue, Peter Eades, Wei Lai, Kozo Sugiyama, *Layout Adjustment and the
  Mental Map*, J. Visual Languages and Computing 6(2), 1995, 183–210.
  <https://doi.org/10.1006/jvlc.1995.1010>

Nur Zusammenfassung oder Metadaten zugänglich:

- Yael Albo, Joel Lanir, Peter Bak, Sheizaf Rafaeli, *Off the Radar: Comparative
  Evaluation of Radial Visualization Solutions for Composite Indicators*, IEEE TVCG
  22(1), 2016, 569–578. <https://doi.org/10.1109/TVCG.2015.2467322> (Abstract:
  <https://cris.bgu.ac.il/en/publications/off-the-radar-comparative-evaluation-of-radial-visualization-solu/>)
- Geoffrey M. Draper, Yarden Livnat, Richard F. Riesenfeld, *A Survey of Radial
  Methods for Information Visualization*, IEEE TVCG 15(5), 2009, 759–776.
  <https://doi.org/10.1109/TVCG.2009.23>
- Michael Burch, Daniel Weiskopf, *On the Benefits and Drawbacks of Radial Diagrams*,
  in: Handbook of Human Centric Visualization, Springer 2014, 429–451.
  <https://doi.org/10.1007/978-1-4614-7485-2_17>
- Alexander Klippel, Frank Hardisty, Chris Weaver, *Star Plots: How Shape
  Characteristics Influence Classification Tasks*, CaGIS 36(2), 2009, 149–163
  (hier nur über Miller et al. 2019 zitiert).
- A. C. Noble et al., *Modification of a Standardized System of Wine Aroma
  Terminology*, Am. J. Enol. Vitic. 38(2), 1987.
  <https://www.ajevonline.org/content/38/2/143>
- Reinout Heijungs, *Two arguments against the use of radar plots for constructing
  composite indicators*, Braz. J. Chem. Eng., 2022.
  <https://doi.org/10.1007/s43153-022-00247-1> (nicht gelesen; die Flächenformel in
  2.1 ist hier selbst hergeleitet)
