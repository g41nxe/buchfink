<p align="center">
  <img src="docs/bilder/github.jpg" alt="Banner im Cartoon-Stil: links der Schriftzug BUCHFINK mit dem Slogan Mehr lesen. Weniger suchen., rechts eine warme Schreibtischszene mit dem Vogel-Maskottchen, Bücherstapeln und der geöffneten Watchlist" width="900">
</p>

# Buchfink

**Weniger Suchen. Mehr Lesen.**

Buchfink behält deine Watchlist im Auge — in der Bibliothek und im Shop, jeden
Tag — und meldet sich nur, wenn sich wirklich etwas ändert. Nebenbei findet es
Bücher, nach denen du nie gesucht hättest, und sagt dir, ob sie zu dir passen.
Deinen Geschmack liest es aus Büchern, die du geliebt hast und die dich
enttäuscht haben, nicht aus einer Kaufhistorie. Fokus: deutschsprachige
Literatur aus dem Bestand des VÖBB (Berlin).

## Was es tut

**Eine Seite für heute.** Die Startseite sagt, wann zuletzt geprüft wurde, was
davon jetzt zu haben ist und worüber du entscheiden solltest — mehr nicht. Wie
viele Zeilen dort stehen, stellst du ein. Der Zustand des Werkzeugs steht auf
der Übersicht und drängt sich nicht auf.

<p align="center">
  <img src="docs/bilder/startseite.jpg" width="800"
       alt="Die Startseite: eine Statuszeile mit dem letzten Lauf, darunter was jetzt zu haben ist und was zu entscheiden ist">
</p>

