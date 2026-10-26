"""Was die Leserin sagt und was über sie gerechnet wird: Einstellungen, Urteile,
Steckbriefe, Leseprofil, Erstaufnahme, Beziehungen und Interessen (#103)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime

from sqlalchemy import (
    func,
    select,
)
from sqlalchemy.exc import IntegrityError

from ..judging.facets import Counterweight, Facet, Liked, ReadingProfile
from ..judging.portrait import Portrait
from ..judging.ratings import RATING_ORIGINS
from ..relations import check_details, check_interest_key, check_relation_kind
from .catalog import CatalogMixin
from .rows import (
    _BEST_PORTRAIT_FIRST,
    _VERSION_ATTEMPTS,
    BookRelationRow,
    IntakeChoiceRow,
    IntakeEntryRow,
    InterestRow,
    InterestSeededRow,
    PortraitRow,
    RatingRow,
    ReadingProfileRow,
    SettingRow,
    _portrait_of,
    _work_book_subjects,
    _work_subjects,
)


class ProfileMixin(CatalogMixin):
    """Was die Leserin sagt und was über sie gerechnet wird: Einstellungen, Urteile,"""

    # --- Einstellungen (#104) ----------------------------------------------

    def saved_settings(self, profile_slug: str) -> dict:
        """Was die Leserin in der Oberfläche eingestellt hat."""
        with self.session() as session:
            rows = session.scalars(
                select(SettingRow).where(SettingRow.profile_slug == profile_slug)
            ).all()
            return {row.key: json.loads(row.value) for row in rows}

    def save_settings(self, profile_slug: str, values: dict, *, now: datetime) -> None:
        """Einstellungen setzen; ``None`` nimmt eine zurück — dann gilt die Datei."""
        with self.session() as session:
            for key, value in values.items():
                row = session.get(SettingRow, (profile_slug, key))
                if value is None:
                    if row is not None:
                        session.delete(row)
                    continue
                if row is None:
                    row = SettingRow(profile_slug=profile_slug, key=key)
                    session.add(row)
                row.value = json.dumps(value)
                row.updated_at = now
            session.commit()

    # --- Bewertungen (Ticket 12) -------------------------------------------

    def rating(self, subject: str, *, origin: str) -> RatingRow | None:
        """Das gespeicherte Urteil einer Herkunft, oder keines.

        Gespeichert wird nur, was ein Mensch oder fremde Leser:innen sagen; das
        Urteil der Anwendung wird gerechnet (ADR 33). Beides verfällt nicht mit
        einer neuen Profilfassung, und deshalb fragt niemand mehr nach einer.
        """
        with self.session() as session:
            # Ihre Sterne gelten dem Werk (ADR 36): steht an dieser Ausgabe
            # keiner, zählt der einer anderen.
            group = _work_book_subjects(session, [subject])[subject]
            rows = {
                row.subject: row
                for row in session.scalars(
                    select(RatingRow).where(
                        RatingRow.subject.in_(group), RatingRow.origin == origin
                    )
                )
            }
            row = rows.get(subject) or next((rows[s] for s in sorted(rows)), None)
            if row is None:
                return None
            session.expunge(row)
            return row

    def ratings_for(self, subjects: Iterable[str]) -> dict[tuple[str, str], RatingRow]:
        """Alle Urteile zu diesen Schlüsseln, nach ``(Schlüssel, Herkunft)``."""
        wanted = set(subjects)
        if not wanted:
            return {}
        with self.session() as session:
            groups = _work_book_subjects(session, wanted)
            members = {member for group in groups.values() for member in group}
            rows = list(
                session.scalars(select(RatingRow).where(RatingRow.subject.in_(members)))
            )
            for row in rows:
                session.expunge(row)
        found = {(row.subject, row.origin): row for row in rows}
        # Die eigene zuerst, sonst die einer anderen Ausgabe desselben Werks.
        out = {key: row for key, row in found.items() if key[0] in wanted}
        for asked, group in groups.items():
            for member in sorted(group - {asked}):
                for (subject, origin), row in found.items():
                    if subject == member:
                        out.setdefault((asked, origin), row)
        return out

    def drop_rating(self, subject: str, origin: str) -> bool:
        """Ein Urteil zurücknehmen; ``True``, wenn eines dastand.

        Nur die Leserin nimmt zurück, und sie tut es, indem sie ihre eigenen
        Sterne noch einmal anklickt. Eine Null wäre dafür kein Ersatz: sie
        hieße "passt überhaupt nicht" und ist selbst ein Urteil.
        """
        with self.session() as session:
            row = session.scalars(
                select(RatingRow).where(
                    RatingRow.subject == subject, RatingRow.origin == origin
                )
            ).first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def put_rating(
        self,
        subject: str,
        *,
        stars: float,
        confidence: str,
        reason: str,
        profile_version: int,
        now: datetime,
        origin: str,
        votes: int | None = None,
    ) -> None:
        """Ein Urteil festhalten — der Leserin oder fremder Leser:innen.

        Der Schlüssel ist ``(subject, origin)``: beide stehen nebeneinander, und
        keines überschreibt das andere (ADR 17, Ticket 21). Die Anwendung
        speichert kein eigenes Urteil mehr (ADR 33).
        """
        if origin not in RATING_ORIGINS:
            raise ValueError(
                f"unbekannte Herkunft {origin!r} "
                f"(bekannt: {', '.join(sorted(RATING_ORIGINS))})"
            )
        with self.session() as session:
            row = session.scalars(
                select(RatingRow).where(
                    RatingRow.subject == subject, RatingRow.origin == origin
                )
            ).first()
            if row is None:
                row = RatingRow(subject=subject, origin=origin)
                session.add(row)
            row.stars = stars
            row.confidence = confidence
            row.votes = votes
            row.reason = reason
            row.profile_version = profile_version
            row.rated_at = now
            session.commit()

    # --- Steckbriefe (#45) ---------------------------------------------------

    def put_portrait(self, subject: str, portrait: Portrait, *, now: datetime) -> None:
        """Einen Steckbrief festhalten — dazu, nie an Stelle eines alten.

        Ohne Code wird er aus dem freien Genre abgeleitet (#89), damit bis zur
        neuen Anweisung (#90) kein Steckbrief ohne Genre-Code entsteht.
        """
        from ..genre_migration import genre_code
        from ..genres import load_genres

        code = portrait.genre_code or genre_code(portrait.genre, portrait.subgenre)
        with self.session() as session:
            session.add(
                PortraitRow(
                    subject=subject,
                    fingerprint=portrait.fingerprint,
                    created_at=now,
                    known=portrait.known,
                    title=portrait.title,
                    author=portrait.author,
                    original_title=portrait.original_title,
                    genre=portrait.genre,
                    subgenre=portrait.subgenre,
                    pitch=portrait.pitch,
                    traits=json.dumps(
                        [
                            {
                                "term": t.term,
                                "sentence": t.sentence,
                                "evidence": t.evidence,
                                "weight": t.weight,
                            }
                            for t in portrait.traits
                        ],
                        ensure_ascii=False,
                    ),
                    violations=json.dumps(list(portrait.violations), ensure_ascii=False),
                    with_text=portrait.with_text,
                    with_sample=portrait.with_sample,
                    genre_code=code,
                    genre_name=load_genres().name(code),
                    form=portrait.form,
                )
            )
            session.commit()

    def portrait(self, subject: str, fingerprint: str) -> Portrait | None:
        """Der jüngste Steckbrief mit diesem Fingerabdruck, oder keiner.

        Ein Steckbrief mit altem Fingerabdruck gilt nicht mehr: Anweisung oder
        Merkmale haben sich seitdem geändert, und er wird neu angelegt, sobald
        ihn jemand braucht.

        Einer, der mit Text entstand, geht jedem ohne vor, auch einem jüngeren:
        aus dem Gedächtnis hielt das Modell *Gestohlene Erinnerung* für *Dark
        Matter* (26.09.2026). Unter Gleichen gilt der jüngste.
        """
        with self.session() as session:
            # Ein Werk, ein Steckbrief (ADR 36): auch der einer anderen Ausgabe.
            group = _work_subjects(session, [subject])[subject]
            row = session.scalars(
                select(PortraitRow)
                .where(PortraitRow.subject.in_(group), PortraitRow.fingerprint == fingerprint)
                .order_by(*_BEST_PORTRAIT_FIRST)
            ).first()
            if row is None:
                return None
        return self._with_source_codes({subject: _portrait_of(row)})[subject]

    def portraits_for(self, subjects: Iterable[str], fingerprint: str) -> dict[str, Portrait]:
        """Die jüngsten Steckbriefe zu diesen Schlüsseln — ein Zugriff für eine
        ganze Liste statt einer je Zeile (#48)."""
        wanted = set(subjects)
        if not wanted:
            return {}
        with self.session() as session:
            # Je Schlüssel alle Ausgaben seines Werks (ADR 36).
            groups = _work_subjects(session, wanted)
            asked_by: dict[str, set[str]] = {}
            for asked, group in groups.items():
                for member in group:
                    asked_by.setdefault(member, set()).add(asked)
            rows = session.scalars(
                select(PortraitRow)
                .where(PortraitRow.subject.in_(set(asked_by)),
                       PortraitRow.fingerprint == fingerprint)
                .order_by(*_BEST_PORTRAIT_FIRST)
            )
            # Der beste je Schlüssel kommt zuerst und bleibt — dieselbe Regel
            # wie bei :meth:`portrait`.
            best: dict[str, Portrait] = {}
            for row in rows:
                for asked in asked_by[row.subject]:
                    if asked not in best:
                        best[asked] = _portrait_of(row)
        return self._with_source_codes(best)

    def asked_with_text(self, subjects: Iterable[str], fingerprint: str) -> dict[str, int]:
        """Wie oft jeder Schlüssel mit Text beschrieben wurde, je Werk (ADR 36).

        Für den zweiten Versuch bei einem Steckbrief mit Regelverstößen (ADR
        43): einmal, nicht bei jedem Lauf wieder.
        """
        wanted = set(subjects)
        if not wanted:
            return {}
        with self.session() as session:
            groups = _work_subjects(session, wanted)
            members = {member for group in groups.values() for member in group}
            rows = session.execute(
                select(PortraitRow.subject, func.count())
                .where(PortraitRow.subject.in_(members),
                       PortraitRow.fingerprint == fingerprint,
                       PortraitRow.with_text.is_(True))
                .group_by(PortraitRow.subject)
            ).all()
            counts = {subject: count for subject, count in rows}
        return {asked: sum(counts.get(m, 0) for m in group) for asked, group in groups.items()}

    def _with_source_codes(self, portraits: dict[str, Portrait]) -> dict[str, Portrait]:
        """Die BISAC-Codes des Verlags an die Steckbriefe mit ISBN hängen —
        damit Bonus, Gegengewicht und Ausschluss dasselbe Genre sehen (ADR 37)."""
        isbns = {s.removeprefix("isbn:") for s in portraits if s.startswith("isbn:")}
        codes = self.bisac_codes(isbns)
        return {
            subject: replace(p, source_codes=codes.get(subject.removeprefix("isbn:"), ()))
            if subject.startswith("isbn:") else p
            for subject, p in portraits.items()
        }

    # --- Leseprofil aus Facetten (#46) ---------------------------------------

    def put_reading_profile(
        self, profile_slug: str, profile: ReadingProfile, *, cause: str, now: datetime
    ) -> int:
        """Eine neue Fassung des Leseprofils festhalten; gibt ihre Nummer zurück."""
        body = {
            "facets": [
                {"families": list(f.families), "books": list(f.books)} for f in profile.facets
            ],
            "counterweights": [
                {"families": list(c.families), "genre": c.genre, "books": list(c.books)}
                for c in profile.counterweights
            ],
            "liked": [{"family": g.family, "boosted": g.boosted} for g in profile.liked],
            "liked_genres": list(profile.liked_genres),
            "disliked_genres": list(profile.disliked_genres),
            "disliked_authors": list(profile.disliked_authors),
        }
        # Lesen und Schreiben sind zwei Schritte; zwei gleichzeitige Anfragen
        # (ein Doppelklick auf "Übernehmen") greifen nach derselben Nummer. Die
        # Eindeutigkeit steht in der Tabelle, also wird bei einer Kollision mit
        # der nächsten Nummer noch einmal versucht.
        for _ in range(_VERSION_ATTEMPTS):
            with self.session() as session:
                latest = session.scalar(
                    select(func.max(ReadingProfileRow.version)).where(
                        ReadingProfileRow.profile_slug == profile_slug
                    )
                )
                version = (latest or 0) + 1
                session.add(
                    ReadingProfileRow(
                        profile_slug=profile_slug,
                        version=version,
                        created_at=now,
                        cause=cause,
                        body=json.dumps(body, ensure_ascii=False),
                    )
                )
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    continue
            return version
        raise RuntimeError("keine freie Fassungsnummer für das Leseprofil")

    def reading_profile(self, profile_slug: str) -> ReadingProfile | None:
        """Die jüngste Fassung des Leseprofils, oder keine."""
        with self.session() as session:
            row = session.scalars(
                select(ReadingProfileRow)
                .where(ReadingProfileRow.profile_slug == profile_slug)
                .order_by(ReadingProfileRow.version.desc())
            ).first()
            if row is None:
                return None
            body = json.loads(row.body)
            return ReadingProfile(
                facets=tuple(
                    Facet(tuple(f["families"]), tuple(f.get("books") or ()))
                    for f in body.get("facets") or ()
                ),
                counterweights=tuple(
                    Counterweight(
                        tuple(c["families"]), c.get("genre"), tuple(c.get("books") or ())
                    )
                    for c in body.get("counterweights") or ()
                ),
                liked=tuple(
                    Liked(g["family"], bool(g.get("boosted"))) for g in body.get("liked") or ()
                ),
                version=row.version,
                liked_genres=tuple(body.get("liked_genres") or ()),
                disliked_genres=tuple(body.get("disliked_genres") or ()),
                disliked_authors=tuple(body.get("disliked_authors") or ()),
            )

    # --- Erstaufnahme (#47) --------------------------------------------------

    def add_intake_entry(
        self, profile_slug: str, side: str, title: str, author: str | None, *, now: datetime
    ) -> int:
        with self.session() as session:
            row = IntakeEntryRow(
                profile_slug=profile_slug,
                side=side,
                typed_title=title,
                typed_author=author,
                created_at=now,
                status="open",
            )
            session.add(row)
            session.commit()
            return row.id

    def intake_entries(self, profile_slug: str) -> list[IntakeEntryRow]:
        """Die genannten Bücher, ohne die entfernten, in der Reihenfolge der Nennung."""
        with self.session() as session:
            rows = list(
                session.scalars(
                    select(IntakeEntryRow)
                    .where(
                        IntakeEntryRow.profile_slug == profile_slug,
                        IntakeEntryRow.status != "removed",
                    )
                    .order_by(IntakeEntryRow.id)
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def intake_entry(self, entry_id: int) -> IntakeEntryRow | None:
        with self.session() as session:
            row = session.get(IntakeEntryRow, entry_id)
            if row is not None:
                session.expunge(row)
            return row

    def update_intake_entry(self, entry_id: int, **fields: object) -> None:
        """Was die Leserin mit einem Eintrag getan hat: neu eingegeben,
        bestätigt, entfernt."""
        allowed = {"typed_title", "typed_author", "status", "book_id"}
        if not set(fields) <= allowed:
            raise ValueError(f"nicht änderbar: {sorted(set(fields) - allowed)}")
        with self.session() as session:
            row = session.get(IntakeEntryRow, entry_id)
            if row is None:
                raise KeyError(entry_id)
            for name, value in fields.items():
                setattr(row, name, value)
            session.commit()

    def set_intake_choice(
        self,
        profile_slug: str,
        side: str,
        family_id: str,
        *,
        book_id: int | None = None,
        active: bool = True,
        scope: str | None = None,
    ) -> None:
        """Eine Familie an- oder abwählen; der Umfang bleibt, wenn keiner kommt."""
        with self.session() as session:
            row = session.scalars(
                select(IntakeChoiceRow).where(
                    IntakeChoiceRow.profile_slug == profile_slug,
                    IntakeChoiceRow.side == side,
                    IntakeChoiceRow.family_id == family_id,
                    IntakeChoiceRow.book_id.is_(None)
                    if book_id is None
                    else IntakeChoiceRow.book_id == book_id,
                )
            ).first()
            if row is None:
                row = IntakeChoiceRow(
                    profile_slug=profile_slug, side=side, family_id=family_id, book_id=book_id
                )
                session.add(row)
            row.active = active
            if scope is not None:
                row.scope = scope
            session.commit()

    def intake_choices(self, profile_slug: str) -> list[IntakeChoiceRow]:
        """Die angetippten Familien, in der Reihenfolge des ersten Antippens."""
        with self.session() as session:
            rows = list(
                session.scalars(
                    select(IntakeChoiceRow)
                    .where(
                        IntakeChoiceRow.profile_slug == profile_slug,
                        IntakeChoiceRow.active.is_(True),
                    )
                    .order_by(IntakeChoiceRow.id)
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def reset_intake(self, profile_slug: str) -> None:
        """Neu anfangen: Einträge und Antworten wirken nicht mehr.

        Nichts wird gelöscht (ADR 5); bestätigte Bücher bleiben im Regal, dort
        nimmt man sie auf der Buchseite zurück.
        """
        with self.session() as session:
            for row in session.scalars(
                select(IntakeEntryRow).where(IntakeEntryRow.profile_slug == profile_slug)
            ):
                row.status = "removed"
            for row in session.scalars(
                select(IntakeChoiceRow).where(IntakeChoiceRow.profile_slug == profile_slug)
            ):
                row.active = False
            session.commit()

    def high_water(self) -> tuple[int, int]:
        """Die höchste Nummer bei Steckbriefen und Beziehungen — billig zu
        fragen, und sie wächst mit jeder neuen Zeile. Woran ein Zwischenspeicher
        merkt, dass er veraltet ist (#58)."""
        with self.session() as session:
            portraits = session.scalar(select(func.max(PortraitRow.id))) or 0
            relations = session.scalar(select(func.max(BookRelationRow.id))) or 0
            return portraits, relations

    def latest_portraits(self, fingerprint: str) -> dict[str, Portrait]:
        """Der jüngste Steckbrief je Gegenstand mit diesem Fingerabdruck.

        Für die Häufigkeit der Familien auf dem neutralen Bestand (#50): was
        die Buchseite, der Lauf oder die Erstaufnahme angelegt haben.
        """
        with self.session() as session:
            rows = session.scalars(
                select(PortraitRow)
                .where(PortraitRow.fingerprint == fingerprint)
                .order_by(PortraitRow.created_at, PortraitRow.id)
            )
            return {row.subject: _portrait_of(row) for row in rows}

    # --- Beziehungen und Interessen (Ticket 05) ----------------------------

    def put_relation(
        self,
        profile_slug: str,
        book_id: int,
        kind: str,
        *,
        active: bool = True,
        now: datetime,
        **details: object,
    ) -> None:
        """Was die Leserin zu einem Buch sagt. Mehrere Arten gelten gleichzeitig."""
        check_relation_kind(kind)
        check_details(kind, dict(details))
        with self.session() as session:
            row = session.scalars(
                select(BookRelationRow).where(
                    BookRelationRow.profile_slug == profile_slug,
                    BookRelationRow.book_id == book_id,
                    BookRelationRow.kind == kind,
                )
            ).first()
            if row is None:
                row = BookRelationRow(
                    profile_slug=profile_slug,
                    book_id=book_id,
                    kind=kind,
                    created_at=now,
                )
                session.add(row)
            row.active = active
            if details:
                row.details = json.dumps(details, ensure_ascii=False)
            session.commit()

    def set_relation_details(
        self, profile_slug: str, book_id: int, kind: str, details: dict, *, now: datetime
    ) -> None:
        """Den Beutel *ersetzen*, auch wenn er leer wird.

        ``put_relation`` laesst vorhandene Angaben in Ruhe, wenn der Aufrufer
        keine mitgibt — sonst loeschte jedes Pausieren die Notizen. Wer etwas
        wegnehmen will, braucht deshalb diesen Weg: sonst liesse sich eine
        Einschraenkung setzen, aber nie wieder aufheben.
        """
        check_relation_kind(kind)
        check_details(kind, details)
        with self.session() as session:
            row = session.scalars(
                select(BookRelationRow).where(
                    BookRelationRow.profile_slug == profile_slug,
                    BookRelationRow.book_id == book_id,
                    BookRelationRow.kind == kind,
                )
            ).first()
            if row is None:
                row = BookRelationRow(
                    profile_slug=profile_slug, book_id=book_id, kind=kind, created_at=now
                )
                session.add(row)
                row.active = True
            row.details = json.dumps(details, ensure_ascii=False)
            session.commit()

    def relations(
        self, profile_slug: str, *, kind: str | None = None, active_only: bool = True
    ) -> list[BookRelationRow]:
        with self.session() as session:
            stmt = select(BookRelationRow).where(BookRelationRow.profile_slug == profile_slug)
            if kind is not None:
                stmt = stmt.where(BookRelationRow.kind == kind)
            if active_only:
                stmt = stmt.where(BookRelationRow.active.is_(True))
            rows = list(session.scalars(stmt.order_by(BookRelationRow.id)))
            for row in rows:
                session.expunge(row)
            return rows

    def relations_of(self, profile_slug: str, book_id: int) -> list[BookRelationRow]:
        with self.session() as session:
            rows = list(
                session.scalars(
                    select(BookRelationRow).where(
                        BookRelationRow.profile_slug == profile_slug,
                        BookRelationRow.book_id == book_id,
                    )
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def deactivate_relation(
        self, profile_slug: str, book_id: int, kind: str, *, now: datetime
    ) -> None:
        """Beziehungen werden deaktiviert, nicht geloescht — die Tatsache, dass
        ein Buch einmal beobachtet wurde, ist selbst eine Auskunft (ADR 18).

        Die Uhr wird uebergeben, nicht gelesen: ein Store, der selbst nach der
        Zeit sieht, laesst sich nicht mit einer festen Uhr pruefen.
        """
        self.put_relation(profile_slug, book_id, kind, active=False, now=now)

    def put_interest(
        self,
        profile_slug: str,
        key: str,
        value: str,
        *,
        active: bool = True,
        now: datetime,
        **details: object,
    ) -> InterestRow:
        check_interest_key(key)
        check_details(key, dict(details))
        with self.session() as session:
            row = session.scalars(
                select(InterestRow).where(
                    InterestRow.profile_slug == profile_slug,
                    InterestRow.key == key,
                    InterestRow.value == value,
                )
            ).first()
            if row is None:
                row = InterestRow(
                    profile_slug=profile_slug, key=key, value=value, created_at=now
                )
                session.add(row)
            row.active = active
            if details:
                row.details = json.dumps(details, ensure_ascii=False)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    def interests(
        self, profile_slug: str, *, key: str | None = None, active_only: bool = True
    ) -> list[InterestRow]:
        with self.session() as session:
            stmt = select(InterestRow).where(InterestRow.profile_slug == profile_slug)
            if key is not None:
                stmt = stmt.where(InterestRow.key == key)
            if active_only:
                stmt = stmt.where(InterestRow.active.is_(True))
            rows = list(session.scalars(stmt.order_by(InterestRow.id)))
            for row in rows:
                session.expunge(row)
            return rows

    def is_interest_seeded(
        self, interest_id: int, source: str, *, address: str | None = None
    ) -> bool:
        """Angesät — und, bei einem Thema, unter dieser Adresse. Ein anderes
        Regal ist ein anderer Bestand (Review 04.10.2026)."""
        with self.session() as session:
            row = session.get(InterestSeededRow, (interest_id, source))
            return row is not None and row.address == address

    def mark_interest_seeded(
        self, interest_id: int, source: str, *, now: datetime, address: str | None = None
    ) -> None:
        """Pro Interesse, nicht pro Anlass.

        Der alte Schluessel liess ``category`` bei Autor:innen leer, so dass
        sich *alle* Autor:innen eine Aussaat teilten: die erste saete still an,
        jede weitere meldete ihre ganze Backlist als Neuzugaenge.
        """
        with self.session() as session:
            row = session.get(InterestSeededRow, (interest_id, source))
            if row is None:
                session.add(InterestSeededRow(interest_id=interest_id, source=source,
                                              seeded_at=now, address=address))
            elif row.address != address:
                row.address, row.seeded_at = address, now
            session.commit()

