# Rundgang: wie die Watchlist arbeitet

Stand 2026-09-05. Was dieses Werkzeug kann und wie es funktioniert — in der
Tiefe, in der man es einmal verstehen will, ohne den Code zu lesen. Die
Entscheidungen hinter jedem Absatz stehen als ADR 1–21 daneben, die Begriffe in
[`CONTEXT.md`](../CONTEXT.md).

Alle Zahlen hier stammen aus der laufenden Datenbank und aus gemessenen Läufen.
Keine ist geschätzt.

---

## Wozu

Ein Werkzeug, das jeden Tag nachsieht, ob ein Buch von deiner Liste in der
**Berliner Onleihe** ausleihbar geworden ist oder im **Shop** im Preis gefallen —
und das nur dann etwas sagt, wenn sich wirklich etwas geändert hat.

Es sucht dir außerdem Bücher, nach denen du nicht gefragt hast. Genau daran
entscheidet sich, ob so ein Werkzeug nützlich oder lästig ist, und der größte
Teil der Arbeit steckt in der Frage, was davon dich überhaupt erreichen darf.

| | |
| --- | --- |
| Quellen | 2 — VÖBB Onleihe (Bibliothek), beam-shop.de (Shop) |
| Beobachtete Titel | 15 |
| Bücher mit Beziehung | 50 |
| Offene Vorschläge | 373 |
| Entscheidungen | ADR 1–21 |
| Tests | 607 |

---

## Ein Lauf, Schritt für Schritt

Ein **Lauf** ist ein Durchgang von *nachsehen → vergleichen → berichten*. Ihn
stößt entweder ein Cron-Job an, der Knopf in der Oberfläche oder die
Kommandozeile — es ist immer derselbe Weg. Die Reihenfolge ist nicht beliebig;
an drei Stellen ist sie das Ergebnis eines Fehlers.

**1. Konfiguration aus der Datenbank laden.** Profil und Watchlist stehen in
SQLite, nicht in YAML. Die YAML-Dateien sind Saatgut, einmal importiert.

> Kein stiller Rückfall auf die Dateien: eine leere Datenbank heißt „noch nicht
> importiert", und das gehört gesagt, statt monatelang gegen eine Datei zu
> laufen, die alle für abgelöst halten.

**2. Jede Quelle fragen, ob sie noch funktioniert.** Vor dem eigentlichen Abruf
bekommt jede Quelle eine bekannte Seite vorgelegt: erkennen die Parser sie noch?

> Eine halb gelesene, umgebaute Website schriebe Unsinn in die Geschichte und
> vergiftete jeden künftigen Vergleich. Eine Quelle, die hier durchfällt, sitzt
> den Lauf aus — die andere läuft weiter.

**3. Sammeln.** Die Onleihe wird nach den beobachteten Titeln gefragt. Der Shop
zusätzlich nach Neuzugängen deiner Referenzautor:innen und in deinen Themen.
Jede Antwort wird eine *Beobachtung*.

**4. Vergleichen mit dem zuletzt Gesehenen.** Verglichen wird gegen die letzte
gespeicherte Beobachtung, nicht gegen „gestern". Was sich unterscheidet, ist ein
*Delta*.

> Dadurch ist der Lauf gegenüber seinem Zeitplan gleichgültig: drei ausgefallene
> Cron-Läufe kosten nichts, der nächste berichtet alles Angesammelte (ADR 4).

**5. Alles Gesehene in die Aufzeichnung schreiben.** Anhängend, nie überschreibend —
auch das, was du nie zu sehen bekommst.

> Deshalb steht dieser Schritt *vor* allem, was noch schiefgehen kann: ein
> Ausfall darf ein Urteil kosten oder ein Titelbild, niemals Geschichte.

**6. Titelbilder holen** — höchstens eins je Buch, einmal, und nur für Bücher,
zu denen du eine Beziehung hast. Für Vorschläge wären das hunderte Anfragen pro
Lauf.

> Dieser Schritt stand einmal *vor* der Aufzeichnung. Ein `403` auf ein Bild riss
> damit den ganzen Lauf ab, bevor eine einzige Beobachtung geschrieben war — und
> `403` ist genau die Antwort, mit der ein Shop einen Bot aussperrt.

