# Verfahren für das Urteil: was die Literatur zu den neun Schwächen sagt

Schreibtischrecherche vom 2026-09-25 zum Urteil des Codes (`facets.fit`, ADR 33,
`docs/bewertungsschema.yaml`). Kein Modellaufruf, keine Live-Messung an einer
Quelle. Wo eine Zahl aus den eigenen Daten stammt, habe ich `data/snapshots.db`
**nur lesend** geöffnet und sage es dazu.

**Lesestand.** Hinter jeder Quelle steht, wie weit ich sie wirklich gelesen habe:

- **[V]** Volltext geholt und die tragenden Stellen gelesen (nicht jede Seite);
- **[A]** nur Abstract oder Suchauszug — was unten daraus folgt, ist entsprechend
  dünn;
- **[Z]** nur als Zitat in einer anderen Quelle gesehen, selbst nicht geöffnet
  (Rocchio 1971, Spärck Jones 1972, Pearl 1988, Keeney/Raiffa 1976, Chow 1970,
  Platt 1999, Zadrozny/Elkan, Wilson 1927, Bradley/Terry 1952, Einhorn 1970).

**Eigene Rechnung** und **eigener Vorschlag** heißt: das steht in keiner Quelle,
es ist mein Schluss. Wo die Literatur schweigt, sage ich das und erfinde keine
Zahl.

---

## TL;DR

- **Das Urteil ist ein saturierender Aggregator mit handgesetzten Gewichten**
  (Noisy-OR über Treffer), kein Wahrscheinlichkeitsmodell. Für die meisten der
  neun Schwächen gibt es in der Literatur ein benanntes Gegenstück, und das
  ist meist eine kleine Ergänzung (eine Zeile Arithmetik, kein neues Modell);
  keines löst eine Schwäche allein durch die Formel, wo Daten der Leserin
  fehlen (S9).
- **Am meisten Ertrag ohne Modellaufruf und ohne Leserinnen-Daten:**
  (1) Seltenheit gewichten (IDF, Spärck Jones 1972), (2) das Tor über die
  *Menge* statt über eine absolute Zahl steuern (Chow 1970, El-Yaniv/Wiener 2010:
  Risiko-gegen-Abdeckung), (3) das Gewicht im Buch als **sättigende** Stufe
  eingehen lassen (BM25, Robertson/Zaragoza 2009; Tagommenders, Sen/Vig/Riedl
  2009), (4) ein Urteil bei dünner Beschreibung **kennzeichnen statt abzuschneiden**
  (Chow-Reject; Wilson-/Beta-Untergrenze).
- **Ein Gegenbefund zur eigenen Annahme:** ein einzelnes Gegengewicht (max statt
  Summe) ist in der Literatur nicht falsch, sondern das, was Wang/Fang/Zhai 2008
  für mehrere negative Beispiele als wirksam messen. Die Schwäche (4) ist
  deshalb keine Schwäche, sondern ein **Gruppierungsproblem** (ein Abzug je
  enttäuschendem Buch, nicht je Gegengewicht).
- **Was fehlt, ist nicht ein besseres Verfahren, sondern ein Prüfstand.** Nach
  meinem Blick in `data/snapshots.db` (25.09.2026) gibt es 15 „Mag ich“, 2
  „Doof“ und 2 eigene Sterne der Leserin. Damit ist keine der Zahlen unten
  *statistisch* belegbar; sie taugen als Regressionsgerüst und für synthetische
  Invarianten (Abschnitt 5). `owned.yaml` scheidet aus (Maschinenurteile, siehe
  Gedächtnisnotiz „owned.yaml ist kein Prüfstand“).
- **Ein Fund am Rand:** ein einzelnes *verstärktes* gemochtes Merkmal rechnet
  sich in Gleitkomma zu 0,19999999999999996 und fällt unter die Schwelle
  `sterne_ab: 2: 0.2` (eigene Rechnung, Abschnitt 5.1). Kein Fehler für das Tor
  (das sitzt bei 3 Sternen), aber ein Beleg für Schwäche (8).

---

## 1. Zweck und Fragestellung

**Frage:** Welche in der Literatur etablierten Verfahren mildern welche der neun
bekannten Schwächen des heutigen Urteils, was verlangen sie an Daten, und in
welcher Reihenfolge lohnt sich das für **eine** Leserin mit 3–15 Beispielen?

**Was das heutige Urteil ist** (aus dem Code gelesen, nicht aus der Aufgabe
übernommen):

- `fit()` bildet `share = 1 − Π(1 − f_i)` über: getroffene Facetten (0,8),
  gemochte Merkmale (0,1; verstärkt 0,2), gemochte Erzählmuster (0,3; verstärkt
  0,4); ein getroffenes Gegengewicht (das erste) multipliziert `share` mit
  `1 − 0,35`. Sterne aus `sterne_ab`; das Tor hält unter 3 Sternen zurück.
- Ein gemochtes Merkmal, das in einer getroffenen Facette steckt, zählt **trotzdem**
  einzeln (`factors += [weights.liked(g, …) for g in liked]`; das Glossar sagt es
  ausdrücklich). Eine Facette mit drei Mitgliedsmerkmalen ergibt so 0,854 statt
  0,8 (eigene Rechnung).

**Was an unserer Lage anders ist als in fast jeder Quelle unten:**

1. **Eine** Leserin, keine Nutzergemeinde. Alles, was auf vielen Nutzern beruht
   (Kollaboration, Matrixfaktorisierung, Bandits mit Millionen Ereignissen),
   fällt weg oder schrumpft auf einen Gedanken.
2. **Ein Buch trägt wenige Merkmale, und die Zahl ist vorgegeben** (Anweisung:
   4–8; in den gespeicherten Steckbriefen 3–9 Familien, eigener Blick in die
   Datenbank). Die Länge ist eine Konstante des Prompts, kein natürliches
   Textmaß. Das ändert die Längenfrage (Abschnitt 3.1).
3. **Die Merkmale werden von einem Modell vergeben**, nicht von Nutzern; dessen
   Rauschen ist eine eigene Fehlerquelle (Schwäche 6), die in keiner klassischen
   Quelle vorkommt.
4. **Das Urteil ordnet und schließt aus, es sagt keine Sterne vorher.** Das
   Tor ist eine Ablehnungsentscheidung, keine Regression.

**Die neun Schwächen, kurz benannt** (S1–S9, wie in der Aufgabe):

| | Schwäche |
|---|---|
| S1 | absolute statt profilrelative Skala (ein Merkmal kommt nie ans Tor, viele sättigen) |
| S2 | Länge und Häufigkeit: mehr Merkmale treffen öfter; häufige zählen wie seltene |
| S3 | Facetten alles-oder-nichts |
| S4 | mehrere Gegengewichte wirken nicht kumulativ |
| S5 | Gewicht des Merkmals im Buch geht nicht ein |
| S6 | Beschreibung ist stochastisch |
| S7 | dünne Beschreibung ergibt niedrige Werte ohne Hinweis auf Unsicherheit |
| S8 | harte Schwellen ohne Band |
| S9 | keine Lernschleife aus den Sternen |

---

## 2. Tabelle: Verfahren × Schwäche

● = mildert die Schwäche nach Quelle oder klarer Rechnung; ○ = mildert sie
teilweise oder nur unter Bedingungen; · = tut nichts dafür. „Zeit“ meint den
Aufwand für uns: **k** klein (Stunden, nur Code), **m** mittel (Tage, braucht
Messgerüst), **g** groß (Daten, die wir nicht haben, oder Modellaufrufe).

| Verfahren (Abschnitt) | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S9 | Zeit |
|---|---|---|---|---|---|---|---|---|---|---|
| A1 IDF-Gewichtung (3.1) | · | ● | · | · | · | · | · | · | · | k |
| A2 Kosinus-/Längennormierung (3.1) | ○ | ● | · | · | · | · | ○ | · | · | k |
| A3 BM25-Sättigung, gestufte Häufigkeit (3.1) | ○ | ○ | · | · | ● | · | · | · | · | k |
| A4 Rocchio, β/γ (3.1) | · | · | · | ○ | · | · | · | · | ○ | k |
| B Tag-Profile mit gradierter Relevanz (3.2) | ○ | ○ | · | ○ | ● | · | · | · | ○ | k–m |
| C1 Naive Bayes, Log-Odds-Summe (3.3) | ○ | ○ | · | ● | ○ | · | ○ | · | ● | m |
| C2 Noisy-OR mit Leck, Kritik (3.3) | ○ | · | ○ | · | · | · | · | · | · | k |
| C3 Beta-Bernoulli je Merkmal (3.3) | ○ | · | · | ○ | · | · | ● | · | ● | m |
| C4 Kalibrierung Platt/isotonisch (3.3) | ● | · | · | · | · | · | · | ○ | ○ | g |
| D1 additive Nutzen, MAUT (3.4) | ○ | · | · | ○ | ● | · | · | · | · | m |
| D2 nichtkompensatorisch, EBA (3.4) | · | · | ● | ○ | · | · | · | · | · | k |
| E Fall-/Nachbarschaftsverfahren (3.5) | ○ | ○ | ○ | ● | ○ | · | · | · | ○ | k–m |
| F1 Ablehnungsoption (Chow) (3.6) | ○ | · | · | · | · | · | ● | ● | · | k |
| F2 Wilson-/Beta-Untergrenze (3.6) | · | · | · | · | · | · | ● | ● | · | k |
| F3 Explorieren (ε-greedy, Thompson, LinUCB) (3.6) | · | · | · | · | · | · | · | · | ○ | m–g |
| G1 Kritik-/Critiquing-Systeme (3.7) | · | · | · | ○ | · | · | · | · | ○ | m |
| G2 regularisierte logistische Regression, Prior (3.7) | ○ | · | · | ○ | · | · | · | · | ● | m–g |
| G3 hierarchische Priors (Familie → Dimension) (3.7) | · | · | · | · | · | · | ○ | · | ● | m |
| X Mehrfachbeschreibung mitteln (3.8, eigener Vorschlag) | · | · | · | · | ○ | ● | ○ | · | · | g (Modell) |
| H Diversität/Serendipity als Kostenrechnung (3.9) | · | · | · | · | · | · | · | · | · | – |

Die Spalte S3 ist bewusst dünn: die Literatur stützt die Alles-oder-nichts-Regel
eher, als sie zu kritisieren (3.4).

---

## 3. Die Verfahren

