# 32. Einstellungen, Saatgut und Leseprofil liegen getrennt

Was eine Leserin über sich sagt, steht an drei Orten, und jeder hat ein eigenes
Wort. `data/profile.yaml` gibt es nicht mehr.

## Kontext

Eine Datei trug drei verschiedene Sorten Inhalt, und man sah ihnen den
Unterschied nicht an:

- **Wirksam.** `sources`, `rating_budget`, `home_offers`, die Preisgrenzen,
  `languages`. Wer sie ändert, ändert den nächsten Lauf.
- **Wirkungslos.** `reference_authors`, `extended_authors`,
  `genre_categories`, `liked_books`, `disliked_books`. Seit ADR 18 steht in
  der Datenbank, was gilt; `configuration.load` überschrieb die ersten drei
  bei jedem Lauf und leerte die letzten beiden ausdrücklich, „damit niemand
  aus Versehen gegen eine veraltete YAML-Kopie arbeitet". Wer sie in der Datei
  änderte, änderte nichts — und nichts sagte es ihm.
- **Für Menschen.** `no_gos` und ein Prosa-Kopf über den eigenen Geschmack.
  Der Bewerter las beides nie; er liest `docs/leseprofil.yaml` (ADR 21).

Dazu kam der Name. Seit ADR 21 heißt das Leseprofil `docs/leseprofil.yaml` und
hat ein eigenes Änderungsverfahren. Zwei Dateien hießen „Profil", und welche
gemeint war, musste man jedes Mal erschließen.

## Entscheidung

Drei Orte, drei Wörter:

| Ort | Deutsch | Inhalt | Wann es gilt |
|---|---|---|---|
| `data/settings.yaml` | Einstellungen | Quellen, Kadenz, Budgets, Schwellwerte, Sprachen | bei jedem Lauf |
| `data/seed.yaml` | Saatgut | Autor:innen, Themen, Buchlisten | einmal, beim Import |
| `docs/leseprofil.yaml` | Leseprofil | wonach geurteilt wird | bei jedem Urteil, mit Version |

Der Typ `Profile` heißt `Settings` und trägt nur noch, was in
`settings.yaml` steht. Das Saatgut bekommt einen eigenen Typ `Seed`, den allein
`seed.sow` benutzt. `no_gos` und der Prosa-Kopf entfallen ersatzlos: ihr Inhalt
steht in `docs/leseprofil.yaml` bereits, und zwar ausführlicher — die
Gegenanzeige „seichter Cozy-Krimi" als `genres.passt_nicht: Cozy-Krimi`, die
„isolierten Settings" als Achse *Enge*.

Drei Felder bleiben am Typ stehen, ohne aus einer Datei zu kommen:
`reference_authors`, `extended_authors` und `genre_categories`.
`configuration.load` füllt sie aus der Datenbank. Sie auch aus den Signaturen
zu entfernen hieße, die Quellenschnittstelle anzufassen — ein breiter Schnitt
für einen begrifflichen Gewinn, den `configuration.load` schon erbringt.

## Konsequenzen

- Wer eine Einstellung ändert, sieht sofort eine Wirkung. Wer das Saatgut
  ändert, liest in dessen erster Zeile, dass er das nicht tut.
- Eine bestehende Installation braucht beide neuen Dateien. Es gibt keine
  Migration beim Laden: Code, der genau einmal etwas tut und danach bei jedem
  Start geprüft wird, verrottet.
- `docs/leseprofil.yaml` bleibt unberührt, und damit auch seine Version. Etwas
  hineinzuschreiben hätte Fassung 5 bedeutet und jedes gespeicherte
  Maschinenurteil als veraltet markiert.
- Die Profilseite zeigt die Gegenanzeigen nur noch einmal. Vorher standen sie
  zweimal da: als Kästchenreihe aus `no_gos` und zwei Zeilen darunter im
  Leseprofil selbst, wo sie begründet sind.
- Der Skill `buch-bewerten` liest ein Dokument statt zweier.

> **Nachtrag: eine Zeile abgelöst durch ADR 33.** Das Leseprofil liegt nicht
> mehr in `docs/leseprofil.yaml`, sondern als Fassungen je Leserin in der
> Datenbank. Einstellungen und Saatgut bleiben, wie sie hier stehen.
