# 37. Genres sind BISAC-Codes

Ein Genre ist ein Eintrag einer festen Liste, `docs/genres.yaml`, und jeder
Eintrag ist ein BISAC-Code mit deutschem Namen. Die Liste kennt keine Quelle;
jede Quelle übersetzt die Codes selbst in ihre Kategorien. Die Leserin mag
oder mag nicht Genres und Autor:innen, abgeleitet aus ihren Büchern und frei
zu ändern. Die Einzelheiten stehen in #53.

## Kontext

Das Genre eines Buchs war freier Text des Modells. In 393 Steckbriefen standen
221 verschiedene Untergenre-Anfänge; die 80 häufigsten deckten 64 %. Dasselbe
hieß „Psychothriller", „Psycho-Thriller" und „Psychologischer Thriller", schon
die oberste Ebene schwankte zwischen „Science-Fiction" und „Science Fiction".
Ein Gegengewicht „nur bei Genre" vergleicht diesen Text und traf deshalb nur
eine Schreibweise (#56, Punkt 2).

Eine Tabelle mit Synonymen hätte das nicht gelöst: jeder Lauf bringt neue
Schreibweisen. Ein Entwurf aus dem Bestand selbst wäre nicht objektiv gewesen —
ein Viertel Psychothriller ist das Profil der Leserin, kein Maßstab.

Recherche: `docs/research/genres-der-quellen.md`. Kurz: beam kennt Genre und
für einige Genres Untergenres, OverDrive nur grobe Themen, die Onleihe einen
Baum mit festen Nummern, den keine Seite als Ganzes zeigt. **BISAC** (BISG,
Buchhandel) steckt schon in den Daten: die DNB nennt es je ISBN, OverDrive je
Titel, vom Verlag vergeben.

## Entscheidung

### Die Liste

- `docs/genres.yaml`: Genre → Untergenre, **ein Untergenre je Buch**. Jeder
  Eintrag trägt den BISAC-Code als Id, den deutschen Namen und die
  BISAC-Bezeichnung zum Nachprüfen.
- Eine **Auswahl** aus BISAC: aufgenommen wird, was mindestens ein Buch im
  Bestand braucht. Die Ordnung kommt aus BISAC, nicht aus dem Geschmack.
- Das „sonstiges" einer Gruppe ist BISACs eigenes „General" (FIC031000 …).
- Eine eigene Erweiterung, als solche markiert: **Regionalkrimi** — fester
  Begriff des deutschen Marktes, bei beam eine Kategorie, in BISAC nicht.
- Wo ein Genre gespeichert wird (Steckbrief, Profil, Thema), stehen **Code und
  Name**. Maßgeblich ist der Code; benennt die Liste um, zieht ein Schritt die
  Namen nach.

### Die Quellen übersetzen selbst

- Die Liste kennt keine Quelle. Jede Quelle hält neben ihrem Code eine Tabelle
  Code → eigene Adresse (beam-Pfad, OverDrive-Thema, Onleihe-Nummer).
- Der Rückfall steht einmal in `Source`: Untergenre → Genre → nichts. Ohne
  Eintrag fegt die Quelle das Thema nicht; geraten wird nicht.
- Ein Test prüft, dass jede Id einer Quellentabelle in der Liste steht.
- Eine neue Quelle braucht nur ihre Tabelle.
- Ein Thema ist ein Listeneintrag, nicht mehr ein beam-Pfad; die vorhandenen
  werden einmal umgeschrieben.

### Wer das Genre eines Buchs bestimmt

1. Ein BISAC-Code der Quelle (DNB, OverDrive), wenn er auf der Liste steht.
2. Sonst das Modell, das aus der Liste wählt. Die Liste geht **nicht** in den
   Fingerabdruck ein: der Bestand wird vorher migriert, die Steckbriefe bleiben
   gültig.

Mehrere Codes je Buch zählen alle.

### Migration des Bestands

Je Steckbrief: BISAC der Quelle; sonst eine einmalige Stichwortregel vom
Freitext auf den Code, deren Übersicht die Leserin vor dem Schreiben durchsieht;
was übrig bleibt, bekommt das „General" seiner Gruppe oder kein Genre. Kein
Modellaufruf; der Freitext bleibt daneben stehen. Danach erst wählt das Modell
selbst aus der Liste.

### Genres und Autor:innen im Profil

- **Abgeleitet aus den Büchern**, bestätigt von der Leserin: die Genres und
  Autor:innen der geliebten Bücher als Vorschläge für „gemocht", die der
  Doof-Bücher für „nicht gemocht". Ein einzelnes Buch sperrt nichts von selbst.
- **Frei ergänzbar und änderbar** in der Erstaufnahme und auf der Profilseite —
  die Ausnahme von „nur über Bücher" (ADR 33), weil ein Genre eine Kategorie
  ist und eine Autor:in ein Name, keine Eigenschaft eines Buchs.
- **Gemochtes Genre:** ein kleiner Bonus im Urteil (kleiner als ein
  verstärktes Merkmal); auf ausdrücklichen Wunsch auch ein Thema, das gefegt
  wird.
- **Gemochte Autor:in:** ein Entdeckungskanal, wöchentlich, je Autor:in auf
  täglich zu stellen; ihre Folgebände sind keine Folgebände im Sinne von
  `MidSeries`. Kein Merkmal fürs Urteil.
- **Nicht gemocht** — Genre wie Autor:in: der Fund wird nicht vorgeschlagen,
  eine harte Regel wie die Fremdsprache.
- **Hierarchie:** ein Genre gilt für alle Untergenres darunter, ein
  Untergenre nur für sich. Für „nicht gemocht" reicht ein Treffer unter den
  Codes eines Buchs; der Bonus zählt einmal.
- Ein Buch **ohne** Code hat kein Genre: weder gesperrt noch begünstigt.
- Gegengewichte „nur bei Genre" zeigen auf denselben Code.

## Erwogen und verworfen

- **Synonymtabelle zum Freitext:** eine Tretmühle, nach 80 Einträgen fehlte
  ein Drittel.
- **Eine Liste aus dem Bestand:** nicht objektiv.
- **Thema (EDItEUR)** statt BISAC: deutsche Bezeichnungen, aber in keiner
  Quelle unserer Daten; eine offizielle Zuordnung BISAC → Thema gibt es, falls
  es später gebraucht wird.
- **Die Übersetzung in der Liste** (`quellen:` am Eintrag): jede neue Quelle
  hätte jeden Eintrag angefasst.
- **Nur der erste Code zählt:** die Reihenfolge der Codes ist nicht festgelegt.
- **Ein nicht gemochtes Genre als Abzug:** „Liebesroman will ich nicht" ist
  eine klare Aussage.
