# Das Urteil: Szenarien, Befunde, Optionen

Stand 25.09.2026. Diese Notiz prüft, wie der Algorithmus, der aus Steckbrief und
Leseprofil Prozent, Sterne und den Durchlass am Tor rechnet (ADR 33), auf
reguläre Fälle und auf Randfälle reagiert, bewertet jede Reaktion und
sammelt Wege, ihn anzupassen. Die Verfahren aus der Literatur stehen in
[urteil-verfahren.md](urteil-verfahren.md); hier steht, was davon zu welchem
Befund passt.

## 1. Vorgehen und Grenzen

**Gemessen** wurde mit derselben Funktion, die auch das Tor benutzt (`facets.fit`),
in drei Arten:

- **Synthetische Bücher und Profile** für gezielte Fälle: rund vierzig Szenarien, jedes ein
  Buch aus echten Familien des Vokabulars gegen das Profil der Leserin (Fassung 6)
  oder gegen ein absichtlich schmales oder breites Profil.
- **Die 86 bekannten Steckbriefe** der Datenbank gegen Fassung 6, für
  Verteilungen, Längenverzerrung und Durchlass.
- **Vier Rechenvarianten als Prototyp** (Abschnitt 5) auf denselben 86, ohne etwas
  zu speichern und ohne Modellaufruf.

**Was diese Notiz nicht kann.** Es gibt keine Wahrheit, gegen die sich „sinnvoll" messen
ließe: die Leserin hat wenige eigene Sterne vergeben, und die 86 Steckbriefe sind
keine neutrale Stichprobe (Funde aus dem Stapel, die schon durch Shop und
Autorenlisten gefiltert wurden, dazu ihre eigenen Bücher). Ob ein Ergebnis
„sinnvoll" ist, ist deshalb ein Urteil nach Lesart des Zwecks: **das Tor soll
Funde aussortieren, die unwahrscheinlich gefallen, ohne Gutes zu verlieren
(ADR 19, Qualität vor Masse), und die Prozentzahl soll ordnen.** Zahlen aus den
Prototypen zeigen Richtung und Größenordnung, keine Kalibrierung.

## 2. Der Algorithmus, wie er heute im Code steht

Was `fit` tut, in der Reihenfolge, in der es rechnet:

1. **Kein Urteil**, wenn das Buch dem Modell unbekannt ist oder das Profil weder
   Facetten noch gemochte Merkmale hat. Ein Fund ohne Urteil wird gezeigt, nie
   zurückgehalten (ADR 7). Ein Profil nur aus Gegengewichten liefert deshalb
   ebenfalls kein Urteil.