### 3.1 A: Vektorraum, Rocchio, IDF, Kosinus, BM25

**Kurzbeschreibung.** Bücher und Profil sind Vektoren über die Familien. Das Profil
entsteht aus den geliebten Büchern (Mittelwert) minus einem Anteil der
enttäuschenden (Rocchio); jede Familie wird mit ihrer Seltenheit (IDF) gewichtet;
das Urteil ist der Kosinus zwischen Profil und Buch. BM25 ersetzt die lineare
Häufigkeit durch eine sättigende Stufe und normiert die Länge nur teilweise.

**Quellen und was sie belegen.**

- **Rocchio.** Neuer Vektor = α·(altes Profil) + β·(Mittel der Zustimmung) −
  γ·(Mittel der Ablehnung); negative Komponenten werden auf 0 gesetzt. Das
  Lehrbuch nennt als übliche Werte α = 1, β = 0,75, γ = 0,15 und begründet
  γ < β damit, dass positive Rückmeldung viel wertvoller sei als negative;
  viele Systeme setzen γ = 0 (Manning/Raghavan/Schütze 2008, §9.1.1 **[V]**;
  Original Rocchio 1971 **[Z]**). Salton/Buckley 1990 (**[V]**, Abschnitt
  zu Tabelle 3) prüften β = 1/γ = 0, β = 0,75/γ = 0,25 und β = γ = 0,5 und
  fanden das mittlere Verhältnis 3 : 1 besser als die beiden anderen.
  Lops/de Gemmis/Semeraro 2011 (§3.3.2.2, **[V]**) führen Rocchio als
  Standardlerner inhaltsbasierter Systeme und merken an, dass es kein
  theoretisches Fundament und keine Leistungsgarantie hat.
  **Für uns:** die Zeile in `bewertungsschema.yaml` („Ablehnung wiegt … etwa ein
  Fünftel“) ist 0,15/0,75 = 0,2 (eigene Rechnung); Salton/Buckley kommen mit
  0,25/0,75 ≈ 0,33, ziemlich genau dort, wo das Schema mit 0,35 „von Hand“
  an den eigenen Büchern gelandet ist. Diese Werte stammen aus **Suchanfragen
  mit vielen beurteilten Dokumenten**; keine Quelle sagt etwas über 2–3
  enttäuschende Bücher. Der Handbefund („1 : 5 war zu wenig“) widerspricht der
  Literatur nicht: 0,15 (Lehrbuch) ist ihr *Startwert*, 0,25 (Salton/Buckley) der
  gemessen bessere.
- **IDF.** Spärck Jones 1972 (**[Z]**, über Robertson 2004 **[V]**): ein Merkmal,
  das in vielen Dokumenten steckt, unterscheidet schlecht und bekommt weniger
  Gewicht; die Formel ist idf = log(N/n_i). Robertson 2004 zeigt, dass sich das im
  probabilistischen Modell rechtfertigen lässt, und dass Robertson-Spärck-Jones-
  Gewichte **ohne Relevanzangaben auf eine Form von IDF hinauslaufen**
  (Robertson/Zaragoza 2009, §3.5 **[V]**). Das ist die Brücke zu C1: IDF ist die
  Basisrate im Nenner einer Log-Odds-Summe.
- **Kosinus.** Rohe Skalarprodukte wachsen mit der Dokumentlänge; die Division
  durch die Vektorlängen macht den Vergleich längenunabhängig (Manning u. a.
  2008, §6.3.1 **[V]**). Gegenposition: BM25 normiert nur *teilweise*, mit
  B = (1 − b) + b·dl/avdl, b = 0 aus, b = 1 voll; als brauchbar gelten
  0,5 < b < 0,8 und 1,2 < k₁ < 2 „in vielen Fällen“, das Modell selbst gibt keinen
  Wert vor (Robertson/Zaragoza 2009, §3.5 **[V]**).
- **Sättigung.** In BM25 hat der Beitrag eines einzelnen Merkmals eine
  Obergrenze, egal wie oft es vorkommt; die Autoren nennen das „saturation“ und
  eine „sehr wertvolle Eigenschaft“ (§3.4.2 **[V]**). Die Stufe ist tf/(k₁ + tf);
  bei k₁ = 1,2 und tf = 1, 2, 3, 8 ergibt (k₁ + 1)·tf/(k₁ + tf) 1,00, 1,38, 1,57,
  1,91 (eigene Rechnung: das Zweite ist schon 1,4-mal, das Achte nur 1,9-mal das
  Erste).

**Was es für unsere Schwächen tut.**

- **S2, Häufigkeit:** IDF. In den 87 Büchern mit bekanntem Steckbrief (eigener
  Blick in die Datenbank, jeweils der letzte Steckbrief) kommt die häufigste
  Familie (`nerve_racking`) in 41 Büchern vor (47 %), die mediane in 5–6; ln(N/df)
  ergibt 0,75 gegen 2,76, also ein Faktor von etwa 3,7 zwischen häufigster und
  mittlerer Familie. Heute zählen beide gleich (`merkmal_einzeln`: 0,1).
  *Vorbehalt:* der Bestand ist ein Thriller-Bestand (Funde aus gewählten Themen),
  die Seltenheit gilt also **in diesem Bestand**, nicht auf dem Buchmarkt.
- **S2, Länge:** Kosinus über Binärvektoren ist |A∩B|/√(|A|·|B|). Bei gleichem
  Treffer k hätte ein Buch mit 8 Familien 1/√2 ≈ 0,71 vom Wert eines mit 4
  (eigene Rechnung). Das *ist* die Längennormierung — und sie hat eine
  Kehrseite: Sie bestraft ein Buch, das *viel* von dem trägt, was die Leserin
  mag, und belohnt dünne Steckbriefe (verschärft S7). Da die Länge hier
  begrenzt ist (in den 97 bekannten Steckbriefen 3–9 Familien; eigener Blick), ist
  der Effekt klein; teilweise Normierung (b ≈ 0,5) wäre der sichere Kompromiss.
  Eine Messung dazu steht aus; die Literatur gibt für 4–8-Merkmal-Objekte keine
  Zahl.
- **S1:** Kosinus ist gegen die Profilgröße normiert (das Profil hat Länge 1),
  aber er kennt keine Sättigung und keine Unabhängigkeit; Facetten müssten als
  zusätzliche Dimension („alle Mitglieder da“) in den Vektor. Das ist ein Umbau
  des Urteils, keine Ergänzung.
- **S5:** BM25-Stufe als Vorbild für „prägend/deutlich/am Rand“: ein gestuftes
  tf mit Obergrenze statt eines Ja/Nein.
- **S4:** Rocchios γ bildet „eine Familie zählt negativ“ ab, nicht „zwei Gegengewichte
  summieren sich“.

**Voraussetzungen.** Nur die vorhandenen Steckbriefe. IDF braucht N und die
Trefferzahlen je Familie; mit N = 87 sind seltene Familien (df ≤ 2) sehr
unsicher — zu glätten (ln((N + 1)/(df + 1))). Kein Modellaufruf.

**Aufwand.** IDF und teilweise Längennormierung: klein. Rocchio/Kosinus als
Ersatz für Noisy-OR: mittel bis groß, weil Facetten, Erzählmuster und das
Gegengewicht umgezogen werden müssten.

**Risiken.**

- IDF misst Seltenheit, nicht Vorliebe. Es gewichtet nur, was die Leserin ohnehin
  als gemocht getippt hat; eine seltene Familie, die sie nicht getippt hat, bleibt
  ohne Wirkung. Das ist gewollt, heißt aber: IDF hebt „selten und gemocht“ und
  ändert an „häufig und gemocht“ nur den Abstand.
- Der Bestand ist klein und thriller-lastig; IDF über 87 Bücher schwankt mit
  jedem neuen Fund.
- BM25-Werte (k₁, b) sind für Text getunt; für 4–8 Merkmale ohne Wortzahl gibt
  es keine Quelle für die Werte.

---

### 3.2 B: Tag-Profile mit gradierter Relevanz (Tagommenders, Tagsplanations, Tag Genome)

**Kurzbeschreibung.** Jedes Merkmal („Tag“) hat zwei Größen: die **Relevanz** des
Tags für das Buch (0–1, gradiert) und die **Vorliebe** der Nutzerin für den Tag.
Der Wert eines Buchs ist die Summe der Produkte. Das ist die natürliche
Verallgemeinerung von „Merkmal mit Gewicht im Buch“.

**Quellen.**

- **Sen/Vig/Riedl 2009, „Tagommenders“ (WWW)** **[V]** ist der Ort, an dem die
  Summenformel steht — nicht in Tagsplanations, wie die Aufgabenstellung
  nahelegte. `implicit-tag(u, m) = Σ_t ntp(u, t)·w(m, t)`: normierte Tag-Vorliebe
  mal Gewicht des Tags am Film, über alle Tags des Films. Sie beschreiben das als
  Verwandten des Skalarprodukts zwischen Profil- und Dokumentvektor aus der
  Informationsgewinnung. Die Tag-Vorlieben werden je Tag auf Mittel 0 und
  Standardabweichung 1 normiert, sind also **vorzeichenbehaftet** — Ablehnung
  zieht in derselben Summe ab (additiv-kompensatorisch). Eine zweite Variante,
  `cosine-tag`, teilt durch die Summe der Ähnlichkeiten und ist damit ein
  gewichtetes *Mittel*, keine Summe. Nach ihren eigenen Messungen erzeugen die
  tagbasierten Verfahren bessere Empfehlungs*ränge* als die Vergleichsverfahren
  (Abstract). Ihr Regress-Tag-Verfahren, das Gewichte je Film aus den Ratings
  lernt, **überanpasst bei Filmen mit wenigen Ratings**; Support-Vector-Maschinen
  mit starker Regularisierung (c = 0,005) hielten am besten.
- **Vig/Sen/Riedl 2009, „Tagsplanations“ (IUI)** **[V]**: baut die *Erklärung*
  aus Relevanz und Vorliebe. Vorliebe = mit dem Tag-Anteil gewichteter Mittelwert
  der Bewertungen der Filme mit dem Tag, zur Durchschnittsnote der Nutzerin hin
  geglättet (Glättungskonstante 0,05); Tag-Anteil = Häufigkeit des Tags am Film
  durch alle Tag-Vergaben, im Nenner um 15 geglättet („um den Zufall
  abzumildern“; die Konstanten sind laut Fußnote **qualitativ an Testfällen**
  gewählt, nicht optimiert). Relevanz = Pearson-Korrelation. In einer
  Befragung von 556 Nutzern schnitt die Darstellung am besten ab, die Tags nach
  **Relevanz** sortiert und die Vorliebe daneben zeigt (RelSort) — Relevanz
  trägt die Erklärung, Vorliebe ergänzt.