**7. Das Bewertungstor, dann der Tagesbericht.** Was die Preisregel durchgelassen hat,
wird gegen dein Leseprofil gehalten: ein Modell beschreibt jeden neuen Fund einmal, den Rest rechnet der Code. Übrig bleibt der Tagesbericht — Text auf die
Konsole, HTML nach `data/digests/`. Gibt es nichts zu sagen, sagt er nichts.

---

## Drei Kanäle, zwei Regeln

Woher ein Fund kommt, entscheidet, was er leisten muss, um dich zu erreichen.
Das ist die wichtigste Regel des ganzen Werkzeugs (ADR 19).

| Kanal | Regel | Warum |
| --- | --- | --- |
| **Watchlist** — du hast danach gefragt | immer melden | Du hast dieses Buch selbst hingeschrieben. Der Preis ist nicht das, was es interessant macht. |
| **Referenzautor:in** — jemand, den du liest | nur als Schnäppchen | Lange galt hier eine Ausnahme: gemeldet zu jedem Preis. Sie war als vorläufig gedacht und ist beendet. |
| **Thema** — ein Regal, dem du folgst | nur als Schnäppchen | Der schwächste Hinweis von allen: der Shop hat das Buch einsortiert, mehr weiß niemand. |

> „Ein Watchlist-Titel wird immer gemeldet. Ein Fund muss es sich
> verdienen."

In der Praxis heißt „Schnäppchen" am Tag des Fundes **unter 5,00 €**: die
Buchpreisbindung verbietet dem Shop Streichpreise, und ein neuer Fund hat noch
keine Vorgeschichte, gegen die sich ein Nachlass messen ließe.

---

## Was dich erreicht — und was nicht

Drei Siebe hintereinander, jedes billiger als das nächste. Kein Vorschlag wird
dabei gelöscht: aussortiert wird beim *Melden*, nie beim Sammeln. Ein Buch, das
heute zu teuer ist, wartet still und meldet sich an dem Tag, an dem sein Preis
fällt.

### 1. Die Preisregel

Kostenlos. Funde unter 5,00 € gelten sofort; im Band von 5,00 bis 9,99 €
braucht es mindestens 25 % Nachlass gegen einen früher beobachteten Preis.

*Gemessen:* von 300 Funden eines echten Laufs lagen 65 bei 10 € oder mehr
— die warten.

### 2. Der Ramschfilter

Sammelbände, Fortsetzungshefte und Gratistitel fliegen der Form nach raus, bevor
irgendjemand Geld für diese Erkenntnis ausgibt. Gilt nur für Themen — ein
Sammelband deiner Referenzautorin ist genau die Gelegenheit, eine Reihe am Stück
zu bekommen.

*Gemessen:* entfernt 9 % — deutlich weniger, als beim Entwurf angenommen.

### 3. Das Bewertungstor — **noch nie gegen echte Funde gelaufen**

Ein Modell beschreibt jeden neuen Fund **einmal** mit Merkmalen aus einem festen
Vokabular (der Steckbrief), und der **Code** rechnet daraus die Übereinstimmung
mit deinem Leseprofil: Prozent, Sterne und eine Begründung aus Daten. Unter drei
Sternen (die Schwelle steht im [Bewertungsschema](bewertungsschema.yaml)) kommt
ein Fund nicht auf den Stapel. Ein Fund ohne Urteil — kein Profil, noch kein
Steckbrief, ein Buch, das das Modell nicht kennt — wird gezeigt, nie
verschwiegen. Höchstens 40 Steckbriefe pro Lauf; ein vorhandener kostet nichts,
und eine neue Fassung deines Profils rechnet alles sofort neu, ohne das Modell
zu fragen.

Ohne Schlüssel benutzt das Tor die lokal angemeldete Claude-Code-Installation
für neue Steckbriefe; wo es gar keinen Weg zum Modell gibt, urteilt es über
die Funde, die schon einen Steckbrief haben. Den Rückstand eines ersten Laufs
beschreibt `ebw rate` außerhalb des Laufbudgets. Alles, was über das Verhalten
mit echten Funden gesagt wird, stammt aus Tests mit einem Stellvertreter, nicht
aus Betrieb.

---

## Was gespeichert wird

