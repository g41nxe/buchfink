# 21. Leseprofil und Bewertungsschema trennen

## Context

`docs/leseprofil.md` heißt „der Maßstab" und enthält zwei Dinge, die nichts
miteinander zu tun haben:

- **Was die Leserin mag** — fünf gewichtete Kernachsen, Gegenanzeigen.
- **Wie zu urteilen ist** — die Sternedefinition, die vier Anforderungen an eine
  Begründung, `confidence`, die Gegenprobe, „nichts erfinden".

Beides trägt dieselbe Versionsnummer. Eine Änderung an der *Verfahrensregel* —
etwa eine schärfere Vorschrift, wie eine Begründung auszusehen hat — erhöht
damit die Maßstabsversion und entwertet **jede** gespeicherte Maschinenbewertung,
obwohl sich am Geschmack der Leserin nichts geändert hat.

Die Leserin hat im Gespräch beschrieben, was ein Leseprofil für sie ist: eine
möglichst detaillierte Beschreibung, welche Bücher sie mag, entstanden in einem
Gespräch darüber, *warum* sie welche Bücher mag. Sie ist die Grundlage der
Entscheidung, ob eine Beobachtung interessant ist. Die suchbaren Kategorien und
die Autor:innen sind daraus **abgeleitet** und nicht selbst das Profil.

Dazu kommt ein Befund: es gibt bereits **zwei Bewerter**, und sie sind
auseinandergedriftet.

| | `buch-bewerten` (Skill) | `gate.py` (Lauf) |
| --- | --- | --- |
| Recherche | nachschlagen, bis mindestens `teils` erreicht ist | nur der Klappentext |
| `vermutet` | „ist hier ein Fehler" | ausdrücklich vorgesehen |

Dieselbe Sternskala, verschiedene Sorgfalt, kein gemeinsames Blatt, auf das man
zeigen könnte. In der Datenbank stehen beide Urteile nebeneinander, und das Tor
benutzt ein Gesprächsurteil ungeprüft weiter, als wäre es eines seiner eigenen.

## Decision

**1. `docs/leseprofil.yaml` wird die Beschreibung.** Es trägt die Achsen als
*Inhalt*, mit ihrer Gewichtung, in Prosa. Es ist versioniert, und diese Version
bedeutet ab jetzt genau eine Sache: den Stand des Geschmacks der Leserin.

**2. `docs/bewertungsschema.yaml` entsteht neu und bleibt stabil.** Es enthält,
was heute in den Abschnitten 3 bis 6 des Maßstabs steht: was ein Stern bedeutet,
was eine Begründung leisten muss, was `confidence` bedeutet, die Gegenprobe,
„nichts erfinden". Es nennt **keine einzige inhaltliche Achse** — es sagt nur,
wie man ein Buch gegen ein beliebiges Profil hält.

**3. Beide Bewerter lesen dasselbe Schema.** `buch-bewerten` und `gate.py`. Der
Skill wird dadurch dünn: Schema laden, anwenden, Ergebnis schreiben.

**4. Eine Bewertung hängt an der Profilversion.** Eine Schemaänderung entwertet
nichts. Nur wenn sich der Geschmack schärft, veralten Urteile — und das ist die
einzige Änderung, bei der ein erneuter Aufruf richtig ist.

**5. Die Achsen erreichen das Modell weiterhin als ganzer Text.** Der Prompt
trägt das Profil vollständig, so wie heute. Es wird **kein** Ableitungsschritt
gebaut, der die Achsen einmal je Profilversion extrahiert und einfriert.

Das war der zunächst empfohlene Weg, und er wird hier ausdrücklich abgelehnt:
Er löst ein Problem, das **niemand beobachtet hat**. Das Bewertungstor ist kein
einziges Mal gelaufen; über die Frage, ob ein Modell die Gewichtung aus Prosa
verlässlich liest, gibt es in diesem Projekt keine einzige Messung. Erst
bewerten lassen, dann sehen, was schiefgeht — und dann bauen.

**6. Autor:innen und Kategorien behalten ihren Platz, bekommen aber eine
Herkunft.** Sie bleiben in `data/profile.yaml`, tragen aber die Profilversion,
aus der sie abgeleitet wurden. Damit ist sichtbar, wenn das Profil weitergezogen
ist und die Suchlisten stehengeblieben sind.

## Consequences

- `rating.rubric_version` wird zu `profile_version` — eine Umbenennung mit
  Migration. Der Name hat behauptet, das Urteil hänge am Maßstab; das war nie
  die Absicht und ab hier ausdrücklich falsch.
- Die dreistufige Beweislast aus `leseprofil-schaerfen` (ADR 17) gilt weiterhin,
  aber nur noch für **das Profil**. Am Schema ändert dieser Skill nichts.
- Der Konflikt oben muss **im Schema** entschieden werden: es hat zu sagen, was
  ein Urteil mit `confidence: vermutet` überhaupt darf. Heute lässt das Tor ein
  vermutetes Urteil ein Buch aussortieren — für eine Entscheidung, von der die
  Leserin nie erfährt, ist das die schwächste Grundlage im ganzen System.
- Eine Profiländerung hat einen messbaren Preis: 373 offene Vorschläge zu je
  gemessenen 34 Sekunden über Claude Code sind rund dreieinhalb Stunden
  Nachbewertung, verteilt auf etwa zehn Läufe. Das Profil zu schärfen ist
  billig; es oft zu schärfen ist es nicht.
- Der Schnitt geht durch ein vorhandenes Dokument, nicht durch Neuland: die
  Abschnitte liegen bereits getrennt nebeneinander.

> **Nachtrag: beide Dokumente sind strukturiert.** Angelegt wurden sie als
> Markdown; beide sind inzwischen YAML. Der Grund ist bei jedem ein anderer.
>
> Beim **Profil** ist es die Bearbeitbarkeit: die Achsen sind eine geordnete
> Liste, deren Reihenfolge die Gewichtung *ist*, die Genres sind zwei Listen,
> die sich ändern, und jeder Abschnitt trägt `belegbar_aus` — woraus er sich
> überhaupt beurteilen lässt. Das macht `confidence` zum ersten Mal ableitbar
> statt geschätzt.
>
> Beim **Schema** ist es die Einzigkeit der Quelle: die drei
> `confidence`-Werte standen viermal in Python und einmal als Prosa im
> Dokument. Jetzt liest der Code Spanne und Werte aus der Datei, und ein
> vierter Wert kostet eine Änderung statt fünf.
>
> Das Schema nennt außerdem selbst, welche Abschnitte in den Prompt gehören.
> Die Gegenprobe etwa betrifft die Pflege des Profils und nicht das Urteil über
> ein Buch — sie mitzuschicken kostet Aufmerksamkeit für etwas, das der
> Bewerter gar nicht tun soll.

> **Nachtrag: in Teilen abgelöst durch ADR 33.** Punkt 1 gilt nicht mehr: Das
> Leseprofil liegt als Fassungen in der Datenbank, nicht als Repo-Datei. Punkt
> 5 gilt nicht mehr: Genau der hier abgelehnte Ableitungsschritt ist gekommen,
> weil die Probleme inzwischen beobachtet sind (#42, die Kosten jeder
> Profiländerung, die Reproduzierbarkeit). Ein Modell vergibt einmal je Buch
> Merkmale; geurteilt wird im Code. Die Trennung von Leseprofil und
> Bewertungsschema bleibt, und das Schema bleibt ohne Version.