- **Vig/Sen/Riedl 2012, „The Tag Genome“ (ACM TiiS)**: nur als Zusammenfassung
  gesehen **[A]**; den Volltext der Vorstufe („Computing the Tag Genome“,
  Technical Report 2010) habe ich gelesen **[V]**: Relevanz ist eine **stetige
  Größe von 0 (trifft nicht zu) bis 1 (trifft stark zu)** je Buch/Film und Tag,
  aus einer Befragung (50.203 Bewertungen von 676 Nutzern) und Regression über
  Tags, Bewertungen und Rezensionen gelernt. Bemerkenswert für uns: der
  Regressionsansatz mit **hierarchischem Prior über die Tags** (Koeffizient je
  Tag aus einer gemeinsamen Normalverteilung) war mit MAE 0,211/0,220 besser als
  ein gemeinsames Modell (0,234/0,237) und besser als getrennte je Tag
  (0,224/0,253) — der Beleg für „teilweises Zusammenlegen“ (3.7).

**Was es für unsere Schwächen tut.**

- **S5** ist der direkte Treffer: Gewicht im Buch als stetige oder gestufte
  Größe in der Summe. Unsere Stufen sind aber **vom Modell vergeben**, nicht aus
  Nutzerdaten gelernt wie im Tag Genome; ihre Verlässlichkeit ist offen (S6).
  Eigene Verteilung (Datenbank, 25.09.2026): von 272 gestuften Merkmalen sind
  *deutlich* 183 (67 %), *prägend* 82 (30 %), *am Rand* nur 7 (3 %). Die Stufe
  „am Rand“ wird also fast nie vergeben; ein Gewicht würde vor allem zwischen
  prägend und deutlich unterscheiden. Die übrigen 396 von 668 Merkmalen tragen
  gar kein Gewicht (Erzählmuster haben keins, ältere Steckbriefe vor #62 auch
  nicht).
- **S1/S2:** die Summe ist unbeschränkt und wächst mit der Merkmalszahl — dieselbe
  Längenschwäche, die wir haben; die Autoren selbst bieten `cosine-tag` als
  Mittelwert an.
- **S4:** in derselben Summe zählt Ablehnung negativ; das ist kumulativ, aber
  ohne Sättigung.

**Voraussetzungen.** Relevanz je (Buch, Merkmal) ist bei uns vorhanden (Stufe);
Vorlieben je Merkmal haben wir als Getippt-Sein (0/1/verstärkt), nicht als
Wert aus Bewertungen. Die Tagsplanations-Formel für die Vorliebe braucht
Bewertungen vieler Bücher je Merkmal — die haben wir nicht.

**Aufwand.** Als Zusatz in `fit()` (`f_i × g(Gewicht)`) klein; als Ersatz nicht
sinnvoll (siehe 4).

**Risiken.** Die Erklärung „Relevanz × Vorliebe“ gaukelt eine Genauigkeit vor,
die die Stufen nicht tragen. Ein stufenloses 0–1 aus dem Modell wäre nicht
stabiler (S6).

---

### 3.3 C: Wahrscheinlichkeitsmodelle

#### C1 Naive Bayes, Log-Odds-Summe („Beweisgewicht“)

**Kurzbeschreibung.** Je Merkmal wird gezählt, in wie vielen gemochten und wie
vielen enttäuschenden Büchern es vorkommt; das Beweisgewicht ist
log( P(Merkmal | gemocht) / P(Merkmal | enttäuschend) ); das Urteil ist die
Summe der Gewichte der getroffenen Merkmale plus das Vorab-Verhältnis.

**Quellen.**

- **Mooney/Roy 2000 (LIBRA)** **[V]** ist das nächste Vorbild, weil es um
  *Bücher* geht: Naive Bayes über Textfelder, Rang nach der Wahrscheinlichkeit
  „gemocht“ (Bewertung 1–5 negativ, 6–10 positiv), Laplace-Glättung, und die
  Erklärung als Liste der Merkmale mit dem größten Beitrag, „Stärke“ = log des
  Verhältnisses. Die genauen Bewertungen der Trainingsbücher gehen als Gewichte
  der Beispiele ein. Ergebnis: schon bei 10 Trainingsbüchern eine mittlere
  Rangkorrelation (rs ≥ 0,3) in vier von fünf Datensätzen, bei 20 Büchern lagen
  die drei bestbewerteten Empfehlungen im Mittel über 8 (Ausnahmen: LIT1 und SF).
  *Vorbehalt:* das sind Wörter aus Klappentexten und Rezensionen, nicht
  4–8 Merkmale, und die Datensätze haben 500–936 Bücher, die je eine Person
  bewertet hat.
- **Pazzani/Billsus 1997** **[V]**: Naive Bayes lernt Nutzerprofile
  inkrementell; bei 10–45 Beispielen „vielversprechend“, in zwei Bereichen
  (unabhängige Künstler) auf Zufallsniveau. Bayes, Rocchio und Backpropagation
  „summieren Belege über viele Merkmale“ und schnitten ähnlich gut ab; die
  **nächsten Nachbarn schnitten in mehr als der Hälfte der Versuche
  signifikant schlechter**, auch mit mehreren Nachbarn (Abschnitt 3 der
  Arbeit). Vom Nutzer *angegebene* Profilmerkmale, als Prior in den Zähler
  gesetzt, halfen besonders bei kleinen Trainingsmengen; nur diese Merkmale zu
  benutzen war „mindestens so genau“ wie die Prior-Methode. Das stützt unser
  Vorgehen, die Leserin die Merkmale antippen zu lassen — belegt an Webseiten,
  nicht an Büchern.
- **Domingos/Pazzani 1997** **[A]**: die Klassifikation kann auch bei stark
  verletzter Unabhängigkeit optimal sein, die *Wahrscheinlichkeiten* dagegen
  nicht. Niculescu-Mizil/Caruana 2005 **[V]** bestätigen: Naive Bayes schiebt
  Wahrscheinlichkeiten Richtung 0 und 1.
  **Konsequenz:** als **Rang** taugt die Summe, als „Prozent“ nicht.

**Was es tut.**

- **S1:** die Log-Odds-Summe hat einen Ursprung (das Vorab-Verhältnis) und beide
  Seiten in einer Währung. Sie sättigt nicht (die Summe wächst unbeschränkt) —
  das ist die *Umkehr* der Noisy-OR-Eigenschaft, mit dem Preis, dass sehr viele
  Treffer sehr sicher aussehen. Ob sich daraus profilrelative Schwellen ergeben,
  hängt an einer Referenzverteilung (F1), nicht an der Formel.
- **S4:** Ablehnung ist ein Beweisgewicht mit Vorzeichen; mehrere *addieren*
  sich. Die Sorge des Schemas (mehrere Gegengewichte aus **einem** Buch zählen
  dieses mehrfach) bleibt: das ist eine Frage der Gruppierung, nicht der
  Formel.
- **S9:** Zählen ist Lernen. Jedes neue „Mag ich/Doof“ ändert die Zähler.

**Voraussetzungen.** Zähler je Familie aus den gemochten und den enttäuschenden
Büchern: bei uns 15 und 2. Ohne starken Prior ist das Verhältnis für fast jede
Familie ±unendlich oder unbestimmt (Familie in 3 von 4 gemochten und 0 von 2
enttäuschenden: mit Laplace 0,67 / 0,25, also LLR ≈ 0,98; eigene Rechnung).
**Mit zwei enttäuschenden Büchern lässt sich die Gegenseite nicht schätzen** —
das ist das Grundproblem, und Pazzani/Billsus lösen es mit einem *Prior aus dem
Nutzerprofil*, nicht mit Daten.

**Aufwand.** Als **Schattenwert** neben dem Noisy-OR (nur berechnen, vergleichen,
nicht anzeigen): klein bis mittel.

**Risiken.**

- Verletzte Unabhängigkeit. Ich habe drei Paare häufiger Familien nachgezählt
  (87 Bücher, jeweils letzter Steckbrief): `nerve_racking`/`menacing` φ = 0,16,
  `nerve_racking`/`plot_driven` φ = 0,26, `atmospheric`/`menacing` φ = 0,18. Das
  ist **schwach**; für diese Paare ist die Unabhängigkeit keine grobe Verletzung.
  Für die übrigen Paare habe ich nichts gemessen. Die Familien sind gerade zur
  Bündelung von Synonymen gebaut, was die Korrelation klein hält.
- Zwei enttäuschende Bücher sind keine Basis für eine Gegenseite.

#### C2 Noisy-OR (Pearl 1988): Grundlagen und Grenzen

**Kurzbeschreibung.** Mehrere Ursachen können ein Ereignis jeweils *für sich*
auslösen; jede tut es mit Wahrscheinlichkeit p_i, unabhängig von den anderen;
P(Ereignis) = 1 − Π(1 − p_i). Mit „Leck“ p₀ (Henrion 1989): auch ohne jede
modellierte Ursache kann das Ereignis eintreten.

**Quellen.** Pearl 1988 **[Z]**. Was ich **[V]** gelesen habe: Onisko/Druzdzel/
Wasyluk 2001 (§2, §5): die zwei Annahmen sind (1) jede Ursache ist für sich
hinreichend und (2) ihre Wirkung ist von der Anwesenheit der anderen
unabhängig; Díez' Prüfregeln für die Anwendbarkeit sind: die Variablen zeigen
den *Grad des Vorhandenseins* an, jede Ursache **kann für sich** wirken, und es
gibt **keine wesentliche Synergie** zwischen den Ursachen. Das Leck p₀ ist der
gemeinsame Effekt aller nicht modellierten Ursachen. Der Vorteil ist, dass
sich die ganze Tabelle aus n Zahlen statt 2ⁿ ergibt; genau deshalb setzen die
Autoren es für **kleine Datensätze** ein. Díez 1993 (UAI) **[V]** verallgemeinert
auf mehrwertige Variablen. Der Titel „Using the Noisy-OR Model Can Be Harmful …
But It Often Is Not“ (ECSQARU 2011, Springer) ist mir nur als Titel begegnet
**[Z]**; ich habe ihn nicht gelesen und behaupte nichts über den Inhalt.

