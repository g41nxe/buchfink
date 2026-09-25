# Die Methode: Formüberdeckung

Stand 25.09.2026, Entwurf. Diese Notiz fasst zusammen, was aus der Szenarienanalyse
([urteil-szenarien.md](urteil-szenarien.md)), der Literatur
([urteil-verfahren.md](urteil-verfahren.md)) und dem Gespräch mit der Leserin folgt,
und beschreibt daraus eine Methode für das Urteil. Sie ist als Prototyp gerechnet und
am Prüfstand gemessen, aber **noch nicht umgesetzt**; die Entscheidung dafür gehört in
einen Nachtrag zu ADR 33.

## 1. Die Idee in einem Bild

Die Leserin und jedes Buch haben eine **Form** über denselben Achsen, den Merkmalen
und Erzählmustern des Vokabulars, wie ein Spinnennetz:

- **Die Form der Leserin** schlägt nach außen aus, wo sie etwas mag, nach innen, wo
  sie etwas ablehnt, und bleibt in der Mitte, wo sie nichts gesagt hat. Wie weit sie
  ausschlägt, lernt die Methode **aus ihren Büchern**; was sie antippt oder verstärkt,
  ist der Startwert.
- **Die Form des Buchs** schlägt so weit aus, wie das Modell ein Merkmal im Buch
  gewichtet: prägend weit, deutlich mittel, am Rand kurz.
- **Das Urteil** fragt: *Wie viel von der Form des Buchs liegt in deiner Form, und wie
  viel in deinem Ablehnungsbereich?* Nicht umgekehrt: eine symmetrische Überdeckung
  würde einen breiten Geschmack bestrafen, weil kein Buch alles tragen kann, was die
  Leserin mag (gemessen: *Leichenblässe* käme auf 27 %).

## 2. Was die Leserin angibt, und was nicht