Fünf Begriffe tragen das ganze Datenmodell (ADR 18). Zwei Regeln darin sind
wichtiger als das Schema.

**Beobachtung** — was eine Quelle zu einem Zeitpunkt gesagt hat: Preis,
Verfügbarkeit, Titel, wie *sie* ihn schreibt. Nie das, was wir glauben. Wechselt
ein Shop still die Ausgabe unter derselben Nummer, bleibt das dadurch sichtbar.

**Buch** — ein Buch als Sache an sich, quellenunabhängig. **Eine Buchzeile
entsteht nur dort, wo du eine Beziehung dazu hast**; ein bloßer Fund
bleibt eine Beobachtung. Sonst bestünde die Tabelle mehrheitlich aus ungeprüften
Dubletten und verdiente ihren Namen nicht.

**Beziehung** — was du zu einem Buch sagst: *beobachtet, besessen, gefiel,
gefiel nicht, verworfen*. Mehrere gelten gleichzeitig, und sie werden
stillgelegt statt gelöscht: „beobachtet, bis du es gekauft hast" ist selbst eine
Auskunft.

**Interesse** — wo gesucht werden soll: eine Autor:in oder ein Thema. Ein neues
Interesse wird beim ersten Mal still angesät, sonst meldete eine frisch
hinzugefügte Autorin ihre gesamte Backlist als Neuzugänge.

**Urteil** — gespeichert wird nur, was ein Mensch sagt: deine eigenen Sterne und
der Durchschnitt fremder Leser:innen. Was das Werkzeug selbst von einem Buch
hält, wird aus Steckbrief und Leseprofil **gerechnet**, nie gespeichert; die
Zahlen dafür stehen im [Bewertungsschema](bewertungsschema.yaml). Die Herkunft
ist Teil des Schlüssels:

> „Eine 4 von dir ist eine Tatsache. Eine fremde Durchschnittsnote sagt etwas über das Buch, nicht darüber, ob es zu dir passt."

Deshalb stehen `reader` und `onleihe_readers` nebeneinander, überschreiben
einander nie und sehen auf der Buchseite verschieden aus. Eine neue
Profilversion entwertet nichts: deine Sterne bleiben, und die gerechnete
Übereinstimmung ist sofort neu (ADR 33).

Die zwei Regeln, die zählen: **die Aufzeichnung wird nur angehängt**, und **eine
Buchzeile entsteht nur, wo du eine Beziehung hast**.

---

## Womit du es bedienst

Eine Weboberfläche für alles, was Ansehen und Entscheiden ist. Eine
Kommandozeile für alles, was ein Vorgang ist. Die Oberfläche scrapt nie selbst —
sie stößt höchstens einen Lauf an (ADR 3).

### Die Seiten

Jede Liste zeigt ein Buch in derselben Zeile: Cover, Titel, Autor:in, woher es
kommt, was es kostet, was du damit tun kannst. Was eine Seite eigenes hat,
steckt in dieser Zeile — die Sterne des Tors auf dem Stapel, das Menü auf der
Watchlist. Und dasselbe Wort steht auf jedem Knopf, der dieselbe Entscheidung
trifft (ADR 29).

| Pfad | Was dort steht |
| --- | --- |
| `/` | Startseite: wann zuletzt geprüft wurde, was jetzt zu haben ist, worüber zu entscheiden ist — vor dem ersten Lauf erklärt sie sich. Wie viele Zeilen je Abschnitt stehen, sagt das Profil (`home_offers`, `home_suggestions`) |
| `/overview` | Übersicht: Zustand der Quellen, die letzten Läufe, die Tagesberichte — und der Knopf „jetzt laufen". Nicht im Menü; der Zeitpunkt „zuletzt geprüft“ auf der Startseite führt hin |
| `/watchlist` | Was du beobachtest, mit Preis und Ausleihstatus in einer Zeile |
| `/book/{id}` | Alles über ein Buch: Beziehungen, Quellen, Preisverlauf, Urteile — und deine eigenen Sterne |
| `/discovery/{quelle}/{nummer}` | Die Seite zu einem Fund: dieselbe wie die Buchseite, ohne das, was es vor einer Entscheidung nicht gibt (ADR 18). Sobald eine Beziehung gilt, führt sie auf die Buchseite |
| `/suggestions` | Der Stapel: entweder je Zeile ein Zeichen, oder mehrere ankreuzen und unten gemeinsam entscheiden |
| `/profile` | Was das Werkzeug über dich zu wissen glaubt. Nur zum Lesen — mit Absicht |