**Einschätzung für uns (eigene Analyse, kein Beleg).**

- Wir benutzen Noisy-OR als **saturierenden Aggregator** („mehrere Gründe
  verstärken sich, ohne je Gewissheit zu erreichen“), nicht als Kausalmodell.
  Dafür ist er ein guter, kleiner Kern. Aber `share` ist dann **keine
  Wahrscheinlichkeit**: die f-Werte sind handgesetzte Gewichte, nicht
  gelernte p_i. „47 %“ (das Beispiel „Der Schwarm“ im Schema) heißt nicht, dass
  jedes zweite solche Buch der Leserin gefiele. Die Oberfläche nennt es
  „Übereinstimmung“ — das ist richtig; ein „Prozent gefällt“ wäre falsch.
- Die **Synergie-Bedingung** ist bei Facetten verletzt (eine Facette *ist* eine
  Synergie), und die Facette mit ihren Mitgliedsmerkmalen zählt doppelt
  (0,854 statt 0,8). Das ist kein Fehler des Modells, sondern eine Entscheidung
  des Glossars — aber sie ist eine, und sie ist unbelegt.
- Das **Leck** ist der begriffliche Ort für S1: p₀ = die Wahrscheinlichkeit, dass
  ein beliebiges Buch gefällt. Das Schema sagt schon, dass ein beliebiges Buch
  drei Sterne zu etwa 27 % und vier Sterne zu etwa 5 % erreicht. Ein Leck
  verschöbe alle Werte, und ohne Daten für p₀ wäre es eine weitere handgesetzte
  Zahl.
- Noisy-OR **sättigt, aber langsam und je nach Profil an anderer Stelle**: mit
  k Merkmalen à 0,1 erreichen 3 Merkmale 0,27, 5 Merkmale 0,41, 9 Merkmale 0,60, 16 Merkmale 0,82,
  30 Merkmale 0,96 (eigene Rechnung). Ein Profil mit einem einzigen gemochten
  Merkmal kommt nie über 0,2 (verstärkt) und damit nie ans Tor bei 3 Sternen;
  ein einzelnes verstärktes Erzählmuster kommt dagegen auf 0,4, gerade drei
  Sterne. Am anderen Ende: bei 30 von 56 gemochten Familien trifft ein
  beliebiges Buch mit 6 Familien im Erwartungswert etwa 3 davon (6 × 30/56,
  eigene Rechnung unter Gleichverteilung) und liegt bei 0,27, nahe an der
  Schwelle 0,4, die fünf Treffer erreichen. Beides ist S1, und beides ist eine
  Eigenschaft der Formel, nicht der Zahlen.

**Aufwand.** Leck oder Deckelung: klein. Das Doppelzählen zu klären: klein
(eine Bedingung in `fit()` und ein Test), aber eine Entscheidung gegen das
Glossar.

#### C3 Beta-Bernoulli je Merkmal

**Kurzbeschreibung.** Für jede Familie ein Zähler „unter den gemochten Büchern
kam sie vor / kam nicht vor“ mit einem Beta-Prior; das Ergebnis ist der
Erwartungswert und ein Intervall.

**Quellen.** Laplace-Glättung („eins zu jedem Zähler“) als Standard der Naive-Bayes-
Klassifikation (Lops u. a. 2011, §3.3.2.1 **[V]**; Mooney/Roy 2000 **[V]**).
Beta-Prior als konjugierte Verteilung des Binomials, Aktualisierung durch
Zählen (Chapelle/Li 2011, Alg. 2 **[V]**; ihr Anfangsprior in den Versuchen ist
Beta(1, 1)). Agresti/Coull 1998 **[A]**: „zwei Erfolge und zwei Misserfolge
zuschlagen“ liefert schon bei kleinen Stichproben brauchbare Intervalle.
Pazzani/Billsus 1997 **[V]**: ein *Prior aus dem Nutzerprofil* hilft besonders
bei kleinen Trainingsmengen.

**Was es tut.** S7 (ein Erwartungswert und ein Band aus wenigen Zählungen statt
eines nackten Anteils) und S9 (Zähler wachsen mit jedem Urteil). Die
Leserin gibt heute *Getipptes* (Prior); jedes „Mag ich“ und „Doof“ wäre ein
Zählschritt.

**Voraussetzungen.** Ein Prior je Familie: naheliegend ist das *heutige* Gewicht
(0,1) als Prior-Mittel mit einer kleinen Pseudo-Zahl (etwa 2–4 Beobachtungen,
**eigener Vorschlag, keine Quelle für den Wert**).

**Risiken.** Bei 15 gemochten Büchern rührt sich fast nichts; der Prior
dominiert, und das ist die richtige Ehrlichkeit. Aber aus dem *Getippten*
(die Leserin sagt „das zählt“) und dem *Beobachteten* (in wie vielen ihrer
Bücher es vorkommt) sind zwei verschiedene Informationen; Beobachtetes zu
zählen nimmt das Tippen nicht ernst.

#### C4 Kalibrierung (Platt 1999; Zadrozny/Elkan; Niculescu-Mizil/Caruana 2005)

**Kurzbeschreibung.** Ein Modellwert wird in eine Wahrscheinlichkeit
umgerechnet: Platt: P(y = 1 | f) = 1/(1 + exp(A·f + B)), A und B durch
Maximum Likelihood; isotonische Regression: eine monotone Treppenfunktion.

**Quellen.** Niculescu-Mizil/Caruana 2005 **[V]** (Platt 1999 und Zadrozny/Elkan
2001/2002 **[Z]** über diese Arbeit). Plattskalierung ist am wirksamsten bei
sigmoid-förmigen Verzerrungen; isotonische Regression korrigiert jede monotone
Verzerrung, ist aber **anfälliger für Überanpassung** — bei Kalibriermengen unter
etwa **200–1000 Fällen** war Platt bei allen neun getesteten Lernverfahren besser;
getestet wurden Mengen ab 32 Fällen. Naive Bayes zeigte eine umgekehrt
sigmoide Verzerrung, für die isotonische Regression besser passte.

**Was es tut.** S1 (der Wert wird zu einer Wahrscheinlichkeit *für diese
Leserin*, damit sind Schwellen interpretierbar) und S8 (ein kalibrierter
Wert erlaubt Kosten-Rechnung statt „drei Sterne“).

**Voraussetzungen.** Urteile der Leserin je Fund: **hunderte**, nicht 2. Selbst
die kleinste getestete Menge (32) liegt jenseits dessen, was vorhanden ist
(2 eigene Sterne; 17 „Mag ich/Doof“, aber alle *ausgewählt*, nicht zufällig
gezogen — siehe 3.6 zur Auswahlverzerrung).

**Fazit.** Nicht jetzt. Der Nutzen tritt erst mit einer Datenmenge ein, die im
Zeitmaßstab dieses Werkzeugs Jahre braucht. Was bleibt: **Ränge statt
Wahrscheinlichkeiten** zeigen (was das Werkzeug schon tut).

---

### 3.4 D: Nutzenmodelle und nichtkompensatorische Regeln

**Kurzbeschreibung.**

- **Additiver Mehrattributnutzen (MAUT)**: U(Buch) = Σ w_i·u_i(x_i). Jede Größe
  kann eine andere ausgleichen („kompensieren“). Nach Keeney/Raiffa 1976 **[Z]**
  ist die additive Form erlaubt, wenn die Attribute wechselseitig
  präferenzunabhängig sind (*das ist Lehrbuchwissen, hier nicht neu belegt*).
- **Nichtkompensatorisch**: eine *konjunktive* Regel („jede Anforderung muss
  erfüllt sein“), eine *lexikographische* („erst das wichtigste Merkmal
  entscheidet“), oder **Elimination durch Aspekte** (Tversky 1972 **[A]**: in
  jedem Schritt wird ein Aspekt mit einer Wahrscheinlichkeit proportional zu
  seinem Gewicht gewählt, und alle Alternativen ohne ihn scheiden aus, bis eine
  bleibt).

**Quellen und Befunde.**

- Einhorn 1970 (Psychological Bulletin 73, S. 221–230) **[Z]** als Ursprung
  nichtlinearer, nichtkompensatorischer Modelle in der Entscheidungsforschung.
- **Lin/Shen/Chen/Zhu/Xiao 2019** (AAAI, „Non-Compensatory Psychological Models
  for Recommender Systems“) **[A]**: Empfehlungsmodelle rechnen gewöhnlich
  kompensatorisch; die Autoren führen *Mindestschwellen* („Dealbreaker“) und einen
  „prominenten Aspekt“ pro Nutzer ein und berichten deutlich bessere
  Rangqualität (AUC-Steigerung bis 53,95 % bei einem Datensatz, den sie
  nennen). Sie stützen sich auf die Angabe, dass über 70 % der Menschen
  nichtkompensatorische Regeln nutzen — das steht im Abstract, den Beleg habe ich
  nicht geprüft.
- **Dieckmann/Dippold/Dietrich 2009** (Judgment and Decision Making) **[A]**: an
  Skijacken war das **kompensatorische** Modell insgesamt besser; etwa ein Drittel
  der Teilnehmer wurde vom lexikographischen besser vorhergesagt.

**Was es für uns tut.**

- **S3:** unsere Facette (nur wenn *alle* Familien getroffen) ist eine **konjunktive
  Regel** und das Gegengewicht ebenso; das Glossar sagt, was passiert, wenn man
  sie kompensatorisch macht: Teiltreffer summieren sich, bis ein Buch passt, das
  „niemandem“ gefällt. Beides stützt die Alles-oder-nichts-Regel — bei einem
  *Preis*: eine Klippe. Was ein Teiltreffer an Facettenbeitrag nicht bekommt,
  fängt teilweise auf, dass die getroffenen Merkmale einzeln zählen (seit
  24.09.2026). Ein
  weicher Übergang, der die Konjunktion nicht aufgibt, wäre ein **Minimum der
  Merkmalsgewichte** im Buch (bei Gewicht im Buch, S5) statt einem Ja/Nein
  (**eigener Vorschlag; nirgends geprüft**).
- **S4:** ein *Dealbreaker* ist genau das, was das Gegengewicht sein soll
  (zieht ab, schließt nicht aus). Die Quelle spricht für Schwellen; das Glossar
  (ADR 33) hat sich dagegen entschieden („keine Gegenanzeigen“). Das ist
  eine Wertentscheidung, kein Befund.