| Sie gibt an | Sie gibt nie an |
|---|---|
| *Mag ich* oder *Doof* zu einem Buch, gern eigene Sterne | wie stark ein Merkmal in einem Buch ist („Rätsel 50 %") |
| bei einem gelesenen Buch optional **Gründe**, angetippt aus dem Vokabular („gemächlich", „großes Ensemble", „episch angelegt"), auch solche, die der Steckbrief nicht nennt, und was sie **anders erlebt** hat („wenig Spannung") | Zahlen, Gewichte, Schwellen |
| was ihr besonders wichtig ist (verstärken, höchstens drei) | |
| eine Ablehnung, die nur in einem Genre gilt (wie heute) | |

## 3. Die Rechnung

### 3.1 Die Form eines Buchs

Für jedes Merkmal *t* des Steckbriefs das Gewicht im Buch: prägend 1,0, deutlich
0,7, am Rand 0,4 (ohne Angabe 0,7). Erzählmuster zählen je Grundhandlung.

Für ein Buch, das die Leserin gelesen und bewertet hat, gilt **ihre** Fassung: ihre
Gründe kommen mit Gewicht 1,0 dazu, was sie anders erlebt hat, fällt weg (Z10). Der
Steckbrief bleibt dabei unverändert; die Fassung der Leserin gilt nur für ihr Profil.

### 3.2 Die Form der Leserin (gelernt)

Für jede Familie *f* und jedes Merkmal *t*:

1. **Belege aus Büchern**: `e = Σ_(gemocht) Gewicht − λ · Σ_(doof) Gewicht`, λ = 1,5
   (ein enttäuschendes Buch wiegt 1,5-fach). Ein Gegengewicht, das die Leserin an
   einem Buch auf ein Genre beschränkt hat, geht aus diesem Buch nicht als
   allgemeine Ablehnung ein; ihre ausdrücklichen Gründe immer.
2. **Startwert aus dem Getippten**: verstärkt +0,6, getippt +0,4, allgemeines
   Gegengewicht −0,4, sonst 0.
3. **Mischung**: `Familie = (e_f + k · Startwert) / (n + k)`, k = 2, n = Zahl der
   gemochten Bücher. Wenige Bücher: der Startwert trägt; viele: die Bücher.
4. **Einzelnes Merkmal**: `Merkmal = (e_t + n · Familie) / 2n`, also zur Hälfte zur
   Familie hin geglättet. So kann *episch angelegt* abgelehnt sein, während
   *Weltenbau* in derselben Familie neutral bleibt (Z11).
5. **Skala**: geteilt durch das obere Viertel der Vorlieben (Quantil 0,75), auf −1 bis 1
   begrenzt. Ein typisches Gemochtes zählt damit voll, nicht nur das Stärkste.

Bekannt ist eine Familie, zu der es irgendeine Angabe gibt, aus Büchern, Getipptem oder
Gegengewicht. Alles andere ist die Mitte des Netzes.

### 3.3 Das Urteil über ein Buch

1. **Merkmale, Anteil in deiner Form**: über die Merkmale des Buchs aus **bekannten**
   Familien (Z2):
   `A = (Σ Gewicht · Vorliebe⁺ − Σ Gewicht · Ablehnung + α·p₀) / (Σ Gewicht + α)`,
   α = 4, p₀ = 0,2. Die Glättung zieht ein dünn beschriebenes Buch zur Mitte, statt
   es kippen zu lassen (Z6).
2. **Erzählmuster, die zweite Spinne** (siehe 3.4): dieselbe Rechnung wie
   für die Merkmale, über die Erzählmuster des Buchs aus bekannten Grundhandlungen,
   jedes mit Gewicht 1 (ein Muster steht nur da, wenn es die Geschichte trägt), mit
   eigener Glättung α_p = 1. Ein positiver Wert B hebt: `× (1 − 0,35·B)` im Produkt;
   ein negativer zieht ab: `× (1 − 0,5·|B|)`. Weiß das Profil über keines der Muster
   etwas, sagt die zweite Spinne nichts.
3. **Facette**: trägt das Buch eine Kombination ganz, gibt es einen Bonus β = 0,25.
   Ihre Merkmale stecken schon im Anteil, sie zählen nicht doppelt.
4. **Gegengewicht mit Genre** (Regel der Leserin): im Genre `× (1 − 0,5 × Gewicht im
   Buch)`.

`Übereinstimmung = [1 − (1 − A)·(1 − Muster)·(1 − Facette)] × Abzüge`

**Sterne** wie heute: ab 0,2 zwei, ab 0,4 drei, ab 0,55 vier, ab 0,7 fünf; Vergleich mit
Toleranz gegen Rundungsfehler. **Tor** ab drei Sternen. Kein Urteil wie heute, wenn das
Buch unbekannt ist oder das Profil nichts weiß.

### 3.4 Zwei Spinnen: wie es sich liest, was es erzählt

Merkmale und Erzählmuster beantworten verschiedene Fragen und bekommen je ein eigenes
Netz: die **erste Spinne** über die Merkmale (Stimmung, Figuren, Handlung, Tempo,
Stil), die **zweite** über die Erzählmuster, jedes Muster mit seiner Grundhandlung als
Familie. Beide werden gleich gelernt (aus deinen Büchern, das Getippte als
Startwert) und gleich gelesen (Anteil des Buchs in deiner Form). Zwei statt eines
Netzes, weil ein Buch vier bis acht Merkmale, aber nur ein bis drei Muster trägt: in
einem gemeinsamen Netz entschieden die Merkmale fast allein.

Die erste Fassung zählte nur das **beste** gemochte Muster. Die zweite Spinne kann mehr:

- **Ablehnung innerhalb einer Grundhandlung.** Gelernt aus deinen Büchern: *Tiere als
  Bedrohung* (aus *Der Schwarm*) −0,2, während die Grundhandlung *Katz und Maus* gemocht
  bleibt (+0,2); *Erstkontakt* −0,23 und *die verborgene Welt nebenan* (aus
  *Auslöschung*) +0,28, beide in *Erkenntnis*. Das ist Z11 für Muster.
- **Ein Muster allein trägt nicht.** Ein Buch, dessen Merkmale neutral sind und das nur
  ein gemochtes Muster trägt, liegt bei 28 % (vorher 41 %, also durchs Tor).
- **Eins oder drei** bleibt fast gleich: ein gemochtes Muster und drei gemochte
  Merkmale 46 %, drei Muster (davon eines gemocht) und dieselben Merkmale 44 %.

Gemessen gegen die erste Fassung (bestes Muster):

| | bestes Muster | zweite Spinne |
|---|---|---|
| *Der Schwarm* mit deinen Gründen | 2★ 39 % | **2★ 33 %** (mehr Abstand zum Tor) |
| deine 7 gemochten Bücher, ohne sich selbst | 48 bis 77 % | 47 bis 72 %, alle mit mindestens drei Sternen |
| Stapelfunde durchs Tor (von 55) | 38 | 37 |
| schmale Profile (1 / 3 / 5 / 8 / 12 getippte Merkmale) | 1 / 4 / 10 / 17 / 45 | unverändert |
| Stufenwechsel bei 40 % weniger Merkmalen | 39 % | 41 % |
| Korrelation mit der Zahl der Merkmale | 0,19 | 0,23 |

Die zweite Spinne ist im Prototyp die Voreinstellung (`muster_spinne`). Für die Anzeige
heißt das: zwei Netze nebeneinander, *wie es sich liest* und *was es erzählt*.

### 3.5 Die Begründung

Jede Zeile ist ein Teil der Rechnung: „passt zu dir: hart (prägend), gezeichnete Figur",
„spricht dagegen: episch angelegt", „Geschichte: Rätsel", „trägt deine Kombination …".
Das Spinnennetz zeigt dasselbe als Bild, auf der Profilseite deine Form, auf der
Buchseite beide Formen übereinander.

## 4. Gemessen am Prüfstand

Prototyp mit der Einstellung aus 3.2 und 3.3, gegen die heutige Rechnung. Daten: deine
Bücher mit Steckbrief (7 *Mag ich*, 2 *Doof*), 55 Stapelfunde, rund zwanzig synthetische
Fälle. Keine Modellaufrufe.

### 4.1 Deine Bücher

*Ohne sich selbst* heißt: die Form wurde ohne dieses Buch gelernt, das Buch dann
beurteilt, die ehrliche Probe, ob die Methode es erkennt.

| Buch | heute | neu, ohne sich selbst | neu, mit sich selbst |
|---|---|---|---|
| Das Rosie-Projekt | 4★ 61 % | 4★ 61 % | |
| Leopard | 5★ 87 % | 4★ 66 % | |
| The Circle | 5★ 93 % | 3★ 50 % | |
| Der Kruzifix-Killer | 5★ 95 % | 4★ 68 % | |
| Leichenblässe | 5★ 93 % | 4★ 68 % | |
| Sharp Objects | 5★ 93 % | 5★ 77 % | |
| Auslöschung | 5★ 98 % | 3★ 48 % | |
| **Der Schwarm** (Doof) | 5★ 92 % | 4★ 70 % | **2★ 39 %** |
| Herr der Ringe (Doof) | 1★ 0 % | 1★ 2 % | 1★ 0 % |

Alle sieben gemochten Bücher erreichen ohne sich selbst mindestens drei Sterne. Ein
enttäuschendes Buch kann ohne sich selbst nicht abgelehnt werden (seine Ablehnung stammt
nur aus ihm); die richtige Probe ist mit sich selbst (Z12): *Der Schwarm* fällt mit
deinen Gründen unter das Tor, **knapp** (39 %).

### 4.2 Szenarien (Auswahl)

| Fall | heute | neu | Ziel |
|---|---|---|---|
| vier Merkmale, alle gemocht | 2★ 34 % | 3★ 47 % | Z1 ✓ |
| acht Merkmale, vier gemocht | 2★ 34 % | 2★ 39 % | Z1 ✓ (die Hälfte ist die Hälfte) |
| ein gemochtes Merkmal, vier andere | 1★ 10 % | 1★ 9 % | ✓ |
| ein Muster + drei gemochte / drei Muster + dieselben | 56 % / 79 % | 55 % / 55 % | Z5 ✓ |
| nur das Muster Rätsel, Merkmale neutral | 3★ 40 % | 3★ 41 % | ⚠ |
| hart prägend / am Rand, sonst gleich | 27 % / 27 % | 35 % / 29 % | Z3 ✓ |
| Facette + gemächlich prägend / am Rand | 56 % / 56 % | 34 % / 41 % | Z4 ✓ |
| episch angelegt / Weltenbau (Science-Fiction) / Weltenbau (Fantasy), je + drei gemochte | 27 / 27 / 18 % | 31 / 37 / 24 % | Z11 ✓ |
| eine Facette, sonst neutral | 5★ 86 % | 3★ 47 % | Doppelzählung weg ✓ |
| dünn: zwei gemochte Merkmale und ein Muster | 5★ 91 % | 5★ 71 % | Z6 ✓ |

### 4.3 Stichprobe und schmale Profile

| | heute | neu |
|---|---|---|
| Stapelfunde durchs Tor (von 55) | 32 | 38 |
| Korrelation mit der Zahl der Merkmale | 0,34 | 0,19 |
| durchs Tor bei einem Profil aus 1 / 3 / 5 / 8 / 12 getippten Merkmalen, ohne Bücher | 0 / 0 / 5 / 6 / 8 | 1 / 4 / 10 / 17 / 45 |
| Stufenwechsel, wenn 40 % der Merkmale fehlen | 27 % | **39 %** |

## 5. Die Ziele, geprüft

| Ziel | Stand |
|---|---|
| Z1 Passung statt Menge | ✓ Anteil in deiner Form; Länge kaum noch im Wert (0,19) |
| Z2 unabhängig von der Profilgröße | ✓ schmale Profile finden Passendes; Unbekanntes zählt nicht |
| Z3 Ausprägung zählt | ✓ Gewicht im Buch in jedem Beitrag |
| Z4 Ablehnung nach Stärke | ✓ gelernt und nach Gewicht im Buch |
| Z5 Muster als eigene Frage | ✓ eigene Spinne; ein gemochtes Muster ist so gut wie drei, ein Muster allein trägt nicht |
| Z6 ehrlich bei dünner Beschreibung | ✓ Glättung zur Mitte |
| **Z7 ruhig gegen Rauschen** | **✗ schlechter als heute** (39 % gegen 27 %): ein Anteil reagiert auf jedes Merkmal einer kurzen Beschreibung |
| Z8 erklärbar, ohne Modell | ✓ jede Zeile ein Teil; Neuberechnung ohne Aufruf |
| Z9 an deinen Büchern geprüft | ✓ 7 von 7 gemocht, 2 von 2 abgelehnt; ⚠ 38 statt 32 Funde durchs Tor |
| Z10 deine Erfahrung geht vor | ✓ Gründe und Abweichungen gelten für dein Profil |
| Z11 Ablehnung so fein wie nötig | ✓ Merkmal statt Familie, ebenso Muster statt Grundhandlung |
| Z12 Enttäuschendes prüft das Profil | ✓ als Probe rechenbar, knapp |

## 6. Was offen ist

1. **Z7, Rauschen.** Die Formel macht es schlimmer, nicht besser; lösen lässt es sich
   nur an der Beschreibung. Erst messen (höchstens zehn Bücher, zwei- bis dreimal mit
   derselben Anweisung, ein bis zwei Bündel), dann entscheiden: nur *prägende* und
   *deutliche* Merkmale zählen, oder zweimal beschreiben und mitteln.
2. **Wenige Bücher zum Lernen.** Nur 7 der 15 gemochten Bücher haben einen Steckbrief;
   die übrigen acht (darunter Reihen) sollten zuerst beschrieben werden (ein Bündel).
   Deine eigenen Bücher tragen das ganze Lernen, ihre Steckbriefe zählen deshalb
   doppelt.
3. **Eichung.** α, p₀, λ, μ, β und die Sternstufen sind an 9 Büchern und 55 Funden
   eingestellt; *Der Schwarm* liegt einen Punkt unter dem Tor. Nachstellen, sobald mehr
   eigene Urteile da sind; der Prüfstand bleibt als Test im Repo.
4. **Mehr Funde durchs Tor** (38 statt 32): entweder so gewollt (die Funde sind schon
   vorgefiltert und passen öfter), oder die Schwelle für drei Sterne leicht anheben
   (bei 0,43 sind es 33).

## 7. Was die Umsetzung braucht

1. **Prüfstand** (vor allem anderen): die Szenarien und die Proben aus Abschnitt 4 als
   Tests, dazu das Messskript; die heutige Rechnung bleibt darin als Vergleich.
2. **Datenmodell**: Gründe und Abweichungen der Leserin je gelesenem Buch
   (`book_relation.details`, keine neue Tabelle); Gegengewichte auch je Merkmal statt
   nur je Familie.
3. **Code**: eine Funktion, die die Form lernt (aus Profil, Relationen, Steckbriefen der
   eigenen Bücher; bei jeder Profiländerung neu, zwischengespeichert), und eine, die
   urteilt; `fit()` wird durch sie ersetzt, die Begründung aus ihren Teilen gebaut.
   Neue Zahlen in `bewertungsschema.yaml`, ADR-33-Nachtrag.
4. **Oberfläche**: beim *Doof* und *Mag ich* die Gründe aus dem ganzen Vokabular antippen
   können (heute nur, was der Steckbrief nennt); das Spinnennetz auf Profil- und
   Buchseite; beim Nachschärfen der Hinweis aus Z12.
5. **Messung Z7** mit dem Modell, klein.

## 8. Review gegen die Recherche (25.09.2026)

Die Methode gegen [urteil-verfahren.md](urteil-verfahren.md), Abschnitt für Abschnitt.

**Wo sie der Literatur folgt**

| Teil der Methode | Entspricht | Befund |
|---|---|---|
| Form aus Büchern, Getipptes als Startwert | Rocchio mit dem Profil als Ausgangsanfrage (3.1); Prior aus Nutzerangaben bei kleinen Mengen (Pazzani/Billsus 1997, 3.3) | ✓ der am besten belegte Teil |
| Vorliebe × Gewicht im Buch, geteilt durch das Gewicht des Buchs | `cosine-tag` der Tagommenders, das gewichtete Mittel statt der Summe (Sen/Vig/Riedl 2009, 3.2) | ✓ die Mittel-Variante, die die Autoren selbst gegen die Längenschwäche anbieten |
| Merkmal zur Familie hin geglättet, Muster zur Grundhandlung | hierarchischer Prior über Tags (Tag Genome, 3.2 und 3.7) | ✓ dort besser gemessen als ein gemeinsames oder getrennte Modelle |
| Glättung zur Mitte bei dünner Beschreibung | Beta-/Bayes-Mittel (3.3/C3, 3.6/F2) | ✓ |
| Facette als Bonus statt eigener Stufe | Noisy-OR verlangt keine Synergie; eine Facette ist eine (3.3/C2) | ✓ die Synergie steht jetzt als eigener Teil da |
| Prüfung: jedes Buch ohne sich selbst | Stufe 0.2 der Recherche | ✓, bei 9 Büchern ohne statistische Aussage |

**Wo sie abweicht, ohne Beleg**

1. **Ablehnung, richtig verglichen.** Die Literatur mittelt Zustimmung und Ablehnung
   je über ihre Bücher (Rocchio: γ/β, Lehrbuch 0,2, Salton/Buckley 0,33 als besser
   gemessen). Unser λ = 1,5 summiert statt zu mitteln; bei 7 gemochten und 2
   enttäuschenden Büchern entspricht es γ/β = 1,5 · 2/7 ≈ 0,43, also knapp über der
   Literatur, nicht weit darüber (Korrektur vom selben Abend). Der Prototyp nimmt die
   Ablehnung jetzt wahlweise als Verhältnis (`rocchio`), damit sie mit der Zahl der
   Bücher mitwandert. Gemessen: 0,43 hält *Der Schwarm* bei 33 %, 0,33 genau an der
   Schwelle (40 %, 2 Sterne), 0,2 lässt ihn durch (49 %). Die gemochten Bücher bleiben
   in allen drei Fällen über dem Tor.
2. **Mehrere Ablehnungen werden verschmolzen.** Die Form summiert die Belege aller
   enttäuschenden Bücher. Die Literatur fand es besser, jedes negative Beispiel für
   sich zu nehmen und das Maximum zu zählen (MultiNeg, Wang/Fang/Zhai 2008, 3.5).
   Gemessen (`neg_max`): bei zwei Büchern ohne Wirkung, ab mehreren wichtig; kostet
   nichts, also übernehmen.
3. **Seltenheit (IDF) fehlt.** Die Recherche empfahl sie als kleinen ersten Schritt
   (3.1). Die gelernte Form ersetzt sie nicht: *nervenaufreibend* steckt in 48 % der
   Funde und zählt voll. Der Prototyp V2 zeigte kaum Wirkung, die Stichprobe ist
   klein; nachholen, wenn der Bestand wächst.
4. **Dünne Beschreibung wird geglättet, nicht gekennzeichnet.** Die Recherche schlug
   beides vor (Chow, 3.6/F1). Die Glättung verhindert das Kippen nach unten, sagt aber
   nicht, dass das Urteil auf wenig ruht; ein Hinweis in der Begründung fehlt noch.

**Was die Recherche empfahl und noch fehlt**

- **Rauschen der Beschreibung messen** (3.8): ungelöst, und die Methode ist hier
  empfindlicher als heute. Die einzige Stelle, an der ein Modell gefragt werden muss.
- **Zufallsauswahl knapp unter dem Tor** (3.6/F3): ohne sie lernt die Form nie aus
  Büchern, die das Tor zurückhält; sie sieht nur, was schon passiert ist.
- **Nachbarbuch als Beleg** (3.5): „trägt, wie *Leichenblässe*", aus derselben Form
  billig zu haben, als Erklärung, nicht als Urteil.

**Weitere Wege?** Kein neues Verfahren: die Recherche schließt Kalibrierung, Bandits,
Matrixfaktorisierung und Nachbarn als Urteil für eine Leserin aus, und die Methode
deckt die belegten Bausteine schon ab. Lohnend sind vier kleine Proben am Prüfstand,
jede ohne Modellaufruf außer der ersten:

1. Rauschen messen (höchstens zehn Bücher, ein bis zwei Bündel) und danach *nur prägend
   und deutlich* zählen als Gegenmittel prüfen.
2. λ = 1 statt 1,5, und das Maximum je enttäuschendem Buch statt der Summe.
3. IDF auf der Seite des Buchs (seltene Merkmale im Anteil stärker).
4. Hinweis „dünn beschrieben" in der Begründung.

Der größte Hebel ist aber kein Verfahren, sondern Daten: die acht gemochten Bücher ohne
Steckbrief beschreiben lassen (ein Bündel), denn die Form lernt heute aus sieben.

## 9. Mit frischen Steckbriefen: der Geschmack hat mehrere Richtungen (25.09.2026, spät)

Die 17 Bücher der Leserin sind mit der aktuellen Anweisung neu beschrieben (drei
Bündel; die Reihen durch ihren ersten Band). Vier kamen als *unbekannt* zurück, ohne
Klappentext: *Cry Baby*, *Cupido*, *Leopard* (im Bündel, früher bekannt), *OFFF*.
*Cry Baby* und *Sharp Objects* sind dasselbe Buch und zählen beim Lernen doppelt.

**Befund.** Mit den frischen Steckbriefen erkennen weder die heutige Rechnung noch die
Methode vier gemochte Bücher ohne sich selbst: *Yendi* 19 %, *Otherland* 13 %,
*Achtsam morden* 31 %, *Auslöschung* 32 % (Methode mit γ/β = 0,33 und Maximum je Buch).
Der Grund liegt nicht in der Rechnung, sondern im Geschmack: er hat **mehrere
Richtungen**, und eine einzige gemittelte Form (Rocchio) liegt zwischen ihnen.

Welches andere gemochte Buch einem Buch am ähnlichsten ist (Anteil geteilter Merkmale):

| Richtung | Bücher | ähnlich untereinander |
|---|---|---|
| düster, hart, spannend | Leichenblässe, Die Verlorenen, Der Kruzifix-Killer, Sharp Objects, David Hunter, The Circle | 34 bis 100 % |
| große Welten, große Ideen | Otherland, Auslöschung, Yendi | 29 bis 45 % |
| warmherzig, schräg, witzig | Das Rosie-Projekt, Achtsam morden | 38 bis 41 % |

Dazu ein Widerspruch, den eine Form nicht auflöst: *große Welt* und *großes Ensemble*
tragen **Otherland** und **Auslöschung** (gemocht) ebenso wie **Der Schwarm**
(enttäuschend). Abgelehnt ist nicht das Merkmal, sondern die Kombination beim Schwarm:
große Welt, Ensemble, gemächlich, ohne Spannung.

**Was daraus folgt.** Die Form muss mehrere Richtungen kennen. Ein Buch wird gegen die
Richtung gemessen, die am besten zu ihm passt (das Maximum, wie MultiNeg auf der
Seite der Ablehnung), und eine Ablehnung kann eine Kombination sein. Das ist der
Gedanke der Facetten, von der anderen Seite: Facetten sind Kombinationen, die mehrere
geliebte Bücher teilen; Richtungen sind Gruppen von Büchern, die einander ähneln.
Die Literatur stützt das nur mittelbar (MultiNeg für Ablehnung, Nachbarverfahren; 3.5
der Recherche, wo Nachbarn als alleiniges Urteil schwach abschnitten, bei vielen
Textmerkmalen). Nächster Schritt: Richtungen als Prototyp (Gruppen aus den Büchern
bilden, je Gruppe eine Form, das Maximum zählt), am selben Prüfstand, ohne
Modellaufruf.
