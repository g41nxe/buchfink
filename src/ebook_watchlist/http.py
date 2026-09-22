"""The shared politeness layer every Source fetches through (ADR 7).

We are a guest on someone else's server. The rules are not negotiable per
Source, so they live here rather than in each scraper: one request at a time, a
pause between them, an honest User-Agent, a single retry for transient trouble,
and a hard stop the moment a site says 429.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import requests

from . import __version__

#: Sent unless the settings supply a contact. Deliberately carries no personal
#: data — add your own address via ``settings.yaml``'s ``contact`` if you
#: want an operator to be able to reach you.
DEFAULT_USER_AGENT = f"ebook-watchlist/{__version__} (personal watchlist bot; +https://github.com/g41nxe/ebook-watchlist)"

MIN_DELAY_SECONDS = 2.0
MAX_DELAY_SECONDS = 4.0
DEFAULT_TIMEOUT_SECONDS = 20.0


class RateLimited(Exception):
    """The server said 429. We stop entirely rather than probing for the limit."""


class FetchError(Exception):
    """The page could not be retrieved after the one permitted retry."""


class NotFound(Exception):
    """The page is gone (404/410).

    Distinct from :class:`FetchError` because for a Source this is usually an
    *answer* — a pinned title that left the catalogue — not a malfunction.
    """


def build_user_agent(contact: str | None) -> str:
    if not contact:
        return DEFAULT_USER_AGENT
    return f"ebook-watchlist/{__version__} (personal watchlist bot; {contact})"


@dataclass(slots=True)
class HttpClient:
    """Serial, rate-limited GETs. One instance per Run, shared by all Sources."""

    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    min_delay: float = MIN_DELAY_SECONDS
    max_delay: float = MAX_DELAY_SECONDS
    session: requests.Session | None = None
    _last_request_at: float | None = None

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "de-DE,de;q=0.9",
            }
        )

    def _wait_turn(self) -> None:
        """Hold the floor: never two requests closer together than the delay."""
        delay = random.uniform(self.min_delay, self.max_delay)
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < delay:
                time.sleep(delay - elapsed)
        self._last_request_at = time.monotonic()

    def get(self, url: str, params: dict[str, str] | None = None) -> str:
        """Fetch one page as text. Raises rather than returning something empty."""
        response = self._fetch(url, params)
        # The Onleihe and Shopware both serve UTF-8 but do not always say so;
        # trusting requests' latin-1 guess mangles umlauts.
        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def get_bytes(self, url: str) -> bytes:
        """Fetch one file as it is — a cover image, nothing decoded.

        Same queue, same pause, same retry as a page: an image is a request like
        any other, and fetching a hundred of them quickly would undo the
        politeness the rest of this class exists for.
        """
        return self._fetch(url, None).content

    def _fetch(self, url: str, params: dict[str, str] | None) -> requests.Response:
        assert self.session is not None  # set in __post_init__
        last_error: Exception | None = None

        for attempt in range(2):
            self._wait_turn()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code == 429:
                    raise RateLimited(f"{url} answered 429 — stopping, not retrying")
                if response.status_code in (404, 410):
                    raise NotFound(f"{url} answered {response.status_code}")
                if response.status_code >= 500:
                    last_error = FetchError(f"{url} answered {response.status_code}")
                elif response.status_code >= 400:
                    # Der Server hat verstanden und abgelehnt: 403, wenn ein
                    # Shop uns aussperrt, 401 hinter einer Anmeldung, 451 aus
                    # rechtlichen Gruenden. Kein zweiter Versuch — die Antwort
                    # wird beim Wiederholen dieselbe sein, und noch einmal zu
                    # klopfen waere genau die Unhoeflichkeit, gegen die diese
                    # Klasse gebaut ist.
                    #
                    # Und ausdruecklich als FetchError, nicht als
                    # requests.HTTPError: bis hierher entkam die einzige
                    # Ausnahme, die keiner der Aufrufer faengt. Ein 403 auf ein
                    # Titelbild riss damit einen ganzen Lauf ab, bevor eine
                    # einzige Beobachtung geschrieben war.
                    raise FetchError(f"{url} answered {response.status_code}")
                else:
                    return response

            if attempt == 0:
                time.sleep(self.max_delay * 2)

        raise FetchError(f"could not fetch {url}: {last_error}") from last_error