**Drei Quellen, eine Zeile.** [Onleihe](https://voebb.onleihe.de),
[OverDrive](https://voebb.overdrive.com) und
[beam-shop.de](https://www.beam-shop.de) für jeden Titel gleichzeitig im Blick:
Preis hier, Verfügbarkeit dort. Onleihe und OverDrive gehören beide zum VÖBB
und führen trotzdem verschiedene Bestände. Weitere Quellen lassen sich ergänzen,
ohne den Kern anzufassen. Eine Quelle, deren Seiten sich geändert haben, fällt
beim Selbsttest vor dem Lauf durch und setzt aus, statt Unsinn aufzuzeichnen.

<p align="center">
  <img src="docs/bilder/watchlist.png" width="800"
       alt="Die Watchlist: jeder Titel mit Preis oder Verfügbarkeit, Shop- und Bibliotheks-Symbol">
</p>

**Watchlist und Vorschläge folgen verschiedenen Regeln.** Was du selbst auf die
Watchlist gesetzt hast, wird zu jedem Preis gemeldet. Vorschläge kommen aus
Neuzugängen deiner Autor:innen, aus Themen, denen du folgst, und aus
Bibliothekslisten — und müssen es sich verdienen: als Schnäppchen, in deiner
Sprache, nicht mitten aus einer Reihe, die du nicht liest, nicht von einem
Sprachmodell geschrieben. Sammelbände, Kurzgeschichten und Gratistitel fallen
heraus; eine Sammelausgabe, die billiger ist als ihre Einzelbände, wird dagegen
als solche genannt. Aussortiert wird beim Melden, nie beim Sammeln: ein Buch,
das heute zu teuer ist, meldet sich an dem Tag, an dem sein Preis fällt.

<p align="center">
  <img src="docs/bilder/vorschlaege.png" width="800"
       alt="Die Vorschlagsseite: Cover, Sterne, ein Satz warum das Buch passt, und drei Zeichen zum Entscheiden">
</p>

**Dein Leseprofil entsteht aus Büchern.** In der Erstaufnahme nennst du drei
bis fünf Bücher, die du geliebt hast, und bis zu fünf, die dich enttäuscht
haben. Daraus tippst du an, was die guten gemeinsam haben und was den
enttäuschenden gefehlt hat — aus festen Listen, nicht in freiem Text. Später
schärfst du auf der Buchseite nach: „Mag ich“ oder „Doof“, dazu die Merkmale,
auf die es dir ankommt. Jede Änderung ist eine neue Fassung; keine
überschreibt die vorige.

**Das Modell beschreibt, der Code urteilt.** Ein Sprachmodell beschreibt jedes
Buch **einmal** mit Merkmalen aus einem festen Vokabular — der Steckbrief. Wie
gut es zu dir passt, rechnet der Code daraus: Prozent, Sterne und eine
Begründung, die auf Daten zeigt, nicht auf Eindrücke. Ändert sich dein Profil,
ist jede Zahl sofort neu, ohne das Modell noch einmal zu fragen. Ein Buch, dem
der Steckbrief nicht gerecht wird, lässt du mit dem Hammer in seiner Zeile neu
beschreiben. Einen API-Schlüssel brauchst du nicht, wenn Claude Code bei dir
angemeldet ist; sonst genügt `ANTHROPIC_API_KEY` in der Umgebung.

<p align="center">
  <img src="docs/bilder/buchseite.png" width="800"
       alt="Die Buchseite: was du dazu sagst, wie gut es passt, und die letzten Beobachtungen">
</p>

**Der ganze Verlauf, nicht nur der letzte Preis.** Jede Beobachtung wird
angehängt, nie überschrieben. Gelöscht wird nichts: ein Buch, das du einmal
beobachtet hast, bleibt eine Auskunft, auch nachdem du es gekauft hast. Jede
Liste zeigt ein Buch in derselben Zeile, und dasselbe Wort steht auf jedem
Knopf, der dieselbe Entscheidung trifft.

**Ein Tagesbericht, nur wenn es etwas zu sagen gibt.** Ein Lauf, der etwas
gefunden hat, schreibt Text auf die Konsole und eine HTML-Seite nach
`data/digests/`, die auch die Oberfläche zeigt. Hat sich nichts geändert,
schweigt er.

**Läuft bei dir.** Kein Konto, keine gespeicherten Zugangsdaten, keine Cloud —
eine SQLite-Datei auf deinem Rechner, Server oder Raspberry Pi. Titelbilder und
Skripte liegen lokal; die Oberfläche lädt nichts von fremden Servern.

## Schnellstart

Voraussetzungen: Python 3.12 oder neuer und [uv](https://docs.astral.sh/uv/).

```bash
uv sync
mkdir -p data
cp examples/settings.yaml examples/seed.yaml examples/watchlist.yaml data/
```

`data/settings.yaml` (Quellen, Schwellwerte, wie viele Zeilen die Startseite
zeigt), `data/seed.yaml` (Autor:innen und Themen) und `data/watchlist.yaml`
(Titel und Autor:in genügen) anpassen, dann die Datenbank füllen und einen
ersten Lauf fahren:

```bash
uv run python -m ebook_watchlist.run seed
uv run python -m ebook_watchlist.run
```

Der erste Lauf sät Beobachtungen und schweigt; ab dem zweiten meldet er
Änderungen. Für die Oberfläche einmal die statischen Dateien bauen, dann
starten:

```bash
uv run tailwindcss_install && uv run python -m ebook_watchlist.web.build
uv run python -m ebook_watchlist.web
```

Danach unter `http://<rechner>:8437/` erreichbar, auch vom Telefon im selben
Netz. Die Oberfläche hat **keine Anmeldung** — sie gehört nicht ins offene
Internet; `--host 127.0.0.1` beschränkt sie auf diesen Rechner.

Sterne gibt es erst mit dem Vokabular der Merkmale (siehe
[Entwickeln](#entwickeln)) und einem Leseprofil; die Erstaufnahme beginnt auf
der Profilseite. Ohne beides beobachtet und sammelt Buchfink wie beschrieben,
nur ohne Urteil.

## Befehle

Alle über `uv run python -m ebook_watchlist.run <befehl>`:

| Befehl | Was er tut |
| --- | --- |
| `run` | ein vollständiger Lauf (die Voreinstellung); mit `--watchlist` nur die Watchlist, ohne nach Vorschlägen zu suchen |
| `seed` | überführt `seed.yaml`, `watchlist.yaml` und `owned.yaml` in die Datenbank; beliebig wiederholbar |
| `doctor` | prüft nur, ob die Quellen noch gelesen werden können |
| `sources` | zeigt den Zustand der Quellen und pausiert eine mit `--disable`, ohne Konfiguration anzufassen |
| `rate` | schreibt Steckbriefe für den Rückstand an Vorschlägen, außerhalb des Budgets eines Laufs |
| `judge` | hält Titel oder eine YAML-Liste gegen dein Profil und schreibt Sterne und Begründung dazu |
| `dismissals` | löst alte Shop-Produktnummern aus `dismissed.yaml` in Buch-Beziehungen auf |

Dieselben Läufe stößt die Oberfläche an: „Jetzt prüfen“ auf Startseite und
Übersicht, „Nur Watchlist“ auf der Watchlist. Eine Dateisperre sorgt dafür,
dass nie zwei gleichzeitig laufen, egal woher sie kommen.

## Betrieb

Am besten als täglicher Lauf plus dauerhaft laufende Oberfläche. Fertige
Vorlagen in [docs/betrieb.md](docs/betrieb.md):

- **Docker Compose** — Lauf und Oberfläche in einem Container, optional hinter
  Traefik
- **Windows** — Aufgabenplanung für Lauf und Oberfläche
- **Linux / Raspberry Pi** — systemd-Timer und -Dienst

## Entwickeln

```bash
uv run pytest && uv run ruff check .
```

Kein Netzzugriff in der Suite; Smoke-Tests gegen die echten Quellen laufen nur
mit `-m live`. Der Code ist englisch, alles Gelesene deutsch — die Begriffe
dazwischen stehen in [CONTEXT.md](CONTEXT.md) (ADR 22).

Das Vokabular der Merkmale und Erzählmuster (`vocabulary/merkmale.yaml`,
`vocabulary/erzaehlmuster.yaml`) liegt **nicht** im Repository: es beruht auf
NoveList, und ob es veröffentlicht werden darf, ist ungeklärt (#59). Ohne diese
Dateien gibt es keinen Steckbrief, keine Sterne und keine Erstaufnahme; die
Tests dazu werden übersprungen. Ein anderes Verzeichnis lässt sich mit
`EBW_VOCABULARY_DIR` angeben.

## Dokumentation

**Das Werkzeug verstehen**

- [docs/rundgang.md](docs/rundgang.md) — was das Werkzeug kann und wie ein Lauf
  arbeitet, ohne den Code zu lesen (Stand 5. September 2026)
- [CONTEXT.md](CONTEXT.md) — Glossar: englischer Name und deutsches Wort
- [docs/adr/](docs/adr) — alle Entscheidungen mit Kontext und Konsequenzen;
  zum Urteil vor allem
  [ADR 33](docs/adr/0033-das-leseprofil-entsteht-aus-buechern-und-der-code-urteilt.md)

**Das Urteil**

- [docs/bewertungsschema.yaml](docs/bewertungsschema.yaml) — die Zahlen, mit
  denen der Code Sterne rechnet: Gewichte, Sternetabelle und die Schwelle, ab
  der ein Vorschlag im Stapel bleibt
- [docs/research/urteil-methode.md](docs/research/urteil-methode.md) — wie die
  Rechnung entstanden ist
- [docs/research/rating-without-an-api-key.md](docs/research/rating-without-an-api-key.md)
  — der Weg über die lokale Claude-Code-Installation

**Geschichte und Recherche**

- [docs/offene-punkte.md](docs/offene-punkte.md) — was fehlt, und welche
  Behauptungen sich unterwegs als falsch erwiesen haben
- [docs/research/](docs/research) — Recherche zu den Quellen, zu
  Metadatenquellen und deren Rechtslage

## Für Agenten

Einstieg in [CLAUDE.md](CLAUDE.md) und [docs/agents/](docs/agents).

## Lizenz

[MIT](LICENSE).