2. Der Steckbrief wird auf die **Menge seiner Familien** abgebildet. Zwei Merkmale
   derselben Familie zählen einmal; das Gewicht des Merkmals im Buch (prägend,
   deutlich, am Rand) geht **nicht** ein (#75).
3. **Beiträge**: 0,8 je Facette, deren Familien alle im Buch stehen; 0,1 je
   gemochtem Merkmal im Buch (verstärkt 0,2); 0,3 je gemochtem Erzählmuster
   (verstärkt 0,4). Die Mitglieder einer getroffenen Facette zählen **zusätzlich**
   einzeln, denn sie stehen auch in der Liste der gemochten Merkmale.
4. **Noisy-OR**: `share = 1 − Π(1 − f)`. Kein Beitrag zieht den Wert je über 1.
5. **Gegengewicht**: trifft mindestens eines zu (alle Familien im Buch, Genre als
   ganzes Wort im Genre oder Untergenre des Steckbriefs), gilt
   `share × 0,65`. Das **erste** Treffer-Gegengewicht zählt, die übrigen nicht; die
   Stärke (0,35) ist für jedes gleich.
6. **Sterne** aus festen Schwellen: 0,8 → 5, 0,6 → 4, 0,4 → 3, 0,2 → 2, sonst 1
   (0 nur bei Nullwert mit Gegengewicht).
7. **Tor**: unter drei Sternen wird ein Fund nicht gezeigt. Ausgenommen sind
   Watchlist-Titel und Bücher, die die Leserin selbst mit Sternen bewertet hat.
   **Nicht ausgenommen** sind neue Titel von Referenzautor:innen.

## 3. Szenarien und Bewertung

Zeichen: **✓** sinnvoll, **⚠** vertretbar, aber mit Preis, **✗** Lücke.
„Zurückgehalten" heißt: unter drei Sternen, der Fund erreicht den Stapel nicht.

### 3.1 Reguläre Fälle (Profil: Fassung 6)

| Nr | Szenario | Ergebnis | | Begründung |
|---|---|---|---|---|
| R1 | trägt beide Facetten, dazu nervenaufreibend und Rätsel | 5★, 99 % | ✓ | die beste Übereinstimmung, die möglich ist |
| R2 | trägt **eine** Facette ganz (gezeichnete Figur + hart), sonst nichts Gemochtes | 5★, 86 % | ⚠ | zwei getroffene Merkmale ergeben fünf Sterne, drei weitere Merkmale des Buchs zählen nicht; die Mitglieder werden zusätzlich einzeln gezählt (Abschnitt 2, Punkt 3) |
| R3 | trägt von **jeder** Facette eine Hälfte | 2★, 28 % | ⚠ | zwei ihrer wichtigsten Merkmale, aber aus verschiedenen Facetten: zurückgehalten; der Sprung gegenüber R2 beträgt 58 Punkte |
| R4 | drei gemochte Merkmale einzeln, keine Facette | 2★, 27 % | ⚠ | für drei Sterne braucht es fünf Einzeltreffer; bei Büchern mit vier bis acht Merkmalen belohnt das lange Beschreibungen (5.2) |
| R5 | ein gemochtes Merkmal | 1★, 10 % | ✓ | ein Treffer von sechzehn ist kein Grund |
| R6 | nichts Gemochtes | 1★, 0 % | ✓ | |
| R7 | nur das **verstärkte** Muster Rätsel, sonst neutral | 3★, 40 % | ⚠ | ein einziges Muster, das dreißig von hundert Büchern tragen, lässt ein Buch durchs Tor, ohne dass Stimmung oder Figur passt |
| R8 | nur das nicht verstärkte Muster Flucht | 2★, 30 % | ✓ | |
| R9 | drei gemochte Merkmale + Gegengewicht gemächlich | 1★, 18 % | ✓ | Ablehnung wirkt |
| R10 | eine Facette ganz + Gegengewicht gemächlich | 3★, 56 % | ⚠ | passiert das Tor trotz der stärksten Ablehnung; jedes Gegengewicht wiegt gleich viel, gleich wie stark die Leserin es ablehnt |
| R11 | drei Gegengewichte zugleich | 1★, 18 % | ⚠ | gleich wie eines (bewusst nicht summiert, ADR 33); bei einem Buch mit Facette bleibt es bei 56 % |
| R12 | große Welt in Science-Fiction (Gegengewicht nur bei Fantasy) | 1★, 19 % | ✓ | die Einschränkung auf das Genre wirkt, kein Abzug |
| R13 | große Welt in Fantasy, sonst gleich | 1★, 12 % | ✓ | Abzug greift; hängt daran, dass das Modell das Genre so nennt |

### 3.2 Ränder beim Profil

| Nr | Szenario | Ergebnis | | Begründung |
|---|---|---|---|---|
| E1 | Profil aus **einem** Merkmal, Buch trägt es | 1★, 10 % | ✗ | kein Buch kann drei Sterne erreichen: das Tor hält jeden beschriebenen Fund zurück (#78) |
| E2 | dasselbe, verstärkt | 1★, **20 %** | ✗ | wie E1; dazu ein Rundungsfehler: 0,1 + 0,1 rechnet sich in Gleitkomma zu 0,19999999999999996, liegt damit unter der Schwelle 0,2 und gibt einen Stern statt zwei, obwohl die Seite „20 %" zeigt (Befund der Recherche, hier bestätigt) |
| E3 | drei Merkmale, Buch trägt alle drei | 2★, 27 % | ✗ | wie E1: die Skala ist absolut, nicht relativ zur Größe des Profils |
| E4 | Profil aus einem **Muster**, verstärkt | 3★, 40 % | ⚠ | passiert; Muster wiegen das Dreifache eines Merkmals |
| E5 | dasselbe, nicht verstärkt | 2★, 30 % | ✗ | wie E1 |
| E6 | Profil nur aus **Gegengewichten** | kein Urteil | ⚠ | zeigt alles; die Ablehnungen, die die Leserin angegeben hat, gehen still verloren. Die Erstaufnahme nimmt so ein Profil an |
| E7 | **kein Profil** | kein Urteil | ✓ | gezeigt, nichts geraten (ADR 33, Punkt 8) |
| E8 | sehr breites Profil (59 Familien), Buch trägt vier | 2★, 34 % | ✓ | keine Sättigung: ein Buch trägt höchstens elf Familien |
| E9 | sehr breites Profil, Buch trägt alle acht | 4★, 74 % | ✓ | 5★ ist ohne Facette unerreichbar, und das ist gut so |
| E10 | große Welt zugleich gemocht **und** Gegengewicht | 1★, 6 % | ⚠ | der Widerspruch wird nicht erkannt; die Erstaufnahme warnt, die Rechnung nicht |
| E11 | Facette aus **drei** Familien, Buch trägt alle | 5★, 85 % | ✓ | |
| E12 | dieselbe Facette, Buch trägt **zwei** von drei | 1★, 19 % | ✗ | Alles-oder-nichts: 66 Punkte Abstand zwischen zwei von drei und drei von drei |

### 3.3 Ränder beim Buch

| Nr | Szenario | Ergebnis | | Begründung |
|---|---|---|---|---|
| B1 | dasselbe Buch, vier Merkmale (drei gemochte) | 2★, 27 % | | |
| B2 | dasselbe Buch, acht Merkmale (vierter Treffer dabei) | 2★, 34 % | ⚠ | längere Beschreibungen treffen öfter; an den echten Steckbriefen 5.2 |
| B3 | gemochtes Merkmal **prägend** | 2★, 27 % | ✗ | gleich wie B4: das Gewicht im Buch zählt nicht (#75) |
| B4 | dasselbe Merkmal nur **am Rand** | 2★, 27 % | ✗ | |
| B5 | Gegengewicht **prägend** im Buch | 1★, 18 % | ✗ | gleich wie B6 |
| B6 | Gegengewicht nur am Rand | 1★, 18 % | ✗ | ein Randmerkmal straft so stark wie ein prägendes; der Fall *Neongrau* (große Welt prägt dort, und das Urteil war trotzdem knapp) und *Der Schwarm* liegen hier |
| B7 | Buch, das das Modell nicht kennt | kein Urteil | ✓ | gezeigt; bleibt dauerhaft unsortiert und ist Gegenstand von #76 |
| B8 | Steckbrief nur aus drei gemochten **Mustern**, ohne Merkmale | 4★, 71 % | ⚠ | dieselbe Zahl gemochter Merkmale ergäbe 27 % (R4): Muster wiegen das Dreifache |
| B9 | zwei Merkmale **einer Familie** | 1★, 20 % | ✓ | zählen einmal |

### 3.4 Ränder in der Rechnung

| Nr | Szenario | Ergebnis | | Begründung |
|---|---|---|---|---|
| C1 | Muster (0,3) + ein Merkmal (0,1) | 2★, 37 % | ⚠ | knapp unter der Schwelle |
| C2 | verstärktes Muster allein | 3★, 40 % | ⚠ | knapp darüber; 3 Punkte trennen „durch" und „zurückgehalten", ohne Unsicherheitsband |
| C3 | acht Treffer, keine Facette | 4★, 66 % | ✓ | |
| C4 | dieselben acht mit Facetten | 5★, 99 % | ⚠ | Facetten heben um 33 Punkte; ihre Mitglieder zählen doppelt |

### 3.5 Aus dem Code, nicht gerechnet

| Nr | Szenario | Verhalten | | Begründung |
|---|---|---|---|---|
| G1 | **Neuer Titel einer Referenzautorin** mit niedrigem Wert | wird zurückgehalten | ⚠ | eine Autorin, die die Leserin liebt, ist an sich eine Nachricht; das Tor kennt keine Ausnahme, nur für Watchlist und eigene Sterne |
| G2 | Steckbrief mit falschem oder fehlendem Genre | Gegengewicht mit Genre greift nicht | ⚠ | still: das Modell nennt das Genre frei; „Roman" für einen Fantasyband hebt den Abzug auf |
| G3 | **Anweisung ändert sich**, Fingerabdruck wechselt | alle Steckbriefe veraltet, bis neu beschrieben | ⚠ | 48 von 48 am 25.09.; bis dahin gibt es keine Urteile, ohne dass etwas zurückgehalten wird (richtig), aber auch ohne Ordnung im Stapel |
| G4 | Profil ändert sich | alle Urteile sofort neu, ohne Modell | ✓ | das ist der Kern von ADR 33 |
| G5 | Watchlist-Titel | nie zurückgehalten | ✓ | die Leserin hat ihn selbst benannt |

## 4. Befunde

In der Reihenfolge, in der sie wehtun. Jeder trägt sein Szenario.

**B-1: Die Skala ist absolut, nicht relativ zum Profil (E1–E5).** Ein Profil aus einem
bis drei Merkmalen kann das Tor nicht erreichen und hält jeden beschriebenen Fund
zurück. #78 hält das fest, mit den Zahlen. Hinzu kommt der
umgekehrte Fall, dass ein wachsendes Profil den Durchlass mit wachsen lässt:
an den echten Steckbriefen passieren bei einem Profil aus **einem** Muster
26, bei sechzehn gemochten Familien 54 von 86 (Tabelle 5.1). Das Tor ist damit an einem
Profil geeicht, das es nicht mehr gibt: bei der Eichung passierten rund ein
Fünftel der Bücher einer Stichprobe, heute (verzerrt) 65 %.

**B-2: Das Gewicht im Buch zählt nicht (B3–B6, #75).** Ob ein Merkmal das Buch prägt oder
nur vorkommt, ändert nichts, weder bei Vorlieben noch bei Gegengewichten. Ein
Randmerkmal kann ein Buch genauso stark abstrafen wie ein prägendes.

**B-3: Die Stufe eines Buchs ist gegen die Beschreibung empfindlich.** Lässt man an den
echten Steckbriefen 40 % der Merkmale weg (zufällig, 20 Wiederholungen), ändert
sich bei 39 % der Bücher die Sternstufe. Von zehn Büchern mit zwei
Beschreibungen (verschiedene Fassungen der Anweisung oder Wiederholung) haben
vier ihre Stufe gewechselt, eines von 1 auf 5 Sterne (6 % gegen 90 %). Das
Modell beschreibt stochastisch; das Urteil schwächt das nicht ab.

**B-4: Längenverzerrung.** Der Wert steigt mit der Zahl der Merkmale im Steckbrief
(Korrelation 0,27 bis 0,38): im Mittel 40 % bei vier, 58 % bei sechs, 69 % bei sieben
Merkmalen. Ein Teil davon ist echt (Bücher, die vieles tragen), ein Teil ist der
Stil des Modells; die Rechnung trennt beides nicht.

**B-5: Facetten sind eine Klippe (R2, R3, E12, C4).** Alles-oder-nichts und
Doppelzählung der Mitglieder: ein Buch mit beiden Hälften einer Facette liegt bei
86 %, eines mit einer Hälfte je Facette bei 28 %. Das Profil der Leserin hat zwei
Facetten und sechzehn gemochte Familien; die Facetten entscheiden über mehr als
jeder andere Beitrag.

**B-6: Muster wiegen zu viel im Verhältnis zu Merkmalen (R7, B8, E4).** Ein Muster zählt
das Dreifache eines Merkmals, und ein einzelnes verstärktes Muster genügt für das
Tor; in der Stichprobe erreichen 26 Bücher drei Sterne allein über *Rätsel*.

**B-7: Ablehnungen sind grob (R10, R11).** Jedes Gegengewicht zieht 35 %, gleich wie stark
es die Leserin ablehnt; mehrere wirken wie eines. Ein Buch mit einer Facette
passiert das Tor auch mit ihrer stärksten Ablehnung.

**B-8: Häufige Merkmale zählen so viel wie seltene (5.3).** *nervenaufreibend* steckt in 48 %
der Steckbriefe, *schräge Figur* in 5 %; beide zählen gleich (verstärkt ist
*nervenaufreibend* sogar das doppelte). Ein Merkmal, das fast jedes Buch trägt,
sagt wenig.

**B-9: Sonderfälle mit Auswirkung im Betrieb.** Neue Titel von Referenzautor:innen unterliegen dem Tor (G1);
ein Profil nur aus Gegengewichten wird angenommen, urteilt aber nichts (E6);
ein widersprüchliches Profil wird nicht erkannt (E10); ein Genre, das das
Modell anders nennt, hebt einen Abzug still auf (G2).

**Was gut ist.** Die Rechnung ist erklärbar (jede Zeile der Begründung ist ein Beitrag), erzeugt
keinen Wert über 1, verarbeitet unbekannte Bücher und fehlende Profile ohne zu raten
(ADR 7) und ist ohne Modellaufruf neu zu rechnen (G4). Mehrfache Merkmale einer
Familie zählen einmal (B9). Die Wirkung des Genres bei Gegengewichten (R12,
R13) funktioniert.

## 5. Messungen an den echten Steckbriefen und Prototypen

86 bekannte Steckbriefe, Fassung 6. Vier Rechnungen gegeneinander; V0 ist die
heutige. Bei V1 bis V3 sind die Schwellen nicht neu geeicht: sie zeigen das
Verhalten, nicht die richtigen Zahlen.

- **V0 heute:** Noisy-OR, absolut.
- **V1 relativ zum Profil:** der Wert geteilt durch das, was das Profil überhaupt
  erreichen kann.
- **V2 mit IDF:** jeder Beitrag mal (seltenes Merkmal hoch, häufiges niedrig),
  Mittel bleibt 1.
- **V3 Kosinus:** Ähnlichkeit zwischen Profilvektor und Buchvektor, das Gewicht im
  Buch geht ein (prägend 1,0, deutlich 0,7, am Rand 0,4).

### 5.1 Durchlass nach Größe des Profils (Bücher mit Wert ≥ 0,4)

Profil aus den ersten *k* gemochten Familien, ohne Facetten und Gegengewichte.
*Nur Merkmale*: ohne Muster, damit das verstärkte Muster *Rätsel* nicht alles
überlagert.

| k gemochte Merkmale | V0 heute | V1 relativ | V2 IDF | V3 Kosinus |
|---|---|---|---|---|
| 1 | 0 | 19 | 0 | 8 |
| 3 | 0 | 20 | 0 | 12 |
| 5 | 10 | 27 | 4 | 14 |
| 8 | 16 | 48 | 10 | 17 |
| 12 (alle) | 18 | 34 | 10 | 11 |

V0 lässt bei kleinen Profilen nichts durch, V1 lässt jeden durch, der das eine
Merkmal trägt (die Skala passt sich an, ohne zu wissen, wie sicher das Profil
ist), V3 ist gleichmäßiger.

### 5.2 Längenverzerrung und Robustheit

| | V0 | V1 | V2 | V3 |
|---|---|---|---|---|
| Korrelation Wert und Zahl der Merkmale (kleiner = besser) | 0,27 | 0,27 | 0,30 | **0,05** |
| Rangstabilität bei 40 % weniger Merkmalen (Spearman, größer = besser) | 0,85 | 0,85 | 0,84 | **0,90** |
| Anteil mit anderer Sternstufe bei 40 % weniger Merkmalen | 39 % | 35 % | 42 % | — |
| Rangkorrelation zur heutigen Reihenfolge | 1,00 | 1,00 | 0,98 | 0,88 |

### 5.3 Häufigkeit der gemochten Familien in der Stichprobe

*nervenaufreibend* 48 %, *bedrohlich* 38 %, *große Ideen* 31 %, *Rätsel* 30 %,
*hart* 27 %, *rasant* 24 %, *gezeichnete Figur* 22 %, … *schräge Figur* 5 %.
Als IDF (glatt, natürlicher Logarithmus plus 1): 1,7 für *nervenaufreibend*, 2,2
für *Rätsel*, 3,9 für *schräge Figur*.

**Lesart.** Kein Prototyp ist überall besser. V3 (Kosinus mit Gewicht im Buch)
beseitigt die Längenverzerrung und macht die Reihenfolge stabiler, ändert aber die
Skala und bräuchte eine neue Eichung des Tors. V1 löst B-1 auf einen Schlag, ist
aber bei sehr schmalen Profilen überzuversichtlich. V2 verändert die Reihenfolge
kaum (0,98) und mildert weder die Längenverzerrung noch die Empfindlichkeit; die
Häufigkeiten stammen dazu aus einer kleinen, verzerrten Stichprobe (86 Bücher,
schon vorgefiltert), sodass ihr Nutzen hier nicht belegt ist.

## 6. Optionen je Befund

Die Verfahren mit Quellen und Lesestand stehen in
[urteil-verfahren.md](urteil-verfahren.md) (Abschnittsnummern dort in Klammern). Die
Recherche kommt zu einem ähnlichen Schluss wie diese Notiz: **das Urteil ist ein
saturierender, additiver Aggregator mit handgesetzten Gewichten; für jede
Schwäche gibt es ein benanntes Gegenstück, meist eine Zeile Arithmetik und kein
Modell.** Wo diese Notiz eine Zahl aus den eigenen Daten nennt, steht sie hier;
wo eine Quelle etwas belegt, verweist die Zeile darauf.

| Befund | Option | Was die Literatur dazu sagt | Eingriff, Aufwand | Preis oder Risiko |
|---|---|---|---|---|
| **B-1** absolute Skala | **(a)** das Tor öffnet, wenn das Profil die Schwelle nicht erreichen kann (#78) | Ablehnung mit Abdeckung statt fester Zahl (Chow 1970, El-Yaniv/Wiener 2010; 3.6) | erreichbaren Wert rechnen, ein Vergleich im Tor; **klein** | Profile knapp über der Schwelle bleiben schlecht sortiert |
| | **(b)** Tor als **Abdeckung**: die besten *k* % des Bestands oder Wert ≥ Schwelle, Reihenfolge nach Wert | dieselben Quellen | `apply()` bekommt eine Rangregel; **mittel** | braucht einen Vergleichsbestand (ein Fund allein hat keinen Rang); anfällig für Bestandsdrift |
| | **(c)** Wert relativ zum erreichbaren Höchstwert (Prototyp V1) | keine Quelle für unseren Fall | Nenner in `fit()`; **klein** | bei einem Merkmal überzuversichtlich (5.1: 19 Bücher passieren) |
| | **(d)** Mindestgröße für das Profil in der Erstaufnahme | – | Regel in `adopt`; **klein** | sperrt die Leserin aus, die wenig weiß |
| **B-2** Gewicht im Buch | Gestufter Faktor je Merkmal: prägend 1, deutlich < 1, am Rand kleiner; ebenso für den Abzug des Gegengewichts | gestufte, sättigende Häufigkeit (BM25: Robertson/Zaragoza 2009; Tagommenders: Sen/Vig/Riedl 2009; 3.1, 3.2) | `f_i × g(Gewicht)` in `fit()`; **klein** | die Zahlen g(·) sind an keiner Quelle geeicht; in den echten Steckbriefen ist „am Rand" mit 3 % kaum belegt, ein Gewicht trennte fast nur prägend (30 %) von deutlich (67 %) |
| **B-3** Empfindlichkeit und Streuung | **(a)** erst **messen**: ≤ 10 Bücher, 2–3 Mal mit unveränderter Anweisung beschreiben, Streuung des Werts bei festem Profil | Mitteln senkt Streuung (Wang u. a. 2023, nur als Hinweis, anderer Aufgabentyp; 3.8) | ein Skript; **klein** (ein bis zwei Bündel) | mischt sonst geänderte Anweisung und Zufall (5 von 15 Büchern mit zwei Beschreibungen einmal bekannt, einmal nicht) |
| | **(b)** dünne Steckbriefe (wenige Merkmale, ohne Text) **zeigen und kennzeichnen** statt hart zurückzuhalten | Ablehnungsoption (Chow 1970; 3.6), Untergrenze/Band (Wilson 1927, Brown/Cai/DasGupta 2001) | Kennzeichen in `Verdict`, Regel im Tor; **klein bis mittel** | kein Konfidenzintervall im statistischen Sinn, nicht so nennen |
| | **(c)** mehrere Beschreibungen mitteln (Merkmal gilt bei ≥ 2 von 3) | eigener Vorschlag | – | Kosten mal zwei bis drei je Fund; erst, wenn (a) Sternstufen kippen sieht |
| **B-4** Längenverzerrung | teilweise Längennormierung statt Kosinus | Kosinus (Manning u. a. 2008, §6.3.1) gegen BM25 mit b ≈ 0,5–0,8 als Kompromiss (Robertson/Zaragoza 2009, §3.5; 3.1) | Nenner in `fit()`; **klein** | Kosinus **bestraft** ein Buch, das viel vom Gemochten trägt, und belohnt dünne Steckbriefe (verschärft B-3); Prototyp V3 senkt die Längenkorrelation von 0,27 auf 0,05, ändert aber die Skala und die Eichung des Tors |
| **B-5** Facetten | **(a)** Doppelzählung entscheiden: Mitglieder einer getroffenen Facette nicht noch einmal einzeln zählen | Noisy-OR setzt „keine wesentliche Synergie" voraus (Onisko/Druzdzel/Wasyluk 2001; Díez; 3.3, C2); das Glossar entscheidet bewusst anders | eine Bedingung, ein Test; **klein** | eine Entscheidung gegen das Glossar (seit 24.09.2026); senkt R2 von 86 auf 80 % |
| | **(b)** weicher Übergang: bei drei oder mehr Familien anteiliger Beitrag (zwei von drei) | die Literatur stützt die Konjunktion (Lin u. a. 2019, Dieckmann u. a. 2009; 3.4), weichere Form ist **eigener Vorschlag, nirgends geprüft** | Regel in `fit()`; **klein** | gibt die klare Aussage „trägt die Kombination" ein Stück auf |
| **B-6** Muster zu schwer | Deckelung: ein einzelnes verstärktes Muster allein erreicht das Tor nicht; oder das Muster nach Seltenheit gewichten | IDF (Spärck Jones 1972; Robertson 2004; 3.1) | Faktor oder Deckel; **klein** | *Rätsel* steckt in 30 % der Steckbriefe, IDF 2,2 gegen 1,7 bei *nervenaufreibend*: IDF allein löst es nicht |
| **B-7** Ablehnung grob | **(a)** Stärke des Abzugs am Gewicht im Buch messen (siehe B-2) | – | **klein** | – |
| | **(b)** ein Abzug **je enttäuschendes Buch**, kumulativ über verschiedene Bücher | das **max** über negative Beispiele ist besser als Verschmelzen (Wang/Fang/Zhai 2008; 3.5); Summieren hat keinen Beleg | Gruppierung nach Ursprungsbuch; **mittel** | bei zwei enttäuschenden Büchern theoretisch |
| | Höhe 0,35 belassen | Rocchio-Spielraum γ/β 0,2 bis 0,33 (Manning u. a. 2008; Salton/Buckley 1990; 3.1) | – | die Leserin liegt am oberen Rand des Bereichs |
| **B-8** Häufigkeit | **IDF** je Familie, geglättet ln((N+1)/(df+1)) | Spärck Jones 1972; Robertson 2004; 3.1 | Multiplikator auf `f_i`; **klein** | Stichprobe klein und Thriller-lastig; Prototyp V2 ändert die Reihenfolge kaum (0,98); Nutzen nicht belegt |
| **B-9** Sonderfälle | Toleranz beim Schwellenvergleich (`share ≥ ab − 1e-9`) | eigene Rechnung | eine Zeile und ein Test; **sehr klein** | – |
| | Ausnahme im Tor für **neue Titel von Referenzautor:innen** (zeigen, mit Kennzeichen) | – | Regel im Tor; **klein** | mehr Funde im Bericht |
| | Genre aus einer festen Liste statt Freitext | vgl. #53 | Vokabular für Genres; **mittel** | – |
| | Konflikt gemocht/Gegengewicht auch in der Rechnung erkennen | – | Prüfung in `adopt` und Nachschärfen; **klein** | – |
| **S9** keine Lernschleife | Lernen mit Prior: Gewichte um den heutigen Wert verschieben, nicht neu schätzen | Prior aus dem Nutzerprofil hilft bei kleinen Mengen (Pazzani/Billsus 1997); hierarchische Priors über Tags (Vig u. a. 2010); starker Prior bei vollständiger Trennung (Gelman u. a. 2008; 3.3, 3.7) | – | braucht Urteile der Leserin: heute 15 „Mag ich", 2 „Doof", 2 eigene Sterne |
| | Zufallsauswahl **knapp unter dem Tor** (ein Fund je Bericht, gekennzeichnet) | Zufallsverkehr als Voraussetzung ehrlicher Auswertung (Li u. a. 2010; 3.6) | ein Zug im Tor; **klein** | jeder Fund kostet einen Platz im Bericht; der Nutzen kommt erst mit Urteilen der Leserin |

**Was in unserem Fall nicht lohnt** (Begründung in urteil-verfahren.md, Abschnitt 4):
Matrixfaktorisierung und Kollaboration (eine Leserin), Kalibrierung nach Platt
oder isotonisch (braucht hunderte Urteile), LinUCB und Thompson-Sampling als
Steuerung (gebaut für Millionen Ereignisse), Bradley/Terry (keine Paare),
Nutzenerhebung nach Keeney/Raiffa (die Leserin wird nicht zu Facetten befragt),
Naive Bayes auf Klappentext-Wörtern (hebelt ADR 33 aus), nächste Nachbarn als
alleiniges Urteil (Pazzani/Billsus 1997: in mehr als der Hälfte der Versuche
schlechter). Ein Naive-Bayes-Log-Odds-Wert mit Prior aus den heutigen Gewichten
kommt als **Schattenwert** infrage (berechnen, vergleichen, nicht zeigen), und
ein Nachbarwert als Auswahl des **Belegs** („trägt, wie *Leichenblässe*").

## 7. Empfehlung

Grundsatz der Recherche, den diese Notiz teilt: **klein und ohne Modellaufruf
zuerst, jeder Schritt einzeln messbar, keiner ändert die Bedeutung eines Sterns
ohne Gegenprobe.** Was in dieser Notiz gerechnet wurde, ist ein Anfang dafür und
kein Ersatz: es misst Verhalten, nicht Treffer.

**Stufe 0: der Prüfstand, vor jeder Änderung.**

1. Die Szenarien aus Abschnitt 3 als **Test** ablegen (`tests/…`, mit der Funktion,
   die das Tor benutzt): die ✓-Fälle als Zusicherung, die ✗-Fälle als bekannte
   Abweichung, die beim Beheben grün werden. Damit steht jede spätere Änderung
   gegen dieselbe Reihe.
2. Ein **Messskript** (`ebw`-Befehl oder Skript in `docs/`) mit den drei Zahlen aus
   Abschnitt 5: Durchlass nach Profilgröße, Längenkorrelation, Anteil geänderter
   Sternstufen bei dünnem Steckbrief. Ohne Modellaufruf.
3. **Wiederholungsmessung** (B-3 a): höchstens zehn Bücher, zwei- bis dreimal mit
   unveränderter Anweisung beschreiben, ein bis zwei Bündel. Der einzige Punkt,
   an dem ein Modell gefragt wird.
4. **Leave-one-out** an den 17 Büchern mit Relation (15 „Mag ich", 2 „Doof"):
   Profil aus den übrigen bilden, das ausgelassene beurteilen. Bei 17 Büchern
   zeigt das Umkippen, nicht Verbesserung.

**Stufe 1: sofort, klein, jeder Schritt für sich.**

- **Schwellentoleranz** (B-9): ein einzelnes verstärktes Merkmal liefert heute einen
  Stern statt zwei. Ein Test, eine Zeile.
- **Tor öffnet bei unerreichbarer Schwelle** (B-1 a, #78): keine leeren Stapel mehr
  durch ein schmales Profil.
- **Ausnahme für Referenzautor:innen** (B-9): ihre neuen Titel erscheinen mit
  Kennzeichen, statt am Tor zu scheitern. Wenn die Leserin das will (Frage 2).
- **Konflikt gemocht/Gegengewicht** und **Genre** vereinheitlichen (B-9), kleine
  Eingriffe im Profil und im Vokabular.

**Stufe 2: ohne Modell, mit Messung gegen den Prüfstand.**

1. **Doppelzählung von Facette und Mitgliedern klären** (B-5 a). Kleine Änderung, aber
   eine Entscheidung gegen das Glossar; sie senkt alle Facettenfunde um sechs Punkte.
2. **Gewicht im Buch** (B-2, #75), für Vorlieben **und** Gegengewichte, nachdem die
   Wiederholungsmessung (Stufe 0.3) gezeigt hat, wie stabil die Stufen sind. Ein
   prägendes Merkmal zählt 1, ein deutliches weniger; der Abzug eines am Rand
   getragenen Gegengewichts sinkt entsprechend.
3. **Muster deckeln** (B-6): ein einzelnes verstärktes Muster allein reicht nicht für
   das Tor.
4. **Teilweise Längennormierung** (B-4), nachdem die Zahl der Merkmale je Steckbrief
   festliegt (der Prompt verlangt vier bis acht; bei gleichem Treffer trennt Kosinus
   4 von 8 um den Faktor 1,4).
5. **Dünn-Kennzeichnung** (B-3 b) für Steckbriefe mit wenigen Merkmalen oder ohne
   Klappentext: zeigen, gekennzeichnet.

**Stufe 3: braucht Urteile der Leserin.**

1. **Zufallsauswahl knapp unter dem Tor**: die einzige Quelle für das, was das Tor
   an Gutem zurückhält.
2. **Lernen mit Prior**: Schwelle und Abstand der Sterne zuerst, Gewichte je Familie
   erst viel später. Erst wenn mehrere Dutzend Sterne über gezeigte **und**
   zurückgehaltene Funde vorliegen.

**Was ich nicht empfehle:** das Urteil gegen ein anderes Verfahren austauschen
(Kosinus, Naive Bayes, Nachbarn). Die Prototypen und die Literatur zeigen, dass
jedes davon einzelne Schwächen behebt und andere mitbringt (Kosinus bestraft
reiche Bücher, Naive Bayes wächst ohne Sättigung und schätzt bei zwei
enttäuschenden Büchern nichts, Nachbarn schneiden in der Vergleichsliteratur am
schlechtesten ab). Der heutige Aggregator ist erklärbar; jede Zeile der
Begründung ist ein Beitrag. Das ist mehr wert als eine Verbesserung um ein paar
Rangplätze.

## 8. Fragen an die Leserin

1. Soll ein Buch mit **einer** Facette (zwei ihrer wichtigsten Merkmale) fünf Sterne
   bekommen, auch wenn drei weitere Merkmale des Buchs nichts mit dem Profil zu tun
   haben (R2)? Oder soll die Doppelzählung entfallen (B-5 a)?
2. Sollen **neue Titel von Referenzautor:innen** das Tor immer passieren
   (gekennzeichnet), oder gelten sie wie jeder andere Fund (G1)?
3. Wie viele Vorschläge je Bericht will sie? Das entscheidet, ob das Tor eine feste
   Schwelle oder eine Abdeckung sein soll (B-1 b).
4. Soll ein Buch, das vom Modell **dünn** beschrieben wurde, mit Kennzeichen
   gezeigt werden, oder lieber fehlen (B-3 b)?
5. Reicht ihr ein Stapel, der auch **Zufälliges knapp unter dem Tor** zeigt, wenn
   es als solches gekennzeichnet ist, damit das Werkzeug lernt, was es zu
   Unrecht zurückhält?

## 9. Was diese Notiz nicht belegt

- Die Prototypen (Abschnitt 5) sind **nicht geeicht**. Sie zeigen Richtungen, keine
  richtigen Zahlen. Kein Wert hier ist eine Empfehlung für einen Faktor.
- Die Stichprobe (86 Steckbriefe) ist klein, verzerrt (vorgefilterte Funde und die
  eigenen Bücher der Leserin) und thriller-lastig. Häufigkeiten und Durchlass
  gelten für diesen Bestand.
- Es gibt keine Wahrheit gegen die gemessen wurde: 15 „Mag ich", 2 „Doof", 2 eigene
  Sterne. Die Bewertung „sinnvoll" folgt dem Zweck (Abschnitt 1), nicht einer
  Trefferquote.
- Die Streuung des Modells (B-3) mischt in den vorhandenen Paaren geänderte Anweisung
  und Zufall; sauber ist nur die Wiederholungsmessung (Stufe 0.3).
- Die Recherche liest mehrere Quellen nur als Abstract oder aus zweiter Hand; das
  steht dort je Quelle mit dem Lesestand, und die Aussagen hier hängen nicht
  daran, wo dieser dünn ist.

## 10. Nachtrag: Ziele, Review der Liste, Gesamtlösung (25.09.2026, abends)

Die Leserin hat drei Vorschläge aus Abschnitt 7 zurückgewiesen, und zu Recht: die
**Abdeckung** am Tor (B-1 b) würde gut passende Bücher abschneiden, nur weil gerade
viele passen; **neu beschreiben lassen** löst ein dünnes, aber passendes Buch
nicht (und ein Merkmal ergänzen kann nur, wer das Buch kennt); ein **Deckel für
Muster** benachteiligt die Hälfte der Bücher, die nur eines tragen (43 von 86
Steckbriefen). Dieser Abschnitt setzt deshalb bei den Zielen neu an und prüft jeden
Vorschlag dagegen, ob er einen anderen guten Fall beschädigt.

### 10.1 Ziele und Erwartungen an das Urteil

| Ziel | Erwartung |
|---|---|
| **Z1 Passung, nicht Menge** | Gemessen wird, wie viel **von diesem Buch** dein Geschmack ist, nicht wie viele Treffer es sammelt. Ein Buch, das nur vier Merkmale trägt und alle vier sind deine, passt sehr gut. |
| **Z2 unabhängig von der Profilgröße** | Ein schmales Profil kann ein passendes Buch erkennen; ein breites macht nicht jedes Buch passend. Über eine Dimension, zu der du nichts gesagt hast, weiß das Urteil nichts — sie zählt weder für noch gegen. |
| **Z3 Ausprägung zählt** | Was ein Buch prägt, zählt mehr als was am Rand vorkommt, bei Vorlieben wie bei Ablehnungen. |
| **Z4 Ablehnung wirkt nach Stärke** | Ein prägendes Gegengewicht zieht deutlich ab, eines am Rand wenig. Eine Kombination, die du liebst, rettet kein Buch, das vor allem aus dem besteht, was dich enttäuscht hat. |
| **Z5 Muster als eigene Frage** | Ein Erzählmuster sagt, *was für eine Geschichte* es ist; Merkmale sagen, *wie sie sich liest*. Ein Buch mit einem gemochten Muster ist nicht schlechter als eines mit drei. |
| **Z6 ehrlich bei dünner Beschreibung** | Wenig Beschreibung heißt: das Urteil rückt zur Mitte, statt nach unten zu fallen; es wird gekennzeichnet, nicht bestraft. |
| **Z7 ruhig gegen Rauschen** | Eine andere Beschreibung desselben Buchs soll die Stufe selten ändern. |
| **Z8 erklärbar, schnell, ohne Modell** | Jede Zeile der Begründung ist ein Beitrag; ein neues Profil wirkt sofort (ADR 33). |
| **Z9 an den eigenen Büchern geprüft** | Deine gemochten Bücher passieren; was dich enttäuscht hat, nicht; aus einer Stichprobe passiert eher weniger als mehr (Qualität vor Masse). |

### 10.2 Die Liste aus Abschnitt 6/7, geprüft gegen die Ziele

| # | Befund | ursprünglicher Vorschlag | Review | neu |
|---|---|---|---|---|
| 1 | schmales Profil erreicht das Tor nie | Tor öffnet bei unerreichbarer Schwelle | ✗ hält dann auch klare Ablehnungen nicht mehr zurück | durch Z1/Z2 gelöst: Passung je Dimension, zu der du etwas gesagt hast |
| 2 | breites Profil lässt mehr durch | Tor als Abdeckung (beste k %) | ✗ schneidet gute Bücher ab, wenn viele gut sind (Einwand der Leserin) | gestrichen. Die Menge regelt die **Anzeige** (der Stapel ist nach Übereinstimmung sortiert), nicht das Tor. Die Passung als Anteil wächst nicht mit dem Profil |
| 3 | Rundungsfehler an der Schwelle | Toleranz | ✓ | bleibt |
| 4 | Gewicht im Buch zählt nicht | Faktor je Stufe | ✓ | Teil der Gesamtlösung (Z3) |
| 5 | Stufe wackelt | erst messen | ✓ | bleibt; die Formel allein löst es nicht (10.4) |
| 6 | dünne Steckbriefe | zeigen, kennzeichnen; neu beschreiben; Merkmal ergänzen | ⚠ neu beschreiben/ergänzen ist keine Lösung für ein unbekanntes Buch (Einwand der Leserin) | Passung als Anteil mit Glättung (Z1, Z6): ein dünnes, passendes Buch steht oben, nicht unten; Kennzeichnung nur als Hinweis |
| 7 | Längenverzerrung | teilweise Längennormierung | ✓, aber einzeln gedacht | fällt mit 6 zusammen: der Anteil ist längenneutral |
| 8 | Facetten sind eine Klippe | anteilig bei 3+ Familien | ⚠ | Facette wird ein **Bonus** auf eine schon gute Passung, keine eigene Stufe; zwei von drei zählen über ihre Merkmale |
| 9 | Facette zählt doppelt | Mitglieder nicht noch einmal zählen | ✓ | erledigt sich: Mitglieder zählen einmal im Anteil, die Facette als Bonus |
| 10 | Muster zu schwer | Deckel für ein einzelnes Muster | ✗ benachteiligt Bücher mit genau einem Muster (Einwand der Leserin; 43 von 86) | **bestes** gemochtes Muster zählt, nicht die Zahl der Muster (Z5): ein Muster = drei Muster |
| 11 | Ablehnung grob | Abzug nach Gewicht, später je Buch | ✓ | Teil der Gesamtlösung (Z4); das Gegengewicht zählt zusätzlich im Anteil gegen |
| 12 | häufige wie seltene Merkmale | IDF später | ✓ | bleibt später; Stichprobe zu klein |
| 13 | Referenzautor:innen am Tor | Ausnahme | ✓ | bleibt, Frage an die Leserin |
| 14 | Profil nur aus Gegengewichten | Minimum oder Gegengewichte anwenden | ✓ | Gegengewichte anwenden: ohne Gemochtes ist die Passung neutral, die Ablehnung wirkt |
| 15 | Widerspruch gemocht/Gegengewicht | Hinweis | ✓ | bleibt |
| 16 | Genre als Freitext | feste Liste | ✓ | bleibt (#53) |
| 17 | keine Lernschleife | Zufall knapp unter dem Tor, Lernen mit Prior | ✓ | bleibt, Stufe 3 |
| 18 | kein Prüfstand | Szenarien als Test, Messskript | ✓ | bleibt, Stufe 0, **vor** der Umstellung |

### 10.3 Die Gesamtlösung

Drei Fragen statt einer Summe, jede mit eigener Zeile in der Begründung:

1. **Wie viel von diesem Buch ist dein Geschmack?** (Merkmale)
   Nur Merkmale aus Dimensionen, zu denen dein Profil etwas sagt (gemocht,
   Facette oder Gegengewicht). Jedes zählt mit seinem Gewicht im Buch (prägend 1,0,
   deutlich 0,7, am Rand 0,4), ein verstärktes 1,5-fach.
   `A = (Gewicht der gemochten + α·p₀) / (Gewicht aller + α)`, geglättet zum
   Vorab-Anteil p₀ = 0,1 mit α = 2: bei dünner Beschreibung rückt der Wert zur Mitte,
   statt zu kippen (Z6; das ist ein Bayes-Mittel, vgl. urteil-verfahren.md 3.3/C3,
   3.6/F2).
2. **Erzählt es eine Geschichte, die du magst?** (Muster)
   Das **beste** gemochte Muster im Buch: 0,35, verstärkt 0,5. Eins oder drei macht
   keinen Unterschied (Z5).
3. **Trägt es eine deiner Kombinationen?** (Facette)
   Ganz getroffen: Bonus 0,4. Die Mitglieder stecken schon in 1.

`Übereinstimmung = 1 − (1 − A)·(1 − Muster)·(1 − Facette)`, danach das stärkste
zutreffende Gegengewicht: `× (1 − 0,5·Gewicht im Buch)`, also prägend × 0,5,
deutlich × 0,65, am Rand × 0,8. Sterne und Tor wie heute (ab 0,4 drei Sterne), mit
Toleranz an der Schwelle.

### 10.4 Gemessen (Prototyp, nicht geeicht)

Szenarien (Auswahl; heute → Gesamtlösung):

| Fall | heute | Gesamtlösung | Ziel |
|---|---|---|---|
| vier Merkmale, alle gemocht | 2★ 34 % | **4★ 62 %** | Z1 ✓ |
| drei gemochte von fünf | 2★ 27 % | 3★ 42 % | Z1 ✓ |
| acht Merkmale, vier gemocht | 2★ 34 % | 2★ 39 % | Z1 ✓ (Hälfte ist Hälfte) |
| zwei Merkmale, beide gemocht (dünn) | 3★ 51 % | 4★ 74 % | Z6 ✓ |
| Profil aus drei Merkmalen, Buch trägt alle drei | 2★ 27 % | 3★ 48 % | Z2 ✓ |
| Profil aus einem Merkmal, Buch trägt es, andere Dimensionen | 1★ 10 % | 2★ 33 % | Z2 ⚠ (Glättung hält zurück, gewollt) |
| hart prägend gegen am Rand | 27 % / 27 % | 51 % / 44 % | Z3 ✓ |
| Facette + gemächlich **prägend** | 3★ 56 % | **2★ 30 %** | Z4 ✓ |
| Facette + gemächlich am Rand | 3★ 56 % | 3★ 49 % | Z4 ✓ |
| ein Muster + drei gemochte Merkmale | 3★ 56 % | 4★ 74 % | Z5 ✓ |
| drei Muster + dieselben Merkmale | 4★ 79 % | 4★ 74 % | Z5 ✓ (gleich) |
| nur verstärktes Muster, Merkmale neutral | 3★ 40 % | 3★ 52 % | ⚠ die Geschichte passt; ob das allein reicht, entscheidet die Leserin |
| eine Facette, sonst nichts Gemochtes | 5★ 86 % | 4★ 60 % | Doppelzählung weg ✓ |

Eigene Bücher (Fassung 6): alle sieben gemochten mit Steckbrief bleiben bei 4 bis 5
Sternen (67 bis 85 %); *Herr der Ringe* bleibt bei 1 Stern. **Der Schwarm** steht
bei 4 Sternen (79 %), heute bei 5 (92 %): **das löst keine Formel**, denn seit
Fassung 6 steht im Profil nichts mehr, was ihn ablehnt (das Gegengewicht
„große Welt" gilt nur noch bei Fantasy); das gehört ins Nachschärfen mit „Doof".

Stichprobe (55 Stapelfunde mit Steckbrief):

| | heute | Gesamtlösung |
|---|---|---|
| durchs Tor | 32 | 38 |
| Korrelation mit der Zahl der Merkmale | 0,31 | 0,19 |
| Durchlass bei 1 / 3 / 5 / 8 / 12 gemochten Merkmalen | 0 / 0 / 5 / 6 / 8 | 9 / 6 / 9 / 21 / 28 |
| Stufenwechsel, wenn 40 % der Merkmale fehlen | 27 % | 38 % |

**Was nicht gelöst ist.** Z7: eine Rechnung, die den *Anteil* misst, reagiert auf jedes
Merkmal einer kurzen Beschreibung; mehr Glättung senkt den Wechsel kaum
(α = 3: 35 %) und nimmt schmalen Profilen die Wirkung. Die Streuung muss an der
Beschreibung behandelt werden: erst messen (Stufe 0, Wiederholungsmessung), dann
ggf. nur *prägende* und *deutliche* Merkmale zählen oder zweimal beschreiben.
Z9: das Tor lässt mehr durch als heute (38 statt 32 von 55); die Eichung (p₀, α,
Schwelle) gehört auf den Prüfstand, bevor etwas umgestellt wird.

### 10.5 Reihenfolge

1. **Prüfstand** (Stufe 0): Szenarien als Test mit den Zielen Z1 bis Z9 als
   Zusicherungen, Messskript, Wiederholungsmessung der Beschreibung.
2. **Gesamtlösung hinter dem Prüfstand**, als eine Änderung an `fit()` mit neuen
   Zahlen in `bewertungsschema.yaml` und ADR-33-Nachtrag; die heutige Rechnung
   bleibt als Vergleich im Messskript.
3. Danach einzeln: Referenzautor:innen, Profil nur aus Gegengewichten, Widerspruch,
   Genre, später Lernen mit Prior.

### 10.6 Was *Der Schwarm* an den Zielen ändert (Aussage der Leserin, 25.09.2026)

> gemächlich und wenig Spannung, zu viele Schauplätze ohne Zusammenhang; nicht zu Ende gelesen.

Der Steckbrief sagt über dasselbe Buch: *fachkundig*, *episch angelegt* (Familie
große Welt), *großes Ensemble*, *gesellschaftskritisch*, **sich steigernd**
(Familie nervenaufreibend), *bedrohlich*, *große Ideen*; kein *gemächlich*.
Drei Lehren, die als Ziele fehlten:

| Ziel | Erwartung | Was heute fehlt |
|---|---|---|
| **Z10 Deine Erfahrung geht vor** | Bei einem Buch, das du gelesen hast, gilt, was **du** über es sagst: fehlt im Steckbrief ein Merkmal (gemächlich) oder steht eines darin, das du anders erlebt hast (Spannung), ersetzt deine Angabe die des Modells für dieses Buch und für alles, was daraus folgt (Gegengewichte, Facetten). Ein Buch mit *Doof* wird nie empfohlen. | Der Steckbrief ist nicht zu berichtigen (#61); die Buchseite zeigt für ein *Doof*-Buch eine Übereinstimmung von 79 %, als wäre es ein Vorschlag. |
| **Z11 Ablehnung so fein wie nötig** | Ein Gegengewicht kann ein **einzelnes Merkmal** meinen, nicht nur eine Familie: *episch angelegt* (viele Schauplätze, Der Schwarm) ist nicht *Weltenbau* (Neongrau, Herr der Ringe), auch wenn beide zur Familie große Welt gehören. | Gegengewichte gelten nur je Familie; die Einschränkung von „große Welt" auf Fantasy (Fassung 6) hat damit genau den Grund entfernt, aus dem *Der Schwarm* enttäuscht hat. |
| **Z12 Enttäuschendes prüft das Profil** | Jedes Buch mit *Doof* ist eine Probe: das Profil muss es unter das Tor bringen, sonst fehlt ihm eine Ablehnung, und die Seite sagt das beim Nachschärfen. | Nichts prüft das; *Der Schwarm* steht seit Fassung 6 bei 5 Sternen, ohne dass es jemandem auffällt. |
