# 33. Das Leseprofil entsteht aus Büchern, und der Code urteilt

Das Leseprofil beschreibt nicht mehr in Prosa, was eine Leserin mag, sondern
hält fest, was ihre Bücher gemeinsam haben. Ein Modell sieht jedes Buch genau
einmal; das Urteil rechnet der Code. Die Einzelheiten stehen in #43 und #44.

## Kontext

Das Leseprofil bis Fassung 4 war eine Repo-Datei mit gewichteten Achsen und
Gegenanzeigen, geändert nur über den Skill `leseprofil-schaerfen`, gelesen von
einem Modell, das jedes Buch gegen den ganzen Text hielt (ADR 17, ADR 21). Fünf
Befunde sprachen gegen dieses Modell:

- **Es kannte nur eine Art zu passen.** Die Achsen wurden gesammelt, bis ein
  Buch passend aussah. *Das Rosie-Projekt* und *Otherland*, beide geliebt,
  fielen dabei durch, weil jedes eine Sache ganz tut und nicht alle ein
  bisschen (#43).
- **Es mischte Genre mit Geschmack.** „Katz und Maus" stand als Achse im
  Profil. NoveList führt es als Erzählmuster des Thrillers, getrennt vom
  Appeal.
- **Das Modell widersprach sich.** Null Sterne bei getroffenen Achsen (#42)
  musste eine Nachfrage abfangen.
- **Jede Profiländerung war teuer.** Eine neue Fassung entwertete alle
  Maschinenurteile; zuletzt 136, rund vier Läufe über `claude -p`.
- **Der Detektor hatte nie Daten.** Die Probe „gemocht, aber schlecht
  bewertet" aus ADR 17 setzt voraus, dass gemochte Bücher beurteilt werden.
  Von 14 Regalbüchern war keines maschinell beurteilt.

ADR 21 Punkt 5 hatte einen Ableitungsschritt ausdrücklich abgelehnt, weil
„niemand ein Problem beobachtet hat". Die Befunde oben sind diese
Beobachtung. Dazu kommen zwei Anforderungen der Leserin: Das Profil soll in
der Oberfläche entstehen und sich dort ändern lassen, auch für neue
Leser:innen (#18), und das Werkzeug soll reproduzierbar sein.

Ein Versuch am 23.09.2026 (#44) hat das neue Modell von Hand durchgespielt: vier
geliebte Bücher, ein enttäuschendes, eine Probe gegen die übrigen. Facetten,
die je Buch abgefragt wurden, trafen **0 von 5** weiteren gemochten Büchern
voll. Über alle Bücher hinweg abgeleitet waren es **3 von 5**, und kein
enttäuschendes Buch wurde mehr getroffen.

## Entscheidung

**1. Das Leseprofil besteht aus Facetten, Gegengewichten, Autor:innen und
Genres.** Eine Facette ist eine benannte Art, wie ein Buch zu dieser Leserin
passt, und besteht aus mindestens zwei Merkmalsfamilien, die ihre geliebten
Bücher gemeinsam tragen. Gegengewichte kommen aus enttäuschenden Büchern.
**Gegenanzeigen gibt es nicht mehr**: Ein Gegengewicht zieht ein Buch nach
unten, schließt es aber nie aus.

**2. Das Vokabular ist fest und liegt im Repo.** `docs/merkmale.yaml`: 72
Merkmale auf Grundlage von NoveLists Appeal-Begriffen, fünf Dimensionen,
darüber 44 Merkmalsfamilien als Arbeitsstand. Die Gegenteil-Probe entscheidet,
was hineindarf. Erzählmuster werden genauso behandelt; ihr Vokabular ist noch
offen. Geändert wird auf Beleg: wenn ein Buch zeigt, dass etwas fehlt oder
falsch schneidet.

**3. Ein Modell sieht jedes Buch genau einmal, unabhängig von jeder Leserin.**
Es identifiziert das Buch, vergibt Merkmale mit Beleg, Erzählmuster und Genre
und schreibt den Pitch. Das Ergebnis wird mit dem Buch gespeichert: Dasselbe
Buch trägt immer dieselben Merkmale.

**4. Der Code urteilt.** Jede Facette ist ein eigener Grund, das Buch zu mögen:
ganz getroffen wiegt sie 0,8, teilweise 0,1, verbunden als Noisy-OR. Das
stärkste Gegengewicht zieht ein Fünftel ab. Die Prozentzahl ordnet, die Sterne
fassen zusammen; null Sterne heißt, nichts passt und etwas spricht dagegen. Die
Begründung setzt sich aus vorhandenen Daten zusammen: welche Facette, der Satz
zum Merkmal, warum es für diese Leserin zählt. Die Werte sind Startwerte und
stehen maschinenlesbar im Bewertungsschema; später lernt das Werkzeug sie aus
den eigenen Urteilen der Leserin.

**5. Das Leseprofil liegt in der Datenbank**, je Leserin (`profile_slug`),
append-only: eine Zeile je Fassung, mit dem Anlass, der sie ausgelöst hat.
`docs/bewertungsschema.yaml` und `docs/merkmale.yaml` bleiben Repo-Dateien:
Sie nennen keinen Geschmack und gelten für jede Leserin gleich.

**6. Es entsteht in der Oberfläche, in der Erstaufnahme.** Die Leserin nennt
drei bis fünf geliebte und bis zu fünf enttäuschende Bücher. Das Werkzeug fragt
nur geschlossen: Es sammelt die Familien aller Bücher auf einmal, zeigt, was
mehrere tragen, und die Leserin bestätigt. Jedes geliebte Buch muss am Ende in
einer Facette stecken. Wie stark eine Facette belegt ist, zeigt eine Skala.

**7. Es ändert sich beim Nachschärfen**, bei jedem Buch, das die Leserin *Mag
ich* oder *Doof* nennt. Bestärken geht still, alles Neue wird gefragt, und auf
der Profilseite lässt sich jederzeit alles abwählen. Die Beweislast aus ADR 17
ist keine Schranke mehr; ihre Asymmetrie lebt als „Bestärken ist billig,
Ändern fragt nach" fort.

**8. Ohne Profil wird nicht geurteilt.** Keine Sterne, kein Vorfilter,
Vorschläge unsortiert, und kein Ersatzprofil. Ein Buch, dessen Merkmale fehlen,
weil das Modell nicht erreichbar war oder es nicht kennt, wird nicht aussortiert
(ADR 7).

## Abgelöst

- **ADR 17**: das Leseprofil als Repo-Datei, geändert nur über
  `leseprofil-schaerfen`; die Gegenanzeigen; die dreistufige Beweislast.
- **ADR 21**: Punkt 1 (das Leseprofil als versionierte Repo-Datei) und Punkt 5
  (kein Ableitungsschritt, das Profil als Text an das Modell). Die Trennung von
  Leseprofil und Bewertungsschema bleibt.
- **ADR 32**: die Zeile `docs/leseprofil.yaml` der Tabelle. Einstellungen und
  Saatgut bleiben, wie sie sind.

ADR 19 bleibt: Das Tor lässt ab drei Sternen durch, jetzt mit Sternen aus dem
Code.

## Konsequenzen

- **Eine Profiländerung kostet keinen Modellaufruf.** Alle Urteile werden
  sofort neu berechnet; Nachbewerten gibt es nicht mehr.
- **Es wird bei null angefangen.** Das Leseprofil Fassung 4 und die 136
  Maschinenurteile dagegen gelten nicht weiter.
- **Die Güte hängt an den Merkmalen.** Im Versuch vergab das Modell *lebendiger
  Schauplatz* an 7 von 13 Büchern, kannte *Cry Baby* unter dem deutschen Titel
  nicht und verriet einmal ein Ende. Dagegen stehen: das Identifizieren vor dem
  Vergeben, das Sortieren häufiger Familien an einem neutralen Bestand und die
  Gegenteil-Probe. Ein ganzheitliches Urteil, das Zwischentöne abwägt, gibt es
  nicht mehr.
- **Die Bewerter vergeben Merkmale statt Sterne.** `ModelRater` und
  `ClaudeCodeRater` behalten den Weg zum Modell, nicht ihre Aufgabe. `star_contradiction` und
  `with_settled_stars` (#42) entfallen; `with_better_pitch` (#29) wandert ins
  Vergeben. Die Skills `buch-bewerten` und `leseprofil-schaerfen` haben
  ausgedient.
- **Das Bewertungsschema wird umgeschrieben**: Sternetabelle, Pitch-Regeln
  (einmal je Buch, ohne Ton passend zu den Sternen) und die Bedeutung von
  `confidence`, die jetzt aus dem Beleg der Merkmale und der Stärke der Facette
  folgt.
- **Die eigenen Sterne der Leserin** schärfen nicht; sie sind die Daten, aus
  denen die Gewichte später gelernt werden.
- **Offen**: wie die Übereinstimmung angezeigt wird. Netflix hat seine Sterne
  abgeschafft, weil sie für ein
  Qualitätsurteil gehalten wurden; Buchfink zeigt Maschinensterne neben den
  Leser-Sternen der Onleihe.

> **Nachtrag: Gegengewichte sind Bündel.** Die Leserin hat *Herr der Ringe*
> verloren als klassische Fantasy auf einer Heldenreise; *Otherland*, eine
> Heldenreise in der Science Fiction, liebt sie. Ein Gegengewicht aus einer
> einzelnen Familie hätte *Otherland* getroffen. Deshalb sind Gegengewichte wie
> Facetten Bündel, die nur zählen, wenn ein Buch alle Teile trägt, und anders
> als Facetten dürfen sie ein **Genre** enthalten: „klassische Fantasy ·
> Heldenreise". Im Gegengewicht grenzt ein Genre nur ein, was bestraft wird;
> in einer Facette würde es eingrenzen, was gefunden wird, und dorthin kommt
> es erst, wenn ein Buch es verlangt. Das Genre muss dafür fein genug sein
> (*High Fantasy*, nicht nur *Fantasy*); sonst träfe ein Gegengewicht auch
> Grimdark wie *Kriegsklingen*.

> **Nachtrag: das Vokabular der Erzählmuster.** Zwei Ebenen wie bei den
> Merkmalen: NoveLists Themes, je Genre, als feine Ebene, die das Modell
> vergibt; Tobias' 20 Grundhandlungen als Familien, über die gefragt und
> verglichen wird. Statt der Gegenteil-Probe gilt für Erzählmuster die
> Meiden-Probe: Gibt es Leser:innen, die genau dieses Muster meiden? Die
> Abwägung der Quellen steht in `vocabulary/story-pattern-vocabularies.md` (nicht in Git, #59);
> ungeklärt ist die Lizenz der NoveList-Bezeichnungen.

> **Nachtrag vom 24.09.2026: Facetten bildet das Werkzeug selbst, gefragt wird
> nur nach einzelnen Merkmalen.** Punkt 6 ließ die Leserin Facetten bestätigen;
> im Test verstand niemand, was "gezeichnete Figur · Rätsel" heißt, ohne die
> Merkmale einzeln zu kennen, und die Gruppierung nach Buch ("Weil du A und B
> mochtest") las sich wie ein Vergleich der Bücher, nicht wie eine Auskunft
> über Geschmack. Die Erstaufnahme zeigt jetzt **alle** Merkmale und
> Erzählmuster der geliebten Bücher als eine gerankte Liste, ohne Gruppierung.
> Die Leserin tippt an, was für sie zählt, und verstärkt davon bis zu
> `MOST_BOOSTED` (drei). Facetten — mindestens zwei angetippte Merkmale, die
> mehrere geliebte Bücher gemeinsam tragen — bildet der Code aus den
> angetippten Merkmalen **automatisch und unsichtbar**; die Leserin bestätigt
> keine Facette und wird auch nicht danach gefragt. Erzählmuster stecken nie
> in einer Facette (#63) — sie zählen immer für sich.
>
> **Ein einzelnes angetipptes Merkmal zählt schwach für sich** (#64), auch
> ohne dass es mit einem anderen geliebten Buch eine Facette bildet: 0,1,
> verstärkt 0,2. Ein Erzählmuster zählt stärker — 0,3, verstärkt 0,4 — weil der
> Versuch zeigte, dass ein gemeinsames Erzählmuster mehr über den Geschmack
> sagt als ein einzelnes Merkmal (#44). Teiltreffer einer Facette gibt es
> dafür nicht mehr: was eine Facette nur zum Teil trifft, zählt über seine
> einzelnen Merkmale, nicht über die Facette. `docs/bewertungsschema.yaml`
> trägt diese Werte jetzt als `merkmal_einzeln`, `verstaerkt_aufschlag` und
> `erzaehlmuster`; `facette_teilweise` entfällt.
>
> Nachschärfen läuft seither gleich: ein *Mag ich*-Buch zeigt seine eigenen
> Merkmale und Erzählmuster zum Antippen und Verstärken, keine Vorschläge und
> kein "passt nicht" mehr — die Facetten rechnet der Code nach jeder Änderung
> aus allen gemochten Merkmalen neu.
>
> Bildschirm 4 ("Was dich verloren hat") verlor aus demselben Grund seine
> Gruppierung nach enttäuschendem Buch: eine Familie stand einmal je Buch,
> das sie trug, und das las sich wie ein Buchvergleich. Sie zeigt jetzt,
> genau wie Bildschirm 3, eine gerankte Liste aller Merkmale und Erzählmuster
> der enttäuschenden Bücher, mit ⊘ statt ♥. Trägt eine Familie auch ein
> geliebtes Buch, steht die Nachfrage nach dem Umfang direkt in der Karte,
> sobald sie angetippt ist — ohne Verstärken, denn ein Gegengewicht hat keine
> abgestufte Stärke. Ein angetipptes Gegengewicht gilt seither für alle
> enttäuschenden Bücher, die dieselbe Familie tragen, nicht nur für eines.

> **Nachtrag vom 24.09.2026: der Lauf urteilt im Code (#48).** Vor dem Umbau
> des Tors sind fünf Fragen entschieden worden.
>
> **Ein Urteil wird gerechnet, nie gespeichert.** Tor, Stapel, Tagesbericht
> und Buchseite rufen dieselbe Stelle auf, die aus Steckbrief, Profil und
> Gewichten Prozent, Sterne und Begründung macht. Damit wirkt eine neue
> Profilfassung sofort und ohne Modellaufruf auf alles, und die alten
> Maschinenurteile (Herkunft `model`, `conversation`) werden nirgends mehr
> gelesen. Das schließt eine Verwechslung aus: ihre Fassungsnummer stammt vom
> Prosa-Profil, und das Datenbankprofil zählt selbst bei 4. Die Zeilen bleiben
> stehen (ADR 16); gelöscht werden sie mit #52. Die eigenen Sterne der Leserin
> bleiben und gehen dem Tor weiter vor.
>
> **Ein Fund bekommt seinen Steckbrief im Lauf.** Höchstens `rating_budget`
> Steckbriefe je Lauf (Voreinstellung 40), einer je Aufruf, ohne Bündeln. Was
> darüber liegt, ist unbewertet und wird gezeigt. Vorher holt der Lauf den
> vollen Klappentext: die Funde sind überwiegend Neuerscheinungen, die ein
> Modell nicht kennt, und ein Steckbrief aus dem abgeschnittenen Kachel-Text
> bliebe für immer dünn.
>
> **Das Tor hält zurück, was unter drei Sternen liegt.** Ein Fund ohne
> Urteil (kein Profil, kein Steckbrief, ein unbekanntes Buch) wird gezeigt und
> nicht aussortiert (ADR 7). Die „vermutet"-Regel entfällt: sie schützte vor
> einem Modell, das Sterne schätzt, und das Modell vergibt jetzt nur noch
> Merkmale. Ohne Schlüssel urteilt das Tor über Funde, die schon einen
> Steckbrief haben. Die Schwelle steht als Wert im Bewertungsschema. Die
> Verteilung an den sieben Büchern der Erstaufnahme und an 20 000 Zufallsbüchern
> spricht für 3: ein beliebiges Buch erreicht sie zu etwa 27 %, vier Sterne
> nur zu etwa 5 %, und mit nur einer Facette hielte 4 fast alles Neue zurück.
>
> **Gegenbeispiele zählen nur über Gegengewichte, und das Gegengewicht wiegt
> 0,35 statt 0,2.** Ein *Doof*-Buch selbst ist kein Signal; das hieße, Bücher
> zu vergleichen, und das haben wir auf Schritt 3 und 4 gerade abgeschafft.
> Gemessen: *Der Schwarm*, den die Leserin enttäuschend fand, kam mit 0,2 auf
> 47 % und damit durch das Tor. Er trägt fünf gemochte Merkmale (59 %), und das
> einzige Gegengewicht, das sie aus ihm angetippt hat, zog nur ein Fünftel ab.
> Ab etwa 0,33 fällt er unter drei Sterne; 0,35 lässt die fünf gemochten
> Bücher unberührt. Mehrere Gegengewichte werden **nicht** summiert: die fünf
> aus *Herr der Ringe* kämen aus einem Buch und zählten es fünfmal. Der Wert ist
> ein Startwert wie die anderen und wird an echten Funden nachgestellt.
>
> **Der Stapel ordnet nach Prozent**, Gleichstand nach Titel wie bisher,
> Unbewertetes am Ende, und zeigt beides (Prozent und Sterne), bis #54 die
> Anzeige entscheidet. `ebw rate` legt künftig die fehlenden Steckbriefe für
> den Stapel an, statt Sterne zu vergeben.

> **Nachtrag vom 25.09.2026: Steckbriefe werden gebündelt angefragt (#66), und
> der Weg über `claude -p` läuft schlank (#52).** Gemessen an acht echten Funden
> aus dem Stapel (Haiku): ein Steckbrief-Prompt hat rund 6500 Tokens, davon 5500
> das feste Vokabular. Über die angemeldete Installation kostete der bloße
> Aufruf zunächst 61 000 Eingabe-Tokens und 0,33 $ (Claude Codes eigene
> Anweisung, Werkzeuge, MCP-Server), 34 Sekunden und ignorierte das
> konfigurierte Modell. Mit eigener kurzer Anweisung, ohne Werkzeuge,
> Einstellungen und MCP, mit dem konfigurierten Modell (voreingestellt Haiku) und
> einem Denkbudget von 2048 Tokens sind es 10 800 Tokens, rund 22 Sekunden und
> 0,03 $ je Buch. Bis zu **acht Bücher in einem Aufruf** kosten 79 Sekunden und
> 0,08 $ statt rund 176 Sekunden und 0,24 $ einzeln; ein Buch, das die Antwort
> auslässt oder krumm beschreibt, fehlt und bleibt unbeschrieben (ADR 7). Die
> Regelverstöße im Steckbrief sind mit beiden Wegen ähnlich hoch (etwa jeder
> zweite Steckbrief hat einen); sie stehen daneben und verwerfen nichts, und ihr
> Senken ist ein eigenes Ticket (#69). Die Leseprobe wird nicht mehr geholt
> (#68): der Steckbrief liest sie nicht, und die Funde im Stapel tragen keine.

> **Nachtrag vom 25.09.2026: Der Steckbrief gewichtet jedes Merkmal (#62), und
> die Anweisung ist geschärft (#69).** Jedes Merkmal trägt jetzt sein Gewicht in
> diesem Buch: *prägend* (ohne es wäre es ein anderes Buch), *deutlich* oder
> *am Rand*. Ein Erzählmuster trägt keines, denn es steht nur da, wenn es die
> Geschichte als Ganzes trägt. **Das Gewicht steuert nur die Stärke, nicht das
> Urteil:** die Stärke einer Familie oder Facette ist die Zahl der geliebten
> Bücher, die sie tragen, und eine Stufe mehr, wenn sie in einem dieser Bücher
> prägt (bei einer Kombination: alle ihre Familien zugleich), höchstens „sehr
> stark". So steht ein einzelnes Buch, in dem etwas prägt, nicht mehr bei
> „schwach". Die Rechnung des Urteils (0,8 je Facette, 0,1 je Merkmal, Tor ab
> drei Sternen, Gegengewicht 0,35) bleibt, wie sie ist: sie ist an den echten
> Büchern geeicht, und ein Gewicht darin würde jeden Prozentwert und die
> Eichung neu öffnen. Das ist ein eigenes Ticket.
>
> Die Anweisung sagt jetzt ausdrücklich: liegt ein Klappentext bei, ist das Buch
> nie „unbekannt"; der Beleg ist ein Wort (*klappentext* oder *wissen*), nie ein
> Satz, und *leseprobe* gilt nicht mehr, weil keine mitgeschickt wird (bei
> „Auslöschung" hatte das Modell sie zweimal erfunden); Erzählmuster gehören nie
> unter die Merkmale; hat eine Dimension mehr als drei Merkmale, fällt das mit
> dem geringsten Gewicht weg; der Pitch soll höchstens 180 Zeichen haben (geprüft
> wird weiter gegen 200). Das ändert den Fingerabdruck: **alle 48 gespeicherten
> Steckbriefe waren damit veraltet** und werden beim nächsten Gebrauch neu
> angelegt.
>
> Gemessen an sieben echten Funden aus dem Stapel (Haiku, im Bündel, mit ganzem
> Klappentext): alte Anweisung vier von sieben Steckbriefen mit Verstoß, neue
> Anweisung einer von sieben, Sonnet keiner; kein Buch „unbekannt". Einzeln, an
> neun Büchern mit ganzem Klappentext, darunter die beiden früheren
> „unbekannt"-Fälle: alle neun bekannt, vier mit einem Verstoß (dreimal zu wenige
> Dimensionen, zweimal ein zu langer Pitch, einmal mit 264 Zeichen). Sonnet
> brauchte 148 statt 123 Sekunden je Bündel und senkt die Verstöße nur noch um
> den einen; **Haiku bleibt der Standard**, Sonnet ist eine Einstellung
> (`rating_model`). Die Gewichte verteilen sich brauchbar: rund ein Drittel der
> Merkmale ist prägend, im Schnitt zwei je Buch.


> **Nachtrag vom 26.09.2026: die Formüberdeckung ersetzt die Rechnung (#79).**
> Das Urteil rechnet jetzt `taste_form.py`. Die Geschmacksform wird aus den
> bewerteten Büchern der Leserin gelernt (*Mag ich* und *Doof*, jedes Merkmal so
> stark, wie es im Buch wiegt), das Getippte und die Familien der Facetten sind
> der Startwert. Das Urteil ist der Anteil des Buchs, der in der Form liegt,
> weniger dem Teil in ihrer Ablehnung, geglättet, damit ein dünner Steckbrief
> vorsichtig bleibt; die Erzählmuster sind eine zweite Spinne, eine ganze
> Facette gibt einen Aufschlag, ein Gegengewicht mit Genre bleibt eine Regel.
> Ablehnung zählt je enttäuschendem Buch, je Merkmal das stärkste (MultiNeg),
> mit dem Verhältnis 0,2 zur Zustimmung (Rocchio). Die Werte stehen im
> Bewertungsschema (`urteil_formueberdeckung`); Herleitung und Prüfstand in
> `docs/research/urteil-methode.md`.
>
> Warum: Die alte Rechnung erkannte an 22 gemochten Büchern 14, fast nur die
> Thriller; die Formüberdeckung erkennt 18, jedes ohne sich selbst gelernt, und
> weist vier von fünf Gegenproben ab. Sie schwankt stärker, wenn ein Steckbrief
> dünner wird (rund 37 statt 26 % Stufenwechsel); das ist tragbar, weil jedes
> Buch einmal beschrieben wird.
>
> `load_judge` lernt die Form einmal je Liste; die Buchseite urteilt über
> denselben Weg wie das Tor. Die alte Rechnung liegt als Nachbau in
> `docs/research/prototyp/alte_rechnung.py`, damit der Prüfstand vergleichen
> kann.
>
> Korrektur am selben Tag: Die Ablehnung wird über die enttäuschenden Bücher
> **gemittelt** (Rocchio, γ/β = 0,33) statt je Merkmal das stärkste Buch zu
> nehmen. An synthetischen Leserinnen fiel mit MultiNeg die Ausbeute, je mehr
> Bücher sie bewerteten: ein einziges enttäuschendes Buch lehnte jede Familie
> voll ab, die es mit den gemochten teilt (Methode, Abschnitt 13).
