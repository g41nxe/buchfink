# Welche Genres die Quellen kennen

Stand 04.10.2026, für die feste Genre-Liste aus #53 (Anlass: #56, Punkt 2).
Gemessen mit wenigen Anfragen: beam 9 Seiten, OverDrive 1, Onleihe 3.

## Kurz

| Quelle | Tiefe | Was es gibt | Adresse |
|---|---|---|---|
| beam | 2 Ebenen | Genre und für einige Genres Untergenres | Pfad `belletristik/<genre>/<untergenre>` |
| OverDrive | 1 Ebene | grobe Themen, keine Untergenres | `subject=<id>` |
| Onleihe | 3 Ebenen | Baum mit festen Nummern; nicht als Ganzes abrufbar | `mediaList,0-<id>-0-101-0-0-0-0-0-0-0.html` |

Für die Liste heißt das: **beam bestimmt, wo es Untergenres mit eigener Adresse
gibt**; OverDrive bekommt je Genre ein Thema; die Onleihe vorerst nur, was
bekannt ist (siehe unten).

## beam

Belletristik, oberste Ebene (19): Abenteuer & Western, Belletristik allgemein,
Biographien, Comics, Erotik, Fantasy, Fremdsprachige Romane, Historische
Romane, Horror & Mystery, Humor & Satire, Kinder- & Jugendbuch, Krimi &
Thriller, Kurzgeschichten & Anthologien, Romance, Romane & Erzählungen,
Science-Fiction, Theater & Lyrik — dazu eBook-Pakete und Gutscheine.

Untergenres, wo es welche gibt:

| Genre | Untergenres (Pfad) |
|---|---|
| `krimi-thriller` | `psychothriller`, `regionalkrimis`, `spionage`, `true-crime`, `krimi-thriller-allgemein` |
| `fantasy` | `high-fantasy`, `dark-fantasy`, `urban-fantasy`, `historische-fantasy`, `paranormal-romance`, `fantasy-allgemein` |
| `science-fiction` | `space-opera`, `military-sf`, `cyberpunk`, `dystopie`, `postapokalypse`, `zeitreisen`, `steampunk`, `alternative-geschichte`, `science-fantasy`, `sf-klassiker`, `science-fiction-allgemein` |
| `romance` | `liebesromane-allgemein`, `historische-liebesromane`, `romantasy`, `romantic-thrill`, `chick-lit`, `gay-romance` |
| `abenteuer-western` | `abenteuer`, `western`, `abenteuer-western-allgemein` |
| `horror-mystery` | nur `horror-mystery-allgemein` |
| `romane-erzaehlungen`, `historische-romane`, `humor-satire` | keine |

## OverDrive (VÖBB)

Themen der deutschen EPUB-Ausgaben (29 532 gesamt), aus der Facette `subjects`
einer Suche ohne Suchwort. Belletristisch und für die Leserin denkbar:

| Thema | Id | Titel |
|---|---|---|
| Fiction | 26 | 9 837 |
| Literature | 49 | 4 904 |
| Romance | 77 | 2 107 |
| Mystery | 57 | 1 972 |
| Fantasy | 24 | 1 943 |
| Thriller | 100 | 1 605 |
| Historical Fiction | 115 | 902 |
| Humor (Fiction) | 123 | 581 |
| Suspense | 86 | 322 |
| Science Fiction | 80 | 287 |
| Classic Literature | 10 | 229 |
| Short Stories | 82 | 168 |
| Horror | 38 | 57 |
| Science Fiction & Fantasy | 98 | 44 |
| Erotic Literature | 21 | 40 |
| True Crime | 92 | 33 |
| Western | 95 | 19 |

Keine Untergenres: ein Psychothriller ist bei OverDrive „Thriller" (oder
„Suspense"). Die heutige Zuordnung in `overdrive/selectors.py`
(`GENRE_SUBJECTS`) nutzt fünf davon; Science Fiction hat nur 287 Titel,
Horror 57.

## Onleihe (VÖBB)

Ein Baum mit festen Nummern, an jeder Detailseite als Pfad zu sehen:

- 2 Belletristik & Unterhaltung
  - 155 Krimi & Thriller
    - 185 Kriminalkomödie
  - 160 Romane & Erzählungen
  - 616 Historisches