- **S5:** additive Nutzen mit *Stufen je Attribut* sind das Gewichts-Modell.

**Voraussetzungen.** MAUT-Verfahren fragen Abwägungen ab („Was wäre dir lieber
…?“). Das Glossar hält fest, dass die Leserin nie nach einer Facette gefragt
wird; Nutzenelicitation nach Keeney/Raiffa passt nicht zu dieser
Grundhaltung.

**Aufwand.** Klein, wo es um die *Wahl der Regel* geht; groß, wo Nutzenfunktionen
erhoben werden müssten.

**Risiken.** Die Befunde stammen aus Konsumentenwahl (Skijacken) und großen
Nutzerbasen; für das Gegengewicht *einer* Leserin gibt es keinen Beleg in beide
Richtungen.

---

### 3.5 E: Fall- und Nachbarschaftsverfahren

**Kurzbeschreibung.** Der Wert eines neuen Buchs richtet sich nach seiner
Ähnlichkeit zu den gemochten und den enttäuschenden Büchern: etwa das Maximum
der Ähnlichkeit zu einem gemochten Buch, minus (mit Gewicht) das Maximum zu einem
enttäuschenden; als Ähnlichkeit gewichtetes Jaccard oder Kosinus über
Merkmalsvektoren.

**Quellen.** Lops u. a. 2011 (§3.3.2.3 **[V]**): Nachbarverfahren speichern alle
Beispiele und vergleichen das neue mit ihnen (Kosinus, wenn Vektorraum); wirksam,
aber ohne Trainingsphase und mit Rechenlast beim Klassifizieren. **Gegenbefund**:
Pazzani/Billsus 1997 **[V]** — nächste Nachbarn schnitten in mehr als der Hälfte
ihrer Versuche **signifikant schlechter** ab als Bayes/Rocchio/Netz; mehrere
Nachbarn halfen nicht. Wang/Fang/Zhai 2008 **[V]**: bei negativen
Beispielen (nur Ablehnung bekannt) war es wirksam, **jedes negative Dokument als
eigene Anfrage** zu nehmen und die Ähnlichkeiten mit **max** zu verbinden
(„MultiNeg“) statt sie zu einem Mittelwert zu verschmelzen, weil negative
Dokumente „auf verschiedene Weise ablenken“; ihr Befund gilt für schwierige
Suchanfragen (TREC), nicht für Buchgeschmack. Schein u. a. 2002 **[A]** (Cold
Start; Inhalt + Kollaboration in einem probabilistischen Rahmen, Vergleich mit
Naive Bayes, neue Kennzahl CROC) und Rashid u. a. 2002 **[V]** (welche Filme einem neuen Nutzer zum Bewerten
vorzulegen sind: laut Schlusswort schneiden Strategien gut ab, die richtig
raten, was die Nutzerin überhaupt beurteilen kann; reine Entropie riskiert
Unbekanntes; **für kollaborative Systeme gerechnet**, überträgt sich kaum auf
eine einzelne Leserin).

**Was es tut.**

- **S4:** das *max* über negative Beispiele ist genau das, was das Schema
  macht („nur das stärkste zählt“) — und die Literatur bestätigt, dass ein
  max über mehrere negative Modelle einem verschmolzenen Modell überlegen
  ist. Eine Summe hätte *keinen* Beleg.
  Was die Literatur *nicht* sagt: wie mehrere *verschiedene* enttäuschende
  Bücher zusammenwirken. Der einzige Ansatzpunkt ist die Gruppierung: **ein
  Abzug je enttäuschendes Buch**, nicht je Gegengewicht (das Schema fürchtet
  genau das Doppelzählen) — kumulativ über verschiedene Bücher, etwa
  `share × Π(1 − c_b)` mit einem c_b je Buch; **eigener Vorschlag**, ohne
  Beleg; bei zwei enttäuschenden Büchern ohnehin theoretisch.
- **S3:** stufenloser Übergang, weil der Wert eine Ähnlichkeit ist, kein
  Bündel-Treffer.
- **Erklärung:** „trägt, wie David Hunter“ ist im Glossar schon als Beleg
  *innerhalb* einer Begründung vorgesehen, nie als eigener Grund. Ein
  Nachbarwert kann diesen Beleg auswählen (das ähnlichste geliebte Buch).

**Voraussetzungen.** Die Merkmale der 15 geliebten und 2 enttäuschenden Bücher
liegen vor (Steckbriefe). Kein Modellaufruf.

**Aufwand.** Klein (eine Funktion neben `fit()`), wenn nur als zweiter
Meinungsgeber und Erklärung.

**Risiken.** Bei 2 negativen Beispielen ist „Ähnlichkeit zu den enttäuschenden“
fast ein Einzelfallvergleich; und Pazzani/Billsus sehen Nachbarn als schwächstes
Verfahren. Als **Urteil** ungeeignet, als **Belegwahl** nützlich.

---

### 3.6 F: Unsicherheit, Zurückhalten, Erkunden

#### F1 Klassifikation mit Ablehnung (Chow 1970)

**Kurzbeschreibung.** Ein Klassifikator darf „weiß nicht“ sagen; man tauscht
**Abdeckung** gegen **Genauigkeit**.

**Quellen.** El-Yaniv/Wiener 2010 **[V]** (Abschn. 1 und 10; Chow 1957/1970 **[Z]**
über sie): bei bekannter Verteilung ist die optimale Ablehnung
*mehrdeutigkeitsbasiert*: abgelehnt wird, wenn keine der A-posteriori-
Wahrscheinlichkeiten deutlich vorn liegt; Chow zeigte, dass die
Ablehnungskosten d die Fehlerquote nach oben begrenzen; ist die A-posteriori
nur *geschätzt*, ist Chows Regel nicht mehr optimal (Fumera u. a. 2000, dort
zitiert). Die Arbeit selbst behandelt rauschfreie Modelle.

**Für uns.** Das Tor ist bereits eine Ablehnung (Funde ohne Urteil werden
gezeigt, nie verworfen: ADR 19). Neu wäre, eine **zweite Ablehnung** einzuführen:
*dünne Steckbriefe* (wenige Merkmale, oder ohne Klappentext — die Datenbank hat
`portrait.with_text`) bekommen kein hartes „unter drei Sternen → zurückhalten“,
sondern „zeigen, gekennzeichnet“. Das mildert **S7** und **S8** in einem Zug und
passt zum Grundsatz des Tors („nie fallen lassen, was nicht beurteilt ist“).
**S1:** das Tor als *Abdeckung* zu formulieren („die besten k % des Bestands“,
Risiko-gegen-Abdeckung im Sinne von El-Yaniv/Wiener) macht es unabhängig von der
absoluten Skala: ein Profil mit einem Merkmal hat dann eben wenige, aber
ordentlich sortierte Treffer.

**Risiken.** Abdeckung braucht einen Vergleichsbestand (ein Fund allein hat keine
Rangstelle); Schwellen auf Rang sind gegen Bestandsdrift empfindlich.

#### F2 Untergrenzen und Bänder

**Quellen.** Wilson 1927 **[Z]**; Agresti/Coull 1998 **[A]**; Brown/Cai/DasGupta
2001 **[A]** empfehlen für kleine n das Wilson- oder das Jeffreys-Intervall und
warnen vor der Standard-(Wald-)Formel. Beispiele, eigene Rechnung nach der
Wilson-Formel (z = 1,96): 3 von 4: [0,30; 0,95]; 6 von 8: [0,41; 0,93];
5 von 5: [0,57; 1,0]; 0 von 2: [0,0; 0,66].

**Für uns.** Es geht nicht um Bewertungsanteile, sondern um *wie viel Belege
hinter einem Wert stehen*. Ein Band lässt sich nur setzen, wo eine Stichprobe
vorliegt — bei uns: die Zahl der Merkmale des Steckbriefs, die Zahl der
gestuften Merkmale, das Vorhandensein von Klappentext. Der natürliche Ort ist
**F1**: die Untergrenze entscheidet, ob ein Fund *sicher unter* der Schwelle
liegt (zurückhalten) oder *im Band* (zeigen, mit Hinweis). Eine echte
Streuung des Urteils liefert erst **X** (Mehrfachbeschreibung, 3.8).

**Voraussetzungen.** Eine Definition von „Beleglage“; keine Nutzerdaten.
**Aufwand.** Klein bis mittel. **Risiken.** Ein Band aus *gezählten
Merkmalen* ist keines im statistischen Sinn; nicht als „Konfidenzintervall“
ausgeben.

#### F3 Explorieren (ε-greedy, Thompson-Sampling, LinUCB)

**Quellen.** Li/Chu/Langford/Schapire 2010 **[V]** (LinUCB: je Arm eine
Ridge-Regression auf Kontextmerkmalen, dazu eine obere Vertrauensgrenze als
Erkundungsbonus; Auswertung an über 33 Mio. Ereignissen; 12,5 % mehr Klicks
gegenüber einem kontextfreien Bandit, der Vorteil sei bei knapperen Daten größer).
Chapelle/Li 2011 **[V]**: Thompson-Sampling mit Beta-Posterior „ist sehr
konkurrenzfähig“ und sollte zu den Standardvergleichen gehören; der
Erkundungsgrad lässt sich durch Verbreitern des Posteriors steuern.

**Für uns.** LinUCB und Thompson sind auf **Millionen Ereignisse** und viele
gleichzeitige Nutzer gebaut; die Gewinne in den Arbeiten stammen aus solchen
Datenmengen. Der Gedanke, der bleibt, ist *ein anderer*: Li u. a. werten offline
nur an **zufällig protokolliertem Verkehr** aus. Übertragen: alles, was die
Leserin je bewertet, sind Funde, die **das Tor passiert haben**. Wer das Tor
später an ihren Sternen misst, sieht nie einen Fehlalarm *hinter* dem Tor (nie
ein zu Unrecht zurückgehaltenes Buch). **Eine kleine, klar gekennzeichnete
Zufallsauswahl knapp unter dem Tor** (z. B. ein Fund pro Bericht aus dem Band der
2-Sterne-Funde) wäre das ε-greedy dieses Werkzeugs und die *einzige* Quelle
für das, was das Tor an Gutem zurückhält (eigener Vorschlag). Dass die
Leserin „lieber wenige sehr gut passende“ Vorschläge will (Gedächtnis:
Qualität vor Masse), ist ein Grund, die Auswahl klein zu halten, nicht, sie
wegzulassen.

