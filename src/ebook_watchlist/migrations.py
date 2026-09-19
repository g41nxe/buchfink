"""Keeping an existing snapshots.db usable across schema changes.

SQLAlchemy's ``create_all`` adds missing *tables* but never touches an existing
one, so a new column on a live database would simply not appear and every query
touching it would fail. That is the whole gap this module closes.

The version counter is SQLite's own ``PRAGMA user_version`` — a slot that
already exists in every database file, so tracking it costs no schema of our
own. ``MIGRATIONS[n]`` upgrades a database at version ``n`` to ``n + 1``; a
database created from scratch is stamped at the current version and skips them
all, because ``create_all`` has already built the finished schema.

Alembic does all this and generates the steps for you. It is the right tool once
Phase 2 moves the Profile and the Watchlist into the database and the contents
stop being reproducible; while the store holds nothing but a rebuildable
Snapshot, thirty lines here are the cheaper trade (ADR 5, ADR 10).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from sqlalchemy import Connection, Engine, inspect

from .cleaning import clean_blurb, without_teaser

Migration = Callable[[Connection], None]


class SchemaTooNew(Exception):
    """The file was written by a newer version of this program."""


def _has_table(connection: Connection, table: str) -> bool:
    """Ob es die Tabelle ueberhaupt (noch) gibt.

    Eine Migration beschreibt die Welt, in der sie geschrieben wurde. Wird ihre
    Tabelle spaeter fallengelassen, muss sie wirkungslos werden statt zu
    scheitern — entfernen darf man sie nicht, das verschoebe die Indizes.
    """
    rows = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return rows.first() is not None


def _columns(connection: Connection, table: str) -> set[str]:
    return {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def add_column(connection: Connection, table: str, column: str, ddl: str) -> None:
    """``ALTER TABLE … ADD COLUMN``, skipped when the column is already there.

    Idempotent on purpose: a half-applied migration must be safe to re-run.
    """
    if column not in _columns(connection, table):
        connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _backfill_seeded_scopes(connection: Connection) -> None:
    """Teach an existing database which discovery scopes it has already seen.

    Without this, the first Run after the upgrade would find no seeded scopes,
    treat every shelf as brand new and swallow a day of genuine arrivals. On a
    real database from before this change that was 163 titles.

    The match reasons are spelled out rather than imported: a migration describes
    what the world looked like when it was written, and must keep doing the same
    thing however the enum grows later.
    """
    # Die Tabelle gibt es seit Ticket 05 nicht mehr — ``interest_seeded`` hat
    # sie abgeloest. Diese Migration bleibt trotzdem in der Kette stehen und
    # wird nur wirkungslos, wenn ihre Tabelle fehlt: die Indizes duerfen sich
    # nicht verschieben, sonst wuerde ein Datenbestand mittlerer Version die
    # falschen Schritte ueberspringen.
    #
    # Ohne diese Pruefung scheiterte jedes Upgrade von Version 0 an einer
    # Tabelle, die ``create_all`` nicht mehr anlegt.
    if not _has_table(connection, "seeded_scope"):
        return
    connection.exec_driver_sql(
        """
        INSERT OR IGNORE INTO seeded_scope (profile_slug, source, match_reason, category)
        SELECT DISTINCT profile_slug, source, match_reason, COALESCE(category, '')
        FROM observation
        WHERE match_reason IN ('profile_author', 'genre_category')
        """
    )


def _add_blurb_columns(connection: Connection) -> None:
    """Room for the blurb, subtitle and series we had been discarding.

    All three ride along on pages the Run already fetches, and they are the only
    signal from which cat-and-mouse, isolated settings and tone can be read at
    all (ADR 17). Existing rows stay NULL — history cannot be backfilled, which
    is precisely why the columns arrive now rather than when the classifier is
    built.
    """
    for column in ("blurb", "subtitle", "series"):
        add_column(connection, "observation", column, "TEXT")


#: Index ``n`` upgrades a database at version ``n``. Append only, never reorder.
def _add_isbn_column(connection: Connection) -> None:
    """The identifier ADR 18 makes book identity out of.

    Both Sources hand it over on pages the Run already fetches - beam in the
    tile order number, the Onleihe in a labelled row - so it costs no extra
    request. Existing rows stay NULL; history cannot be backfilled.
    """
    add_column(connection, "observation", "isbn", "TEXT")


def _add_book_id_column(connection: Connection) -> None:
    """Der Bezugspunkt, der ``watchlist_key`` abloest (ADR 18).

    Bestehende Zeilen bleiben NULL. Ein Backfill waere Ratearbeit: der alte
    Schluessel ist ``titel|autor`` in Kleinschreibung und traegt keine ISBN,
    also liesse er sich nur ueber denselben Matcher auf ein Buch abbilden, den
    wir gerade erst einfuehren. Die Historie verliert dadurch nichts - sie
    behaelt ihren ``watchlist_key``.
    """
    add_column(connection, "observation", "book_id", "INTEGER")


def _drop_resolution_table(connection: Connection) -> None:
    """``resolution`` geht in ``book_source`` auf (ADR 18, Ticket 04).

    Die Zeilen werden bewusst *nicht* uebernommen. Ihr Schluessel ist
    ``titel|autor`` in Kleinschreibung, und daraus ein Buch zu bauen haette
    Buecher mit kleingeschriebenen Titeln erzeugt, die der Leserin dauerhaft so
    angezeigt wuerden. Die Tabelle ist ein Cache: was hier verlorengeht, ist
    ein Suchlauf je Eintrag und Quelle - bei 24 Zeilen und der Hoeflichkeitspause
    gut eine Minute, einmalig. Ein dauerhaft haesslicher Titel waere teurer.

    Beobachtungen sind davon nicht beruehrt; die Historie bleibt vollstaendig.
    """
    connection.exec_driver_sql("DROP TABLE IF EXISTS resolution")


def _add_cover_column(connection: Connection) -> None:
    """Der Dateiname des lokal abgelegten Titelbilds (Ticket 15)."""
    add_column(connection, "book", "cover_file", "TEXT")


def _drop_seeded_scope_table(connection: Connection) -> None:
    """``seeded_scope`` geht in ``interest_seeded`` auf (Ticket 05).

    Nicht uebernommen: der alte Schluessel liess ``category`` bei Autor:innen
    leer, so dass *alle* Autor:innen sich eine Zeile teilten. Aus einer Zeile,
    die nichts unterscheidet, laesst sich nicht rekonstruieren, welche
    Autor:in schon einmal gefegt wurde — das ist genau der Fehler, den die
    neue Tabelle behebt.

    Die Folge ist einmalig sichtbar: nach dem Umstieg saeen alle Interessen
    neu an, also bleibt genau ein Lauf still. Ein geratener Backfill haette
    stattdessen dauerhaft falsche Aussaat behauptet.
    """
    connection.exec_driver_sql("DROP TABLE IF EXISTS seeded_scope")


def _add_run_pid_column(connection: Connection) -> None:
    """Which process is doing a Run, so an abandoned one can be told from a live one.

    An unfinished run row means "started and never wrote an ending", which a
    killed process and a Run still working produce alike. Existing rows stay
    NULL and are therefore judged by their age instead — the pid of a process
    that ended before this column existed cannot be recovered (Ticket 10).
    """
    add_column(connection, "run", "pid", "INTEGER")


def _add_rating_origin(connection: Connection) -> None:
    """Woher ein Urteil stammt (Ticket 21).

    Die Tabelle wird neu gebaut statt ergaenzt: der alte eindeutige Schluessel
    lag auf ``subject`` allein, und genau der muss fallen — sonst koennten das
    Urteil der Leserin und das des Modells nicht nebeneinander stehen, und eins
    wuerde das andere ueberschreiben. SQLite kann eine Eindeutigkeit nicht
    aendern, also gibt es dafuer keinen kleineren Weg.

    Bestehende Zeilen wandern mit und gelten als Modellurteile — die einzige
    Herkunft, die es bis hierher gab.

    Die Spalte heißt hier weiterhin ``rubric_version``. Sie wird erst von der
    *naechsten* Migration umbenannt, und eine Migration muss weiter tun, was sie
    tat, als sie geschrieben wurde (ADR 16) — sonst liest sie aus einer alten
    Datenbank eine Spalte, die es dort noch nicht gibt.
    """
    if not _has_table(connection, "rating"):
        return
    if "origin" in _columns(connection, "rating"):
        return
    connection.exec_driver_sql("ALTER TABLE rating RENAME TO rating_old")
    connection.exec_driver_sql(
        """
        CREATE TABLE rating (
            id INTEGER NOT NULL PRIMARY KEY,
            subject VARCHAR NOT NULL,
            origin VARCHAR NOT NULL,
            stars INTEGER NOT NULL,
            confidence VARCHAR NOT NULL,
            reason VARCHAR NOT NULL,
            rubric_version INTEGER NOT NULL,
            rated_at DATETIME NOT NULL,
            CONSTRAINT uq_rating UNIQUE (subject, origin)
        )
        """
    )
    connection.exec_driver_sql(
        """
        INSERT INTO rating (id, subject, origin, stars, confidence, reason,
                            rubric_version, rated_at)
        SELECT id, subject, 'model', stars, confidence, reason,
               rubric_version, rated_at
        FROM rating_old
        """
    )
    connection.exec_driver_sql("DROP TABLE rating_old")


def _rename_rubric_version(connection: Connection) -> None:
    """``rubric_version`` heißt ``profile_version`` (ADR 21, Ticket 25).

    Der alte Name behauptete, ein Urteil hänge am *Maßstab* — an dem Dokument
    also, das inzwischen das Verfahren ist und ausdrücklich keine Bewertung
    entwertet. Es hängt am Leseprofil, und der Name sagt das jetzt.

    Eine reine Umbenennung, kein Neubau: SQLite kann ``RENAME COLUMN`` seit
    3.25 (ADR 16).
    """
    if not _has_table(connection, "rating"):
        return
    spalten = _columns(connection, "rating")
    if "profile_version" in spalten or "rubric_version" not in spalten:
        return
    connection.exec_driver_sql(
        "ALTER TABLE rating RENAME COLUMN rubric_version TO profile_version"
    )


def _add_rating_pitch(connection: Connection) -> None:
    """Der Satz, der die Leserin hinsehen lässt — neben der Begründung.

    Eine eigene Spalte und kein Anhängsel an ``reason``: die beiden haben
    verschiedene Adressaten, und zusammengelegt hätte der Digest entweder ein
    Protokoll gezeigt oder die Begründung ihre Prüfbarkeit verloren.
    """
    if not _has_table(connection, "rating"):
        return
    add_column(connection, "rating", "pitch", "VARCHAR NOT NULL DEFAULT ''")


def _add_observation_cover_url(connection: Connection) -> None:
    """Die Adresse des Titelbilds mitschreiben (Ticket 15, nachgereicht).

    Der Parser liest sie seit jeher aus der Kachel, die Quelle setzt sie auf
    die Beobachtung — und hier ging sie verloren, weil es die Spalte nicht gab.
    Für Watchlist-Titel fiel das nicht auf: dort holt derselbe Lauf das Bild,
    solange das Feld noch im Speicher steht. Für eine Entdeckung war sie nach
    dem Lauf weg, und ein Bild liess sich nachträglich nur über die
    Detailseite wiederfinden — eine Anfrage je Buch für etwas, das schon
    dagewesen war.

    Nicht rückwirkend zu füllen: was ein Shop vor drei Wochen als Bildadresse
    nannte, weiss heute niemand mehr. Die nächsten Läufe tragen sie ein.
    """
    add_column(connection, "observation", "cover_url", "TEXT")


def _add_dnb_columns(connection: Connection) -> None:
    """Platz für das, was nur die DNB weiß (Ticket 42).

    ``dnb_checked_at`` hält auch ein *erfolgloses* Nachfragen fest: neun von
    dreißig Büchern kennt die DNB nicht, und ohne diesen Vermerk würde jeder
    Lauf sie erneut fragen.

    ``book_contains`` bekommt keine Fremdschlüssel-Klausel: SQLite prüft sie
    ohne ``PRAGMA foreign_keys`` ohnehin nicht. Für eine frische Datei legt
    ``create_all`` die Tabelle an; hier steht sie für die bestehenden.
    """
    add_column(connection, "book", "series_index", "TEXT")
    add_column(connection, "book", "language", "TEXT")
    add_column(connection, "book", "dnb_checked_at", "DATETIME")
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS book_contains "
        "(book_id INTEGER NOT NULL, isbn TEXT NOT NULL, "
        "PRIMARY KEY (book_id, isbn))"
    )


def _dnb_is_keyed_by_isbn(connection: Connection) -> None:
    """Die DNB-Auskunft gehört an die ISBN, nicht an ein Buch (Ticket 42).

    Der Schritt davor war falsch, und der Fall, der ihn ausgelöst hat, zeigt
    es: „David Hunter: 3in1 Bundle" ist bei uns **kein Buch**. Eine
    ``book``-Zeile entsteht erst durch eine Entscheidung der Leserin (ADR 18),
    ein Fund hat keine. ``book_contains(book_id, …)`` konnte damit ausgerechnet
    die Sammelausgabe nicht speichern, für die es gebaut wurde.

    Die DNB antwortet ohnehin über eine ISBN. Danach wird jetzt geschlüsselt —
    dann gilt die Antwort für Bücher und Funde gleichermaßen.

    Angehängt statt eingeschoben: eine Datei auf Version 13 muss denselben Weg
    gehen wie eine neue (ADR 16).
    """
    connection.exec_driver_sql("DROP TABLE IF EXISTS book_contains")
    for spalte in ("series_index", "language", "dnb_checked_at"):
        if spalte in _columns(connection, "book"):
            connection.exec_driver_sql(f"ALTER TABLE book DROP COLUMN {spalte}")
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS dnb_record ("
        "isbn TEXT PRIMARY KEY, checked_at DATETIME NOT NULL, found INTEGER NOT NULL, "
        "title TEXT, subtitle TEXT, author TEXT, series TEXT, series_index TEXT, "
        "language TEXT)"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS dnb_contains ("
        "isbn TEXT NOT NULL, contained TEXT NOT NULL, PRIMARY KEY (isbn, contained))"
    )


def _blurb_stands_once(connection: Connection) -> None:
    """Der doppelte Klappentext, einmal (Ticket 40).

    Der Parser nahm ``get_text()`` ueber den Elternknoten und damit den
    sichtbaren Anriss **und** den eingeklappten vollen Text. 110 der 116
    langen Klappentexte stehen deshalb doppelt in der Datenbank, im Median zu
    einem Drittel Ballast — 71.313 Zeichen, die in jeden Bewertungs-Prompt
    gehen.

    Von selbst geht das nie weg: nachgeladen wird nur, was auf "…" endet, und
    ein doppelter Text endet auf dem vollen. **Null** der 110 gelten als
    abgeschnitten, 102 Buecher blieben also fuer immer so.

    Umgeschrieben statt angehaengt, und das ist Absicht. Das Append-only aus
    ADR 5 schuetzt die *Zeitreihe* — Preis und Verfuegbarkeit, was der Shop
    wann gesagt hat. Der Klappentext ist keine: ``diff.py`` erwaehnt ihn
    nirgends, niemand vergleicht ihn ueber die Zeit. Und korrigiert wird
    nicht, was der Shop gesagt hat, sondern **unser Lesefehler beim
    Einsammeln**. Eine kaputt geparste Spalte zu reparieren ist eine
    Migration, keine Geschichtsfaelschung.

    Der Schnitt ist verlustfrei: in 110 von 110 beginnt der volle Text mit dem
    Anriss, in keinem einzigen ist er kuerzer.
    """
    zeilen = connection.exec_driver_sql(
        "SELECT id, blurb FROM observation WHERE blurb LIKE '%alles anzeigen%'"
    ).fetchall()
    for zeile_id, blurb in zeilen:
        gekuerzt = without_teaser(blurb)
        if gekuerzt and gekuerzt != blurb:
            connection.exec_driver_sql(
                "UPDATE observation SET blurb = ? WHERE id = ?", (gekuerzt, zeile_id)
            )


def _reception_was_a_detour(connection: Connection) -> None:
    """Eine eigene Tabelle fuer fremde Stimmen — und wieder zurueck (Ticket 54).

    Diese Nummer tut **nichts** und bleibt trotzdem stehen. Sie hat einmal
    ``reception`` angelegt, geschluesselt nach ``(subject, source)`` — eine
    Achse zu viel, denn ``rating`` traegt seit ADR 19 genau diesen Schluessel
    als ``(subject, origin)``, und eine weitere Quelle ist dort eine weitere
    Herkunft, kein zweites Schema.

    Sie zu **ersetzen** war der eigentliche Fehler: jede Datei, die sie schon
    gelaufen war, ueberspringt den Nachfolger fuer immer (ADR 16). Genau das
    ist passiert und hat ``rating.votes`` auf einer Datei mit
    ``user_version = 17`` fehlen lassen. Aufgeraeumt wird deshalb angehaengt,
    in ``_the_detour_leaves_no_table``.
    """


def _observation_carries_the_vote(connection: Connection) -> None:
    """Was die Quelle ueber die Stimmen sagte, als sie es sagte (Ticket 54).

    Zwei ganze Zahlen je Zeile — anders als der Klappentext, dessen
    Mitschreiben rund zehn Megabyte im Jahr kostete. Und anders als dieser ist
    es eine echte Zeitreihe: eine Durchschnittsnote wandert, und wann sie
    wanderte, ist eine Auskunft.
    """
    add_column(connection, "observation", "rating", "INTEGER")
    add_column(connection, "observation", "rating_votes", "INTEGER")


def _how_many_voted(connection: Connection) -> None:
    """Auf wie vielen Stimmen eine fremde Bewertung ruht (Ticket 54).

    Fuer die eigenen Urteile bedeutungslos — dort steht *eine* Stimme, die des
    Modells oder der Leserin. Fuer eine Bibliotheks- oder Shop-Bewertung ist
    die Zahl der halbe Wert der Angabe: 5,0 aus einer Stimme ist keine
    Auskunft, 2,8 aus 1641 schon. Gemessen an Google Books liegt der Median
    unserer Buecher bei **einer** Stimme
    (``docs/research/reader-ratings-sources.md``).

    Eine Spalte statt einer eigenen Tabelle: ``rating`` ist bereits nach
    ``(subject, origin)`` geschluesselt (ADR 19).
    """
    add_column(connection, "rating", "votes", "INTEGER")


def _the_detour_leaves_no_table(connection: Connection) -> None:
    """Die verworfene ``reception``-Tabelle wegraeumen.

    Angehaengt statt in Nummer 16 nachgetragen: eine Datei, die 16 schon
    gelaufen ist, sieht deren neuen Inhalt nie (ADR 16). Genau eine solche
    Datei gibt es.
    """
    connection.exec_driver_sql("DROP TABLE IF EXISTS reception")


def _blurb_without_the_collapse_button(connection: Connection) -> None:
    """Die andere Haelfte des Aufklapp-Knopfs (Ticket 40, Nachtrag).

    Der Shop hat zwei: einen zum Aufklappen vor dem vollen Text ("alles
    anzeigen expand_more") und einen zum Zuklappen dahinter ("weniger anzeigen
    expand_less"). Migration 15 hat den ersten erwischt, den zweiten nicht —
    ``clean_blurb`` streifte zwar die Ligatur ab, liess aber die blossen
    Woerter stehen.

    Gemessen: 110 von 2674 gespeicherten Texten enden auf "weniger anzeigen",
    dieselben 110, die vorher doppelt waren. Aufgefallen ist es beim Lesen
    eines Klappentexts auf dem Entwurf der Buchseite — also genau dort, wo ihn
    zum ersten Mal jemand liest.
    """
    zeilen = connection.exec_driver_sql(
        "SELECT id, blurb FROM observation WHERE blurb IS NOT NULL AND blurb != ''"
    ).fetchall()
    for zeile_id, blurb in zeilen:
        gereinigt = clean_blurb(blurb)
        if gereinigt and gereinigt != blurb:
            connection.exec_driver_sql(
                "UPDATE observation SET blurb = ? WHERE id = ?", (gereinigt, zeile_id)
            )


def _book_carries_its_blurb(connection: Connection) -> None:
    """Platz fuer den Klappentext am Buch (Ticket 52).

    Er ist ein Stammdatum und kein Messwert. In jeder Beobachtung stuende er
    taeglich neu — rund zehn Megabyte im Jahr fuer denselben Text; am Buch
    steht er einmal. Gefuellt wird die Spalte beim naechsten Lauf, aus den
    Beobachtungen, die ohnehin hereinkommen.
    """
    add_column(connection, "book", "blurb", "TEXT")


def _voebb_is_called_onleihe(connection: Connection) -> None:
    """Die Quelle heisst ``onleihe``, nicht ``voebb``.

    Der VOEBB betreibt **zwei** digitale Plattformen mit getrennten Bestaenden:
    die Onleihe unter ``voebb.onleihe.de`` und OverDrive unter
    ``voebb.overdrive.com``. Solange die erste ``voebb`` hiess, meinte der Name
    einen von zwei Katalogen, ohne zu sagen, welchen — gemessen an einem
    Nachmittag, an dem "nicht im Katalog" als Auskunft ueber *den* Katalog
    gelesen wurde und ueber den anderen nichts sagte.

    Der Quellname steht an fuenf Stellen in der Datenbank, und ``observation``
    und ``book_source`` sind darueber geschluesselt — ohne diesen Schritt
    verloere jedes beobachtete Buch seine Geschichte.

    ``voebb_readers`` wird dabei zu ``library_readers``: die Herkunft meint die
    Leserschaft *einer Bibliothek*, nicht die einer bestimmten. So hiess sie
    fuer die Leserin ohnehin immer ("Leser:innen der Bibliothek"), und die
    zweite Bibliothek bringt eigene Stimmen mit.
    """
    for tabelle, spalte, alt, neu in (
        ("observation", "source", "voebb", "onleihe"),
        ("book_source", "source", "voebb", "onleihe"),
        ("interest_seeded", "source", "voebb", "onleihe"),
        ("source", "name", "voebb", "onleihe"),
        ("rating", "origin", "voebb_readers", "library_readers"),
    ):
        # Tabelle *und* Spalte: eine Migration beschreibt die Welt, in der sie
        # geschrieben wurde, und muss in einer aelteren wirkungslos sein statt
        # zu scheitern.
        if not _has_table(connection, tabelle) or spalte not in _columns(connection, tabelle):
            continue
        # ``OR IGNORE``, weil der Quellname bei ``book_source`` und
        # ``interest_seeded`` im Primaerschluessel steht: wer vorher in
        # ``profile.yaml`` schon ``onleihe: {kind: voebb}`` geschrieben hat,
        # traegt beide Namen, und ein Konflikt liesse die ganze Migration
        # zurueckrollen. Die Version bliebe dann auf dem alten Stand, und die
        # Anwendung startete ueberhaupt nicht mehr — ein Preis, den eine
        # Umbenennung nicht wert ist. Die Zeile bleibt dann unter dem alten
        # Namen liegen und wird von niemandem mehr gefunden, was folgenlos ist:
        # eine Quelle dieses Namens gibt es nicht mehr.
        #
        # Tabellen- und Spaltennamen stehen als Literale in der Zeile darueber,
        # nur die Werte sind gebunden.
        connection.exec_driver_sql(
            f"UPDATE OR IGNORE {tabelle} SET {spalte} = ? WHERE {spalte} = ?",  # noqa: S608
            (neu, alt),
        )

    # Urteile ueber einen Fund ohne ISBN haengen am Quellnamen
    # (``item:<quelle>:<nummer>``, siehe ``ratings.subject_of``). In dieser
    # Installation gibt es keine solche Zeile, in einer anderen schon.
    if _has_table(connection, "rating") and "subject" in _columns(connection, "rating"):
        connection.exec_driver_sql(
            "UPDATE rating SET subject = 'item:onleihe:' || substr(subject, 12) "
            "WHERE subject LIKE 'item:voebb:%'"
        )


def _library_readers_are_named_per_library(connection: Connection) -> None:
    """Die Leserstimmen heissen wieder nach ihrer Bibliothek.

    Der Schritt davor machte aus ``voebb_readers`` ein generisches
    ``library_readers`` — mit dem Gedanken, die Herkunft meine "irgendeine
    Bibliothek". Das war falsch, und zwar auf eine Art, die erst mit der
    zweiten Bibliothek weh getan haette:

    Ein Urteil haengt an der ISBN, sobald es eine gibt (``ratings.subject_of``);
    der Quellname faellt dann aus dem Schluessel. ``rating`` ist ueber
    ``(subject, origin)`` eindeutig, also schrieben zwei Bibliotheken fuer
    dieselbe ISBN in **dieselbe Zeile** — die zweite ueberschriebe die erste bei
    jedem Lauf, stumm und je nach Reihenfolge der Quellen. Alle fuenf Zeilen im
    echten Bestand sind ISBN-Zeilen; es waere nicht der Randfall gewesen,
    sondern der Normalfall.

    Ein eigener Schritt statt einer Korrektur am vorigen: eine Installation ist
    bereits auf Version 22 gelaufen, und eine nachtraeglich geaenderte Migration
    haette sie nie erreicht.
    """
    if not _has_table(connection, "rating") or "origin" not in _columns(connection, "rating"):
        return
    connection.exec_driver_sql(
        "UPDATE OR IGNORE rating SET origin = 'onleihe_readers' WHERE origin = 'library_readers'"
    )


def _book_carries_its_volume(connection: Connection) -> None:
    """Der Band innerhalb der Reihe, neben der Reihe (#10).

    Die Reihe hatte ihre Spalte laengst, sie blieb nur leer; der Band hatte
    keine. Gefuellt wird beides beim naechsten Lauf aus der DNB-Auskunft,
    die schon in der Datenbank liegt — hier wird nichts nachgeholt.
    """
    add_column(connection, "book", "series_index", "TEXT")


def _a_judgement_knows_its_way(connection: Connection) -> None:
    """Auf welchem Weg ein Modellurteil entstand (#10).

    Aeltere Urteile bleiben leer: welcher Weg es war, weiss niemand mehr, und
    ein geratener Wert waere schlechter als keiner.
    """
    add_column(connection, "rating", "via", "TEXT")


MIGRATIONS: tuple[Migration, ...] = (
    _backfill_seeded_scopes,
    _add_blurb_columns,
    _add_isbn_column,
    _add_book_id_column,
    _drop_resolution_table,
    _add_cover_column,
    _drop_seeded_scope_table,
    # Angehaengt, nie eingeschoben: der Zaehler ist die Version einer
    # bestehenden Datei, und eine verschobene Reihenfolge liesse einen
    # Datenbestand mittlerer Version die falschen Schritte ueberspringen.
    _add_run_pid_column,
    _add_rating_origin,
    _rename_rubric_version,
    _add_rating_pitch,
    _add_observation_cover_url,
    _add_dnb_columns,
    _dnb_is_keyed_by_isbn,
    _blurb_stands_once,
    _reception_was_a_detour,
    _observation_carries_the_vote,
    _how_many_voted,
    _the_detour_leaves_no_table,
    _blurb_without_the_collapse_button,
    _book_carries_its_blurb,
    _voebb_is_called_onleihe,
    _library_readers_are_named_per_library,
    _book_carries_its_volume,
    _a_judgement_knows_its_way,
)

SCHEMA_VERSION = len(MIGRATIONS)


def _version(connection: Connection) -> int:
    return int(connection.exec_driver_sql("PRAGMA user_version").scalar_one())


def _stamp(connection: Connection, version: int) -> None:
    # PRAGMA takes no bound parameters, hence the literal; version is our own int.
    connection.exec_driver_sql(f"PRAGMA user_version = {int(version)}")


def migrate(engine: Engine, metadata, migrations: Sequence[Migration] = MIGRATIONS) -> None:
    """Bring the database at ``engine`` up to the current schema."""
    fresh = not inspect(engine).get_table_names()
    metadata.create_all(engine)

    with engine.begin() as connection:
        target = len(migrations)
        if fresh:
            # create_all just built the finished schema; there is nothing to upgrade.
            _stamp(connection, target)
            return

        version = _version(connection)
        if version > target:
            raise SchemaTooNew(
                f"snapshots.db is at schema version {version}, this program knows {target} "
                "— it was written by a newer version of ebook-watchlist"
            )
        for migration in migrations[version:]:
            migration(connection)
        _stamp(connection, target)


__all__ = ["MIGRATIONS", "SCHEMA_VERSION", "SchemaTooNew", "add_column", "migrate"]