Eine Kategorie lässt sich als Liste abrufen
(`mediaList,0-155-0-101-0-0-0-0-0-0-0.html`, Kopfzeile „Titel 1-20 von …").
Ihre **Unterkategorien zählt die Seite nicht auf** — weder die
Belletristik-Seite noch die von Krimi & Thriller. Bekannt wird eine Nummer
nur, wo eine Detailseite sie nennt.

Daraus folgt eine billige Möglichkeit: Detailseiten holt das Werkzeug ohnehin
für jeden Steckbrief (#17). Liest es dabei den Kategorienpfad mit, lernt es
den Baum nebenbei, ohne eine Anfrage mehr.

Umgesetzt mit #92: Die Detailseite nennt unter „Kategorie:" eine **flache
Liste** (2, 160, 616), keinen Pfad. Das Belegesammeln zählt jede Nummer mit,
`ebw categories` listet sie und zeigt, welche schon in `GENRES` steht. Das
Fegen über die Kategorienliste ist #93.

## Offen

- Ob die Onleihe ein Verzeichnis aller Kategorien hat (Menü, Sitemap) — nicht
  gefunden, nicht weiter gesucht.
- beam „Belletristik allgemein" und „Romane & Erzählungen" ohne Untergenres:
  Gegenwartsliteratur hat dort keine feinere Adresse.

## Objektive Grundlage: BISAC

Die Unterteilung oben ist die der Quellen; für die Liste selbst braucht es
einen Maßstab, der weder Shop noch Modell ist. Zwei Systeme des Buchhandels
kommen in Frage: **BISAC** (BISG, USA) und **Thema** (EDItEUR, international,
mit deutschen Bezeichnungen und einer offiziellen Zuordnung von BISAC).

**BISAC steckt schon in den Daten** — vom Verlag vergeben, nicht vom Modell:

- Die **DNB** nennt es je ISBN in Feld 653: „(BISAC Subject Heading)
  FIC022020: FICTION / Mystery & Detective / Police Procedural", daneben die
  VLB-Warengruppe („9121: Belletristik/Krimis, Thriller, Spionage").
- **OverDrive** nennt es je Titel (`bisacCodes`, `bisac[].description`).
- Thema-Codes stehen in keiner der gespeicherten DNB-Antworten.

Die belletristischen Gruppen (Quelle: bisg.org/fiction, abgerufen 04.10.2026),
gekürzt auf das, was für die Leserin in Frage kommt:

| Gruppe | Codes (Auswahl) |
|---|---|
| Thrillers FIC031 | General 000 · Crime 010 · Domestic 100 · Espionage (FIC006000) · Legal 030 · Medical 040 · Military 050 · Political 060 · Psychological 080 · Supernatural 070 · Suspense (FIC030000) · Technological (FIC036000) · Terrorism 090 |
| Mystery & Detective FIC022 | General 000 · Amateur Sleuth 100 · Cozy 070 (+ Unterarten) · Hard-Boiled 010 · Historical 060 · International 080 · Police Procedural 020 · Private Investigators 090 · Traditional 030 · Women Sleuths 040 |
| Science Fiction FIC028 | General 000 · Action & Adventure 010 · Alien Contact 090 · Androids & KI 150 · Apocalyptic & Post-Apocalyptic 070 · Crime & Mystery 140 · Cyberpunk 100 · Genetic Engineering 110 · Hard SF 020 · Humorous 120 · Military 050 · Space Exploration 130 · Space Opera 030 · Steampunk 060 |
| Dystopian | FIC055000 (eigene Gruppe, nicht unter Science Fiction) |
| Fantasy FIC009 | General 000 · Action & Adventure 100 · Contemporary 010 · Cozy 160 · Dark Fantasy 070 · Dragons 120 · Epic 020 · Historical 030 · Humorous 080 · Military 140 · Paranormal 050 · Romance 090 · Urban 060 |
| Horror FIC015 | General 000 · Cosmic & Eldritch 020 · Monsters & Creatures 030 · Occult & Supernatural 040 · Psychological 050 · Slasher 060 |
| Romance FIC027 | General 000 · Contemporary 020 · Fantasy 030 · Historical 050 · Paranormal 120 · Suspense 110 · Dark Romance 560 (… und viele Tropes) |
| Historical FIC014 | nach Epochen |
| Weitere | Action & Adventure FIC002000 · Humorous FIC016000, Dark Humor FIC060000 · Literary FIC019000 · Family Life FIC045 |

Auffällig: Was der Bestand frei geschrieben nahelegte, hat BISAC fast alles
als eigenen Code — „Domestic Thriller", „Cozy", „Police Procedural",
„Dark Humor", „Space Opera", „Cyberpunk", „Dark Fantasy", „Occult &
Supernatural". Nicht in BISAC: Regionalkrimi, Folk Horror.
