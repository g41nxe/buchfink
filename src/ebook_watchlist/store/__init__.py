"""Der Snapshot: ein Protokoll der Beobachtungen in SQLite und ein Laufjournal (ADR 5).

Seit #103 ein Paket hinter einer Fassade: `Store` bleibt der eine Name, den
jeder Aufrufer kennt, seine Methoden liegen nach Fachgebiet in `runs`,
`observations`, `catalog` und `profile`, die Tabellen in `rows`. Kein Aufrufer
musste sich dafür ändern.
"""

from __future__ import annotations

from .core import StoreCore
from .profile import ProfileMixin
from .rows import (
    _BEST_PORTRAIT_FIRST,
    _VERSION_ATTEMPTS,
    BISAC_ORIGINS,
    DNB_READING,
    ENTRY_TRIGGER,
    SERIES_ORIGINS,
    Base,
    BisacEntryRow,
    BookRelationRow,
    BookRow,
    BookSourceRow,
    DnbContainsRow,
    DnbRecordRow,
    IntakeChoiceRow,
    IntakeEntryRow,
    InterestRow,
    InterestSeededRow,
    ObservationRow,
    PortraitRow,
    RatingRow,
    ReadingProfileRow,
    RunRow,
    SeriesEntry,
    SeriesEntryRow,
    SeriesNameRow,
    SeriesRow,
    SeriesWatchRow,
    SettingRow,
    SourceCategoryRow,
    SourceRow,
    StateRow,
    WorkEntryRow,
    _better_spelling,
    _file_bisac,
    _file_series,
    _file_work,
    _merge_series,
    _portrait_of,
    _to_observation,
    _tune_sqlite,
    _unknown_author_name,
    _work_book_subjects,
    _work_keys,
    _work_siblings,
    _work_subjects,
)
from .runs import RunsMixin


class Store(RunsMixin, ProfileMixin):
    """Besitzt die SQLite-Datei. Das Schema entsteht beim ersten Gebrauch.

    Eine Fassade: die Methoden stehen nach Fachgebiet in den Nachbarmodulen.
    Die Profilmethoden bauen auf dem Katalog auf, der Katalog auf den
    Beobachtungen — deshalb genügen hier zwei Basen.
    """


__all__ = [
    "BISAC_ORIGINS",
    "Base",
    "BisacEntryRow",
    "BookRelationRow",
    "BookRow",
    "BookSourceRow",
    "DNB_READING",
    "DnbContainsRow",
    "DnbRecordRow",
    "ENTRY_TRIGGER",
    "IntakeChoiceRow",
    "IntakeEntryRow",
    "InterestRow",
    "InterestSeededRow",
    "ObservationRow",
    "PortraitRow",
    "RatingRow",
    "ReadingProfileRow",
    "RunRow",
    "SERIES_ORIGINS",
    "SeriesEntry",
    "SeriesEntryRow",
    "SeriesNameRow",
    "SeriesRow",
    "SeriesWatchRow",
    "SettingRow",
    "SourceCategoryRow",
    "SourceRow",
    "StateRow",
    "Store",
    "StoreCore",
    "WorkEntryRow",
    "_BEST_PORTRAIT_FIRST",
    "_VERSION_ATTEMPTS",
    "_better_spelling",
    "_file_bisac",
    "_file_series",
    "_file_work",
    "_merge_series",
    "_portrait_of",
    "_to_observation",
    "_tune_sqlite",
    "_unknown_author_name",
    "_work_book_subjects",
    "_work_keys",
    "_work_siblings",
    "_work_subjects",
]