**Aufwand.** Klein (eine Auswahl im Tor). **Risiken.** Jeder Fund unter dem Tor
kostet einen Platz im Bericht; der Nutzen zeigt sich erst mit Urteilen der Leserin.

---

### 3.7 G: Erhebung und Lernen aus wenigen Angaben

**Kurzbeschreibung.** Kritik-/Critiquing-Systeme fragen nach Abwandlungen („so,
aber weniger düster“); paarweise Vorlieben werden mit Bradley/Terry zu Gewichten
verrechnet; wenige Sterne lernen Gewichte über regularisierte logistische
Regression; bei dünnem Profil fällt ein Wert auf die Dimension zurück.

**Quellen.**

- Chen/Pu 2012 (UMUAI 22, S. 125–150) **[A]**: Critiquing-Systeme holen
  Rückmeldung zu vorgeschlagenen Dingen ein, lernen daraus das Profil genauer und
  schlagen in der nächsten Runde Besseres vor; die Arbeit ist ein Überblick über
  Oberflächen und Erzeugungsverfahren. **Für uns:** die *Schärfung* (Antippen
  gemochter Merkmale nach jedem Urteil) *ist* ein Critiquing-Kanal; die Quelle
  liefert keine Verrechnungsformel für 3–15 Beispiele.
- Bradley/Terry 1952 **[Z]**: P(i schlägt j) = e^{β_i}/(e^{β_i} + e^{β_j}).
  Braucht **Paare**; wir haben Relationen („Mag ich/Doof“), also höchstens
  15 × 2 = 30 stark abhängige Paare aus 17 Büchern (eigene Rechnung). Nicht
  sinnvoll.
- **Gelman/Jakulin/Pittau/Su 2008** **[V]**: für logistische Regression ein
  schwach informatives **Cauchy(0; 2,5)** auf standardisierten Eingaben (mittelwertfrei,
  Standardabweichung 0,5) als Vorgabe; es liefert **immer eine Antwort auch bei
  vollständiger Trennung** (bei kleinen Stichproben häufig) und bringt in
  einer Kreuzvalidierung an einer Sammlung von Datensätzen mehr als
  Gauß- und Laplace-Priors. Das Verfahren ist für „wenige Prädiktoren, mäßig
  viel Daten“ gedacht; bei 56 Familien gegen 17 Beispiele wäre es
  **stark durch den Prior bestimmt** — was hier richtig wäre, wenn der Prior
  *unsere heutigen Gewichte* wäre statt Null (eigener Vorschlag).
- **Hierarchische Priors / Rückfall auf die Dimension.** Beleg aus dem Tag Genome
  (Vig u. a. 2010 **[V]**): ein Koeffizient je Tag aus einer gemeinsamen
  Verteilung war besser als ein gemeinsamer und besser als getrennte je Tag —
  „teilweises Zusammenlegen“. Übertragen: das Gewicht einer Familie wird aus der
  Verteilung ihrer **Dimension** (Stimmung, Handlung, Figuren, Tempo, Stil)
  gezogen; eine Familie ohne eigene Belege fällt auf den Dimensionswert zurück.
  Die Übertragung auf 56 Familien × 17 Bücher ist ein Gedanke, keine Messung;
  Gelman/Hill 2007 (dort als Grundlage genannt) habe ich nicht gelesen.

**Was es tut.** **S9** (Lernen aus Urteilen mit Prior statt ohne), **S7** (Rückfall
auf die Dimension bei dünner Familie).

**Voraussetzungen.** Urteile der Leserin; ein Prior aus den heutigen
Gewichten. **Aufwand.** Mittel bis groß; erst nach Abschnitt 5, Stufe 3.
**Risiken.** Überanpassung: Sen u. a. 2009 **[V]** sahen bei
Regress-Tag genau das (Koeffizienten mit „intuitiv falschen“ Werten), sobald
ebenso viele Merkmale wie Bewertungen da waren. Das ist bei uns der
Normalzustand.

---

### 3.8 X: Mehrfachbeschreibung mitteln (eigener Vorschlag für S6)

Keine der Quellen behandelt ein Modell, das die *Merkmale* vergibt. Belegbar ist
dreierlei:

1. **Das Rauschen ist real, aber ich habe es nicht sauber messen können.** Die
   Datenbank hat für 10 Bücher **zwei** bekannte Steckbriefe (aus zwei
   verschiedenen Anweisungen, `fingerprint` 4fab… und e33b…; alles am
   24./25.09.2026). Die Überlappung der Familien (Jaccard) liegt im Mittel bei
   0,35 (Median 0,22, Spanne 0,10–0,75); auf der Ebene der 108 feinen Merkmale
   0,24. **Das mischt zwei Ursachen:** geänderte Anweisung *und* Zufall. Es ist
   also nur eine grobe Obergrenze für das reine Rauschen. Bei 5 von 15 Büchern
   mit zwei Steckbriefen hat das Modell das Buch einmal „gekannt“ und einmal
   „nicht“ (`known`). Für eine saubere Zahl braucht es dieselbe Anweisung
   zweimal.
2. **Mitteln senkt Streuung.** Wang u. a. 2023 (Self-Consistency, ICLR;
   arXiv 2203.11171) **[A]** zeigen, dass mehrere gezogene Antworten und die
   am häufigsten erreichte das Ergebnis bei Rechen- und Schlussfolgerungs-
   aufgaben verbessern; das ist ein *anderer* Aufgabentyp (eine Antwort, keine
   Merkmalsliste). Es ist ein Hinweis, kein Beleg für unseren Fall.
3. **Elementare Statistik:** die Streuung eines Mittelwerts von n unabhängigen
   Messungen sinkt mit 1/√n; ob die Wiederholungen des Modells unabhängig sind,
   ist offen.