Start mit `python -m ebook_watchlist.web`. Die Oberfläche bindet an alle
Schnittstellen, damit sie vom Handy im selben Netz erreichbar ist, und hat
**keine Authentifizierung** — sie gehört nicht ins offene Internet
(`--host 127.0.0.1` schränkt sie auf diesen Rechner ein).

### Die Befehle

| Befehl | Was er tut |
| --- | --- |
| `run` | ein vollständiger Durchgang; der Cron-Job ruft genau diesen auf |
| `doctor` | fragt nur, ob die Quellen noch gelesen werden können — ohne etwas abzurufen |
| `sources` | listet die Quellen und pausiert eine, ohne dass jemand Konfiguration auskommentiert |
| `seed` | überführt die YAML-Dateien einmalig in die Datenbank; beliebig wiederholbar |
| `dismissals` | löst alte Shop-Produktnummern in Buch-Beziehungen auf |

---

## Woran wir uns halten

Vier Regeln, die sich durch den ganzen Code ziehen. Jede stammt aus einem
Fehler, nicht aus einem Lehrbuch.

**Wir sind Gast auf fremden Servern.** Eine Anfrage zur Zeit, 2 bis 4 Sekunden
Pause dazwischen, ein ehrlicher User-Agent, genau ein Wiederholungsversuch. Ein
`429` beendet den Lauf sofort, statt die Grenze auszutesten. Ein Titelbild ist
eine Anfrage wie jede andere und wird genauso behandelt (ADR 7).

**Messen statt behaupten.** Fast jeder Irrtum in diesem Projekt hatte dieselbe
Form: eine plausible Aussage über Daten, die niemand angesehen hatte. „Die
Testsuite braucht 88 Sekunden" — sie brauchte 11,7. „Google Books findet nichts"
— das war eine überschrittene Quote. Der Bündelfilter hätte *5 Cottages* und
*21 – Fremder Schatten* für Sammelbände gehalten. Die vollständige Liste steht
in [`offene-punkte.md`](offene-punkte.md).

**Nicht raten, sondern fragen.** Was sich nicht zweifelsfrei auflösen lässt,
landet auf einer Liste „braucht Aufmerksamkeit", statt erfunden zu werden. Ein
Freitext ohne erkennbaren Autornamen bekommt keinen angedichtet, und eine
Produktnummer sagt nicht, welches Buch gemeint ist — das kann nur der Shop
(ADR 8).

**Qualität vor Masse.** Lieber wenige, sehr gut passende Vorschläge als
massenweise unpassende. Ein leerer Stapel ist ein gutes Ergebnis, kein Fehler —
und Schweigen ist die Voreinstellung des ganzen Werkzeugs.

---

## Was noch nicht läuft

Ehrlicher Stand, damit dieser Rundgang nicht mehr verspricht, als es gibt. Die
ausführliche Fassung mitsamt der Liste widerlegter Behauptungen steht in
[`offene-punkte.md`](offene-punkte.md).

- **Das Bewertungstor hat nie gegen echte Funde gerechnet.** Die Rechnung ist an deinen sieben Büchern und an Zufallsbüchern gemessen; ob die Schwelle von drei Sternen stimmt, zeigt erst ein echter Lauf.
- **Es liegt kein einziges Titelbild da.** Der Weg steht, aber Bilder werden
  beim Lauf geholt, und seither lief keiner. Die Oberfläche zeigt durchweg
  Platzhalter.
- **Die Metadatenquelle ist recherchiert, nicht angebunden.** Ohne sie fehlen
  Sprachfilter, kanonische Schreibweisen sowie Reihe und Bandnummer — und damit
  die Grundlage für Serien-Tracking.
- **373 Vorschläge sind unbearbeitet.** Bewusst zurückgestellt, bis das Tor
  gefiltert hat: sie von Hand durchzusehen wäre genau die Arbeit, die das Tor
  abnehmen soll.
