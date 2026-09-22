"""A Source backed by a YAML file instead of a website.

It exists so the whole pipeline can be exercised — and its Deltas demonstrated —
without touching the network: edit a price in the fixture, run again, watch the
Digest name the change.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from ..config import Settings, WatchlistEntry
from ..models import Availability, MatchReason, Observation
from .base import Item, RunContext, Source, SourceStructureError


class FakeSource(Source):
    name = "fake"

    def __init__(self, fixture: Path, name: str = "fake") -> None:
        self.fixture = fixture
        self.name = name

    def _rows(self) -> list[dict[str, Any]]:
        if not self.fixture.exists():
            raise SourceStructureError(f"fake source fixture not found at {self.fixture}")
        data = yaml.safe_load(self.fixture.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("items")
        if not isinstance(data, list):
            raise SourceStructureError(
                f"fake source fixture at {self.fixture} must be a list of items"
            )
        return data

    def collect(
        self,
        settings: Settings,
        watchlist: Sequence[WatchlistEntry],
        context: RunContext,
    ) -> list[Observation]:
        by_title = {entry.title.casefold(): entry for entry in watchlist if entry.active}
        observations: list[Observation] = []

        for index, row in enumerate(self._rows(), start=1):
            if not isinstance(row, dict):
                raise SourceStructureError(f"fake source item #{index} is not a mapping")
            try:
                title = row["title"]
                source_item_id = str(row["id"])
            except KeyError as exc:
                raise SourceStructureError(
                    f"fake source item #{index} is missing {exc.args[0]!r}"
                ) from exc

            entry = by_title.get(str(title).casefold())
            availability = row.get("availability")
            observations.append(
                Observation(
                    source=self.name,
                    source_item_id=source_item_id,
                    title=str(title),
                    author=row.get("author"),
                    match_reason=MatchReason(row.get("match_reason", MatchReason.WATCHLIST)),
                    watchlist_key=entry.key if entry else None,
                    price_cents=row.get("price_cents"),
                    original_price_cents=row.get("original_price_cents"),
                    availability=Availability(availability) if availability else None,
                    reservation_count=row.get("reservation_count"),
                    available_from=row.get("available_from"),
                    category=row.get("category"),
                    url=row.get("url"),
                )
            )
        return observations

    def item(self, source_item_id: str) -> Item | None:
        """Which book one of the fixture's ids means (Ticket 17).

        Here too the point is that the whole path can be walked without a
        website — resolving an old dismissal is otherwise the one step that
        could only ever be tried against the live shop.
        """
        for row in self._rows():
            if not isinstance(row, dict) or str(row.get("id")) != source_item_id:
                continue
            return Item(
                source_item_id=source_item_id,
                title=str(row.get("title", "")),
                author=row.get("author"),
                isbn=row.get("isbn"),
                blurb=row.get("detail_blurb") or row.get("blurb"),
                url=row.get("url"),
            )
        return None

    def probe(self) -> None:
        self._rows()