**Vorschlag.** Zuerst **messen** (nicht ändern): ≤ 10 bereits beschriebene Bücher
mit unveränderter Anweisung 2–3 Mal neu beschreiben lassen (der Portrayer nimmt
bis zu acht Bücher je Aufruf, #66; das sind wenige Aufrufe), dann Jaccard je
Buch und die Streuung des `share` bei festem Profil auswerten. Erst wenn die
Streuung Sternstufen kippt, lohnt Mitteln (Merkmal gilt bei ≥ 2 von 3
Beschreibungen; Gewicht = Anteil). **Sparsam** (Gedächtnis: Livelaeufe und
Messungen klein halten). **Aufwand:** klein für die Messung, groß für ein
Dauerverfahren (Kosten × 2–3 je Fund).

---

### 3.9 H: Was ein hartes Tor an Überraschendem kostet

**Quellen.** Lops u. a. 2011 (§3.2.2 und §3.4.2 **[V]**): inhaltsbasierte Systeme
haben **keine eigene Methode, Unerwartetes zu finden**; wer nur Bücher wie die
gelesenen liest, bekommt nur solche. Unterschieden werden *Neuheit* (unbekannt)
und *Serendipität* (unbekannt **und** überraschend gut). Kaminskas/Bridge 2016
(ACM TiiS 7(1), Art. 2) **[A]**: Überblick und empirische Analyse; im Abstract:
Diversität nach Bewertungen korreliert positiv mit Neuheit, Neuheit positiv mit
Abdeckung. Mehr habe ich nicht gelesen.

**Für uns.** Das Tor kostet Serendipität, **und das ist gewollt** („Qualität vor
Masse“; das Schema: „ein leerer Stapel ist ein gutes Ergebnis“). Die Literatur
liefert hier keinen Wert, nur die Einsicht, dass Ähnlichkeit *nur* gegen die
Vergangenheit rechnet. Die Kostenrechnung ist die Auswahl aus 3.6/F3: eine kleine,
gekennzeichnete Menge knapp unter dem Tor.

---

## 4. Was in unserem Fall nicht geht oder sich nicht lohnt

- **Matrixfaktorisierung und Kollaboration.** Eine Leserin, 15 „Mag ich“. Lops
  u. a. 2011 stellen den Ansatz der *inhaltsbasierten* Systeme ausdrücklich
  dagegen, dass er ohne andere Nutzer auskommt; Rashid u. a. 2002 rechnen
  Erhebung für Kollaboration und brauchen viele Nutzer.
- **Tag Genome selbst lernen.** 50.203 Bewertungen von 676 Nutzern bei
  Vig u. a. — mehr als das Tausendfache unserer Daten; wir *haben* die Relevanz als Stufe
  vom Modell.
- **Regress-Tag/Per-Buch-Regression.** Überanpasst bei wenig Daten (Sen u. a.
  2009).
- **LinUCB, Thompson-Sampling als Steuerung.** Gebaut für Millionen Ereignisse
  (Li u. a.: 33 Mio.); bei einigen Dutzend Urteilen wird der Erkundungsbonus
  zum Rauschen. Nur der Gedanke der Zufallsauswahl bleibt (3.6/F3).
- **Kalibrierung (Platt, isotonisch).** Erst ab hunderten Urteilen (3.3/C4).
- **Bradley/Terry und Paarvergleiche.** Wir haben keine Paare (3.7).
- **Nutzenerhebung nach Keeney/Raiffa.** Die Leserin wird nicht zu Facetten
  befragt (Glossar); eine Elicitation gegen diesen Grundsatz wäre ein anderes
  Produkt.
- **Naive Bayes auf Klappentext-Wörtern (LIBRA).** Die Steckbriefe sind das
  Ergebnis genau dieser Verdichtung; ein zweiter Weg über den Rohtext hebelte ADR
  33 („der Code urteilt aus dem Steckbrief“).
- **k-NN als alleiniges Urteil** (Pazzani/Billsus 1997).
- **Elimination durch Aspekte als Wahlmodell.** Es braucht beobachtete
  *Entscheidungen*; wir haben Relationen. Als Gedanke (konjunktiv, Reihenfolge nach
  Gewicht) ist es schon in Facette/Gegengewicht enthalten.

---

## 5. Vorschläge in Reihenfolge

**Grundsatz:** klein und ohne Modellaufruf zuerst, jeder Schritt einzeln
messbar, keiner ändert die Bedeutung eines Sterns ohne Gegenprobe.

### Stufe 0: das Messgerüst (vor jeder Änderung)

Nach meinem Blick in `data/snapshots.db` (25.09.2026): 87 Bücher mit bekanntem
Steckbrief, 15 aktive Beziehungen `liked` („Mag ich“) und 2 `disliked` („Doof“),
2 Sterne mit Herkunft `reader`, 7 mit `onleihe_readers`. Woher jede
`liked`/`disliked`-Zeile stammt (Erstaufnahme oder Klick), zeigt die Tabelle
nicht; ich habe es nicht nachgesehen. `owned.yaml` scheidet aus (Sterne sind
Maschinenurteile, Gedächtnisnotiz; `ratings.py` rechnet nur `BY_READER` zu den
menschlichen Urteilen).

1. **Synthetische Invarianten** (keine Leserin, kein Modell): (a) *Profilgrößen-
   Reihe:* Profile mit 1, 3, 5, 10, 20 gemochten Merkmalen gegen die 87
   gespeicherten Steckbriefe; gemessen wird der Anteil ≥ 3 Sterne. Das macht S1
   sichtbar (im Schema stehen die Anteile „27 % / 5 %“ für ein Profil). (b)
   *Monotonie:* ein weiterer Treffer senkt das Urteil nie; ein Gegengewicht
   hebt es nie. (c) *Längenprobe:* gleiche Treffer bei 4 und 8 Merkmalen. Das sind
   Regressionstests, keine Wahrheit.
2. **Leave-one-out an den 17 Büchern:** Profil aus den übrigen 16 bilden, das
   ausgelassene beurteilen; Kennzahl: Rang des Gemochten unter den 87 (oder
   AUC gemochte gegen enttäuschende). Bei 17 Büchern sind die Unterschiede
   **nicht signifikant**; das taugt, um *Umkippen* zu sehen (ein bisher
   gemochtes Buch fällt unters Tor), nicht als Beweis von Verbesserung.
3. **Wiederholungsmessung für S6** (3.8): dieselbe Anweisung, ≤ 10 Bücher, 2–3
   Mal — der einzige Punkt, an dem ein Modell gefragt wird, und nur klein.

### Stufe 1: ohne Modell, kleine Eingriffe (jeder für sich testbar)

| # | Eingriff | Schwäche | Quelle | Messung |
|---|---|---|---|---|
| 1 | Vergleich der Schwellen mit Toleranz (`share ≥ ab − 1e-9`): die Gleitkommafalle | S8 | eigene Rechnung (Anhang) | ein Test: verstärktes einzelnes Merkmal = 2 Sterne |
| 2 | Tor als **Abdeckung** ergänzen (Schwelle *oder* obere k % des Bestands), Reihenfolge nach `share` | S1 | El-Yaniv/Wiener 2010; Chow 1970 | Profilgrößen-Reihe (Stufe 0, Nr. 1a): Anteil unabhängig von der Profilgröße |
| 3 | **IDF-Faktor** je Familie aus den Steckbriefen (geglättet), als Multiplikator auf `f_i` | S2 | Spärck Jones 1972; Robertson 2004 | Rang in der LOO-Probe; Verteilung der Sterne |
| 4 | **Doppelzählen** Facette/Mitglieder klären (Mitglieder einer getroffenen Facette nicht noch einmal) | S3, Annahme des Noisy-OR | Onisko u. a. 2001 (Synergie-Bedingung) | LOO-Probe; Wirkung auf die 15 „Mag ich“ |
| 5 | **Gewicht im Buch** als Stufe: `f_i × g(Gewicht)`, g(prägend) = 1, g(deutlich) < 1; „am Rand“ kaum belegt (3 %) | S5 | BM25 (Robertson/Zaragoza 2009); Sen u. a. 2009 | zuerst Stabilität prüfen (Stufe 0, Nr. 3) |
| 6 | **Dünn-Kennzeichnung** (F1/F2): wenige Merkmale oder kein Klappentext → zeigen, gekennzeichnet | S7, S8 | Chow 1970; Wilson 1927 (als Vorbild für ein Band) | Anteil der gekennzeichneten Funde; gibt es überhaupt viele? |

*Die Zahlen für g(·) sind an keiner Quelle geeicht.* Sie sind Startwerte wie
`merkmal_einzeln: 0.1` (Schema: „Startwerte … werden gelernt statt gesetzt“).
Kein Wert sollte ohne Stufe 0 übernommen werden.

### Stufe 2: ohne Modell, als Schattenwert

7. **Naive-Bayes-Log-Odds** (C1) mit Prior aus den heutigen Gewichten
   (Pazzani/Billsus 1997) — nur *berechnen und protokollieren*, nicht anzeigen;
   prüfen, ob Rang und Sterne stark abweichen. Wo sie abweichen, lohnt der
   Blick auf die Bücher.
8. **Nachbarwert** (E) als *Belegauswahl* für die Begründung, nicht als Urteil.
9. **Ein Abzug je enttäuschendes Buch** (statt je Gegengewicht), kumulativ über
   *verschiedene* Bücher (S4): erst, wenn es mehr als 2 enttäuschende Bücher gibt.

### Stufe 3: braucht Urteile der Leserin

10. **Zufallsauswahl knapp unter dem Tor** (F3): der einzige Weg zu
    Urteilen über *zurückgehaltene* Funde. Klein halten (ein Fund je Bericht).
11. **Lernen mit Prior** (G2/G3/C3): Gewichte um den heutigen Wert *verschieben*,
    nicht neu schätzen; eine bis zwei globale Größen zuerst (z. B. Schwelle und
    Abstand), Gewichte je Familie erst weit später; Rückfall auf die Dimension
    (G3). **Wann?** Die Literatur gibt keinen Wert für „genug Urteile“; Kalibrierung
    verlangt hunderte (Niculescu-Mizil/Caruana 2005), Regularisierte Regression
    liefert auch mit wenigen Daten *irgendeine* Antwort (Gelman u. a. 2008), aber
    sie wird vom Prior bestimmt. Meine Einschätzung (kein Beleg): erst wenn die
    Leserin mehrere Dutzend Sterne über **zurückgehaltene und gezeigte**
    Funde gegeben hat.
12. **Mehrfachbeschreibung mitteln** (X): nur, wenn die Wiederholungsmessung
    (Stufe 0, Nr. 3) die Streuung als stufenkippend zeigt.

### Nicht tun (jetzt)

Kalibrierung, LinUCB, Regress-Tag, Nutzenerhebung, Matrixfaktorisierung.

---

### 5.1 Beobachtung am Rand: die Gleitkommafalle (eigene Rechnung)

`share = 1 − Π(1 − f_i)`, mit einem verstärkten Merkmal `f = 0,1 + 0,1 = 0,2`:
`1 − (1 − 0,2) = 0,19999999999999996`, und `share ≥ 0,2` ist falsch. Ein Profil,
bei dem ein Buch nur ein einziges verstärktes gemochtes Merkmal trägt, ergibt
deshalb **1** statt 2 Sterne. Ich habe die Arithmetik in Python nachgerechnet und
den Code gelesen (`fit()` vergleicht mit `share >= ab`, `Weights.liked` addiert
`single + boost`); die Anwendung selbst habe ich **nicht** laufen lassen.

Für das Tor bei 0,4 folgt daraus bei den Fällen, die ich nachgerechnet habe,
nichts: fünf Treffer à 0,1 ergeben 0,40951 (drüber), ein verstärktes Erzählmuster
`1 − (1 − 0,4)` ergibt 0,4 (`True`), und `0,3 + 0,1 == 0,4` ist in Gleitkomma
wahr. Andere Kombinationen an einer Schwelle (0,6; 0,8) habe ich nicht
durchgespielt. Die Lehre für S8 ist allgemein: eine Schwelle, die auf einem
berechneten Wert liegt, braucht eine Toleranz.

---

## 6. Quellenverzeichnis

Reihenfolge nach Verwendung; jede Quelle mit Lesestand.

**A. Vektorraum, Rocchio, IDF, Kosinus, BM25**

- Manning, C. D., Raghavan, P., Schütze, H. (2008): *Introduction to Information
  Retrieval*, Cambridge University Press; Online-Ausgabe: §9.1.1 (Rocchio),
  §6.2.1 (IDF), §6.3.1 (Skalarprodukt, Kosinus), §11.4.3 (BM25).
  https://nlp.stanford.edu/IR-book/ **[V]** (vier Abschnitte)
- Rocchio, J. J. (1971): Relevance feedback in information retrieval. In:
  Salton, G. (Hg.): *The SMART Retrieval System*, Prentice-Hall, S. 313–323.
  **[Z]** (über Lops u. a. 2011 und Manning u. a. 2008)
- Salton, G., Buckley, C. (1990): Improving retrieval performance by relevance
  feedback. *JASIS* 41(4), 288–297.
  http://www.cs.ucr.edu/~vagelis/classes/CS172/publications/jasistSalton1990.pdf **[V]**
- Spärck Jones, K. (1972): A statistical interpretation of term specificity and
  its application in retrieval. *Journal of Documentation* 28(1), 11–21. **[Z]**
  (über Robertson 2004)
- Robertson, S. (2004): Understanding inverse document frequency: on
  theoretical arguments for IDF. *Journal of Documentation* 60(5), 503–520.
  https://www.staff.city.ac.uk/~sbrp622/idfpapers/Robertson_idf_JDoc.pdf **[V]**
  (Einleitung, §1–2)
- Robertson, S., Zaragoza, H. (2009): The Probabilistic Relevance Framework:
  BM25 and Beyond. *Foundations and Trends in Information Retrieval* 3(4),
  333–389. DOI 10.1561/1500000019 **[V]** (§3.4–3.5; Bandangabe aus dem Dokument
  selbst)
- Lops, P., de Gemmis, M., Semeraro, G. (2011): Content-based Recommender
  Systems: State of the Art and Trends. In: Ricci u. a. (Hg.): *Recommender
  Systems Handbook*, Springer, Kap. 3, S. 73–105.
  http://facweb.cs.depaul.edu/mobasher/classes/ect584/papers/contentbasedrs.pdf **[V]**

**B. Tag-basierte Profile**

- Sen, S., Vig, J., Riedl, J. (2009): Tagommenders: connecting users to items
  through tags. *WWW ’09*.
  https://files.grouplens.org/papers/tagommenders_numbered.pdf **[V]**
- Vig, J., Sen, S., Riedl, J. (2009): Tagsplanations: explaining recommendations
  using tags. *IUI ’09*, DOI 10.1145/1502650.1502661.
  https://files.grouplens.org/papers/vig-iui2009-tagsplanations.pdf **[V]**
- Vig, J., Sen, S., Riedl, J. (2012): The Tag Genome: encoding community
  knowledge to support novel interaction. *ACM TiiS* 2(3), Art. 13.
  DOI 10.1145/2362394.2362395 **[A]**
- Vig, J., Sen, S., Riedl, J. (2010): Computing the Tag Genome. Technical
  Report, University of Minnesota. https://files.grouplens.org/papers/genome.pdf
  **[V]** (Vorstufe der TiiS-Arbeit; die Zahlen der Tabelle stammen aus dieser
  Fassung, nicht aus der TiiS-Fassung)

**C. Wahrscheinlichkeitsmodelle**

- Mooney, R. J., Roy, L. (2000): Content-based book recommending using learning
  for text categorization. *ACM DL ’00*; arXiv cs/9902011 (1999).
  https://arxiv.org/pdf/cs/9902011 **[V]**
- Pazzani, M., Billsus, D. (1997): Learning and revising user profiles: the
  identification of interesting web sites. *Machine Learning* 27, 313–331.
  https://ics.uci.edu/~pazzani/Publications/SW-MLJ.pdf **[V]**
- Domingos, P., Pazzani, M. (1997): On the optimality of the simple Bayesian
  classifier under zero-one loss. *Machine Learning* 29, 103–130. **[A]**
- Pearl, J. (1988): *Probabilistic Reasoning in Intelligent Systems*, Morgan
  Kaufmann. **[Z]** (über Onisko u. a. 2001)
- Onisko, A., Druzdzel, M. J., Wasyluk, H. (2001): Learning Bayesian network
  parameters from small data sets: application of Noisy-OR gates. *International
  Journal of Approximate Reasoning* 27(2), 165–182.
  https://sites.pitt.edu/~druzdzel/psfiles/ijar01.pdf **[V]**
- Díez, F. J. (1993): Parameter adjustment in Bayes networks. The generalized
  noisy OR-gate. *UAI ’93*. https://arxiv.org/pdf/1303.1465 **[V]** (Abstract und
  Kopf; nicht durchgearbeitet)
