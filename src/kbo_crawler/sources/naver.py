"""Naver Sports schedule and game-relay source adapter.

The adapter returns source JSON without normalizing it.  Keeping fetching and
parsing separate lets callers persist the exact response before attempting a
schema-dependent parse.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Protocol

from ..errors import SourceError
from ..http import HttpClient


class JsonHttpClient(Protocol):
    """Minimal HTTP contract required by :class:`NaverSource`."""

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any: ...


class NaverSource:
    """Fetch public KBO data from Naver Sports.

    Instantiating this class performs no I/O.  A small protocol is used instead
    of a concrete requests session so tests and archival replayers can inject a
    deterministic client.
    """

    BASE_URL = "https://api-gw.sports.naver.com"
    SECTION_ID = "kbaseball"
    CATEGORY_ID = "kbo"

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        base_url: str = BASE_URL,
    ) -> None:
        self.client = client or HttpClient()
        self.base_url = base_url.rstrip("/")

    def fetch_schedule(self, game_date: date | datetime | str) -> Mapping[str, Any]:
        """Fetch games for one calendar date.

        Naver currently filters this endpoint with an inclusive
        ``fromDate``/``toDate`` pair.  The older-looking ``date`` parameter is
        silently ignored, so using it can accidentally return the latest slate.
        """

        normalized_date = _iso_date(game_date)
        return self._get(
            "/schedule/games",
            params={
                "sectionId": self.SECTION_ID,
                "categoryId": self.CATEGORY_ID,
                "fromDate": normalized_date,
                "toDate": normalized_date,
            },
        )

    def fetch_games(self, game_date: date | datetime | str) -> Mapping[str, Any]:
        """Alias for :meth:`fetch_schedule`."""

        return self.fetch_schedule(game_date)

    def fetch_season(self, season_year: int | str | None = None) -> Mapping[str, Any]:
        """Fetch season boundaries, months, and postseason phase metadata."""

        params: dict[str, Any] = {
            "sectionId": self.SECTION_ID,
            "categoryId": self.CATEGORY_ID,
        }
        if season_year is not None:
            year = int(season_year)
            if year < 1982:
                raise ValueError("season_year must be a valid KBO season")
            params["seasonYear"] = year
        return self._get("/schedule/season", params=params)

    def fetch_seasons(self, season_year: int | str | None = None) -> Mapping[str, Any]:
        """Alias for :meth:`fetch_season`."""

        return self.fetch_season(season_year)

    def fetch_relay(self, game_id: str, inning: int) -> Mapping[str, Any]:
        """Fetch a relay page for an already-discovered Naver game ID.

        ``game_id`` is deliberately accepted as an opaque source identifier.
        This adapter never constructs or guesses one from date/team strings.
        """

        normalized_game_id = str(game_id).strip()
        if not normalized_game_id:
            raise ValueError("game_id must be a non-empty discovered source ID")
        normalized_inning = int(inning)
        if normalized_inning < 1:
            raise ValueError("inning must be at least 1")
        return self._get(
            f"/schedule/games/{normalized_game_id}/relay",
            params={"inning": normalized_inning},
        )

    def _get(
        self,
        path: str,
        *,
        params: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        payload = self.client.get_json(f"{self.base_url}{path}", params=params)
        if not isinstance(payload, Mapping):
            raise SourceError(f"Naver {path} returned a non-object JSON payload")
        return payload


def _iso_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw_value = str(value)
    try:
        normalized = date.fromisoformat(raw_value).isoformat()
    except ValueError as exc:
        raise ValueError("game_date must use YYYY-MM-DD") from exc
    # Python accepts the compact ISO basic form (YYYYMMDD), while the Naver
    # endpoint requires the extended form with hyphens.
    if normalized != raw_value:
        raise ValueError("game_date must use YYYY-MM-DD")
    return normalized