- Henrion, M. (1989): Some practical issues in constructing belief networks.
  **[Z]** (über Onisko u. a. 2001)
- ECSQARU 2011, Springer LNCS, Kap. 11: „Using the Noisy-OR Model Can Be Harmful
  … But It Often Is Not“. https://link.springer.com/chapter/10.1007/978-3-642-22152-1_11
  **[Z]** (nur der Titel aus einer Trefferliste; Autorenangabe nicht geprüft;
  Volltext nicht abrufbar)
- Platt, J. (1999): Probabilistic outputs for support vector machines and
  comparisons to regularized likelihood methods. In: *Advances in Large Margin
  Classifiers*. **[Z]** (über Niculescu-Mizil/Caruana 2005)
- Zadrozny, B., Elkan, C. (2001/2002): Kalibrierung von Naive Bayes, SVM und
  Entscheidungsbäumen mit isotonischer Regression. **[Z]** (über
  Niculescu-Mizil/Caruana 2005; Titel und Ort nicht geprüft)
- Niculescu-Mizil, A., Caruana, R. (2005): Predicting good probabilities with
  supervised learning. *ICML ’05*, 625–632.
  https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf **[V]**
- Agresti, A., Coull, B. A. (1998): Approximate is better than „exact“ for
  interval estimation of binomial proportions. *The American Statistician*
  52(2), 119–126. **[A]** (über einen Suchauszug)

**D. Nutzenmodelle, nichtkompensatorisch**

- Keeney, R. L., Raiffa, H. (1976): *Decisions with Multiple Objectives*, Wiley.
  **[Z]**
- Tversky, A. (1972): Elimination by aspects: a theory of choice.
  *Psychological Review* 79(4), 281–299. **[A]** (Suchauszug)
- Einhorn, H. J. (1970): The use of nonlinear, noncompensatory models in
  decision making. *Psychological Bulletin* 73(3), 221–230. **[Z]**
- Lin, C., Shen, X., Chen, S., Zhu, M., Xiao, Y. (2019): Non-compensatory
  psychological models for recommender systems. *AAAI 2019*. **[A]**
- Dieckmann, A., Dippold, K., Dietrich, H. (2009): Compensatory versus
  noncompensatory models for predicting consumer preferences. *Judgment and
  Decision Making* 4(3). **[A]**

**E. Fall-/Nachbarschaftsverfahren, Kaltstart**

- Wang, X., Fang, H., Zhai, C. (2008): A study of methods for negative
  relevance feedback. *SIGIR ’08*, 219–226.
  https://www.eecis.udel.edu/~hfang/pubs/sigir08.pdf **[V]**
- Schein, A. I., Popescul, A., Ungar, L. H., Pennock, D. M. (2002): Methods and
  metrics for cold-start recommendations. *SIGIR ’02*, 253–260.
  DOI 10.1145/564376.564421 **[A]**
- Rashid, A. M., Albert, I., Cosley, D., Lam, S. K., McNee, S. M., Konstan, J. A.,
  Riedl, J. (2002): Getting to know you: learning new user preferences in
  recommender systems. *IUI ’02*.
  https://cs.fit.edu/~pkc/apweb/related/rashid-iui02.pdf **[V]**

**F. Unsicherheit, Zurückhalten, Erkunden**

- Chow, C. K. (1970): On optimum recognition error and reject tradeoff. *IEEE
  Transactions on Information Theory* 16(1), 41–46. **[Z]**
- El-Yaniv, R., Wiener, Y. (2010): On the foundations of noise-free selective
  classification. *JMLR* 11, 1605–1641.
  https://www.jmlr.org/papers/volume11/el-yaniv10a/el-yaniv10a.pdf **[V]**
- Wilson, E. B. (1927): Probable inference, the law of succession, and
  statistical inference. *JASA* 22(158), 209–212. **[Z]**
- Brown, L. D., Cai, T. T., DasGupta, A. (2001): Interval estimation for a
  binomial proportion. *Statistical Science* 16(2), 101–133. **[A]**
- Li, L., Chu, W., Langford, J., Schapire, R. E. (2010): A contextual-bandit
  approach to personalized news article recommendation. *WWW ’10*.
  https://arxiv.org/pdf/1003.0146 **[V]**
- Chapelle, O., Li, L. (2011): An empirical evaluation of Thompson sampling.
  *NIPS 2011*.
  https://papers.nips.cc/paper_files/paper/2011/file/e53a0a2978c28872a4505bdb51db06dc-Paper.pdf
  **[V]**
- Wang, X., Wei, J., Schuurmans, D., Le, Q., Chi, E., Narang, S., Chowdhery, A.,
  Zhou, D. (2023): Self-consistency improves chain of thought reasoning in
  language models. *ICLR 2023*, arXiv 2203.11171. **[A]**

**G. Erhebung, Lernen aus wenigen Angaben**

- Chen, L., Pu, P. (2012): Critiquing-based recommenders: survey and emerging
  trends. *User Modeling and User-Adapted Interaction* 22, 125–150.
  DOI 10.1007/s11257-011-9108-6 **[A]**
- Bradley, R. A., Terry, M. E. (1952): Rank analysis of incomplete block
  designs: I. The method of paired comparisons. *Biometrika* 39(3/4), 324–345.
  **[Z]**
- Gelman, A., Jakulin, A., Pittau, M. G., Su, Y.-S. (2008): A weakly informative
  default prior distribution for logistic and other regression models. *The
  Annals of Applied Statistics* 2(4), 1360–1383.
  https://sites.stat.columbia.edu/gelman/research/published/priors11.pdf **[V]**
- Gelman, A., Hill, J. (2007): *Data Analysis Using Regression and
  Multilevel/Hierarchical Models*, Cambridge University Press. **[Z]** (über
  Vig u. a. 2010)

**H. Diversität**

- Kaminskas, M., Bridge, D. (2016): Diversity, serendipity, novelty, and
  coverage: a survey and empirical analysis of beyond-accuracy objectives in
  recommender systems. *ACM TiiS* 7(1), Art. 2. DOI 10.1145/2926720 **[A]**
  (Abstract)

**Eigene Quellen im Repository**

- `src/ebook_watchlist/facets.py` (`fit`, `Weights`), `docs/bewertungsschema.yaml`,
  `CONTEXT.md` (Fit, Facet, Counterweight, Portrait, Strength), ADR 19 und 33.
- `data/snapshots.db`, nur lesend (Stand 25.09.2026): `portrait` (107 Zeilen,
  92 Subjekte, 97 bekannt), `book_relation` (`liked` 15, `disliked` 2 aktiv),
  `rating` (`reader` 2, `onleihe_readers` 7). Alle Zählungen in diesem Dokument
  daraus; keine Quelle im Netz und kein Modell wurden dafür angefragt.

---

## Nachbemerkung: was ich nicht bestätigen konnte

- **Rocchio 1971, Spärck Jones 1972, Pearl 1988, Keeney/Raiffa 1976, Chow 1970,
  Platt 1999, Wilson 1927, Bradley/Terry 1952, Einhorn 1970** sind Primärquellen
  im Sinne der Aufgabe, aber hinter Bezahlschranken oder als Buch; ich habe sie
  nicht selbst geöffnet. Was ich über sie schreibe, steht so in den Quellen, die
  ich gelesen habe, und ist als **[Z]** gekennzeichnet.
- **Die Aufgabenstellung nannte „Score = Σ Präferenz × Relevanz“ für
  Tagsplanations.** Die Summenformel steht in **Tagommenders** (Sen/Vig/Riedl
  2009); Tagsplanations zeigt Relevanz und Vorliebe getrennt und rechnet eine
  Vorliebe (gewichteter Mittelwert) und eine Relevanz (Pearson), aber keine
  Summe. Das habe ich so belegt gefunden.
- **Das Tag Genome (TiiS 2012)** habe ich nicht im Volltext bekommen (ACM
  gesperrt); die Aussagen zu Relevanz 0–1 und zum hierarchischen Modell stützen
  sich auf den Technical Report von 2010.
- **Zahlen zu „Rocchio 1 : 5 zu wenig“** sind die des Schemas (von Hand an den
  Büchern der Leserin gefunden); ich habe sie nicht nachgeprüft.
- **„Über 70 % der Menschen nutzen nichtkompensatorische Regeln“** steht im
  Abstract von Lin u. a. 2019; die Herkunft der Zahl dort habe ich nicht
  geprüft.
- **Schwäche 6:** eine saubere Messung der Streuung *derselben* Anweisung
  liegt nicht vor; die 0,35 (Familien-Jaccard) mischt Anweisungswechsel und Zufall.
