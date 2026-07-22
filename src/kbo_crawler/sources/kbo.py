"""Adapters for official KBO schedule, game-centre, player, and roster data."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from typing import Any, Protocol, runtime_checkable

from kbo_crawler.errors import SchemaError, SourceError
from kbo_crawler.http import HttpClient

KBO_BASE_URL = "https://www.koreabaseball.com"
SCHEDULE_URL = f"{KBO_BASE_URL}/Schedule/Schedule.aspx"
GAME_CENTER_URL = f"{KBO_BASE_URL}/Schedule/GameCenter/Main.aspx"
SCOREBOARD_URL = f"{KBO_BASE_URL}/ws/Schedule.asmx/GetScoreBoardScroll"
BOXSCORE_URL = f"{KBO_BASE_URL}/ws/Schedule.asmx/GetBoxScoreScroll"
ROSTER_URL = f"{KBO_BASE_URL}/Player/Register.aspx"
ROSTER_ALL_URL = f"{KBO_BASE_URL}/Player/RegisterAll.aspx"


class KBOHTMLResponseError(SourceError):
    """An endpoint that should return JSON returned an HTML document."""


class KBOContentTypeError(SourceError):
    """An ASMX response did not advertise a JSON-compatible media type."""


class KBOBusinessError(SourceError):
    """KBO returned a syntactically valid error response."""


@runtime_checkable
class BrowserFallback(Protocol):
    """Optional browser-backed fetcher.

    Implementations may return a mapping directly or the browser's response
    body as text.  Selenium is intentionally not imported by this module.
    """

    def __call__(
        self,
        url: str,
        *,
        method: str,
        data: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | str:
        ...


def _date_text(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


class KBOSource:
    """Read-only client for public KBO pages and game-centre ASMX methods."""

    def __init__(
        self,
        *,
        http: HttpClient | None = None,
        browser_fallback: BrowserFallback | None = None,
    ) -> None:
        self.http = http or HttpClient()
        self.browser_fallback = browser_fallback
        self._bootstrapped = False

    def bootstrap_game_center(self, game_date: date | str | None = None) -> str:
        """Open game centre once so the shared session receives KBO cookies."""

        params = {"gameDate": _date_text(game_date).replace("-", "")} if game_date else None
        response = self.http.request("GET", GAME_CENTER_URL, params=params)
        body = response.text
        if not body.strip():
            raise SourceError(f"{GAME_CENTER_URL} returned an empty bootstrap page")
        self._bootstrapped = True
        return body

    def fetch_schedule(self, year: int, month: int, *, series_id: str = "0") -> str:
        """Fetch a monthly official schedule page."""

        if month < 1 or month > 12:
            raise ValueError("month must be between 1 and 12")
        return self.http.get_text(
            SCHEDULE_URL,
            params={"year": str(year), "month": f"{month:02d}", "seriesId": series_id},
        )

    def fetch_scoreboard(
        self,
        game_id: str,
        *,
        league_id: str = "1",
        series_id: str = "0",
        season_id: str | int | None = None,
    ) -> Mapping[str, Any]:
        return self._fetch_game_json(
            SCOREBOARD_URL,
            game_id,
            league_id=league_id,
            series_id=series_id,
            season_id=season_id,
        )

    def fetch_boxscore(
        self,
        game_id: str,
        *,
        league_id: str = "1",
        series_id: str = "0",
        season_id: str | int | None = None,
    ) -> Mapping[str, Any]:
        return self._fetch_game_json(
            BOXSCORE_URL,
            game_id,
            league_id=league_id,
            series_id=series_id,
            season_id=season_id,
        )

    def fetch_player_daily(
        self,
        player_id: str | int,
        *,
        role: str = "hitter",
        season_id: str | int | None = None,
        series_id: str = "0",
    ) -> str:
        """Fetch the official daily-record HTML for a hitter or pitcher."""

        role_key = role.lower()
        if role_key not in {"hitter", "pitcher"}:
            raise ValueError("role must be 'hitter' or 'pitcher'")
        segment = "HitterDetail" if role_key == "hitter" else "PitcherDetail"
        url = f"{KBO_BASE_URL}/Record/Player/{segment}/Daily.aspx"
        params: dict[str, Any] = {"playerId": str(player_id)}
        if season_id is not None:
            # KBO currently renders the selected season in an ASP.NET form.
            # These values are retained in the raw request metadata even when
            # the site chooses the current season.
            params["seasonId"] = str(season_id)
            params["seriesId"] = series_id
        html = self.http.get_text(url, params=params)
        if season_id is not None and not self._html_has_selected_option(
            html, str(season_id)
        ):
            if self.browser_fallback is None:
                raise SourceError(
                    "KBO daily page ignored the requested season; configure "
                    "browser_fallback for ASP.NET year selection"
                )
            html = self._fallback_html(url, method="GET", data=params)
            if not self._html_has_selected_option(html, str(season_id)):
                raise SourceError(
                    f"KBO browser fallback did not select season {season_id}"
                )
        return html

    def fetch_roster(
        self,
        roster_date: date | str,
        *,
        team_id: str | None = None,
        all_teams: bool = False,
    ) -> str:
        """Fetch a dated first-team roster page.

        ``Register.aspx`` contains per-team registration and transaction
        details.  ``RegisterAll.aspx`` is useful for a compact all-team
        snapshot but does not expose all transaction details.
        """

        url = ROSTER_ALL_URL if all_teams else ROSTER_URL
        params: dict[str, Any] = {"date": _date_text(roster_date)}
        if team_id:
            params["teamId"] = team_id
        html = self.http.get_text(url, params=params)
        requested = _date_text(roster_date)
        date_pattern = re.escape(requested).replace(r"\-", r"[.\-/]")
        if not re.search(date_pattern, html):
            if self.browser_fallback is None:
                raise SourceError(
                    "KBO roster page ignored the requested date; configure "
                    "browser_fallback for ASP.NET date selection"
                )
            html = self._fallback_html(url, method="GET", data=params)
            if not re.search(date_pattern, html):
                raise SourceError(
                    f"KBO browser fallback did not select roster date {requested}"
                )
        return html

    def _fetch_game_json(
        self,
        url: str,
        game_id: str,
        *,
        league_id: str,
        series_id: str,
        season_id: str | int | None,
    ) -> Mapping[str, Any]:
        if not game_id:
            raise ValueError("game_id is required")
        if not self._bootstrapped:
            self.bootstrap_game_center()

        resolved_season = str(season_id) if season_id is not None else game_id[:4]
        payload = {
            "leId": league_id,
            "srId": series_id,
            "seasonId": resolved_season,
            "gameId": game_id,
        }
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": GAME_CENTER_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        response = self.http.request("POST", url, data=payload, headers=headers)
        try:
            result = self._decode_asmx_response(response, url)
        except KBOHTMLResponseError:
            if self.browser_fallback is None:
                raise
            result = self._decode_fallback(
                self.browser_fallback(url, method="POST", data=payload), url
            )
        return self._validate_game_payload(result, url)

    @staticmethod
    def _decode_asmx_response(response: Any, url: str) -> Mapping[str, Any]:
        content_type = str(response.headers.get("Content-Type", "")).lower()
        body = str(response.text).lstrip("\ufeff \t\r\n")
        if "html" in content_type or body.lower().startswith(
            ("<!doctype html", "<html", "<!--")
        ):
            raise KBOHTMLResponseError(f"{url} returned HTML instead of ASMX JSON")
        accepted_types = ("application/json", "text/json", "text/plain")
        if not any(media_type in content_type for media_type in accepted_types):
            raise KBOContentTypeError(
                f"{url} returned unsupported Content-Type {content_type!r}"
            )
        try:
            value = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise SourceError(f"{url} returned invalid JSON") from exc
        return KBOSource._coerce_mapping(value, url)

    @staticmethod
    def _decode_fallback(value: Mapping[str, Any] | str, url: str) -> Mapping[str, Any]:
        if isinstance(value, str):
            body = value.lstrip("\ufeff \t\r\n")
            if body.lower().startswith(("<!doctype html", "<html", "<!--")):
                raise KBOHTMLResponseError(
                    f"browser fallback for {url} also returned HTML"
                )
            try:
                value = json.loads(body)
            except json.JSONDecodeError as exc:
                raise SourceError(
                    f"browser fallback for {url} returned invalid JSON"
                ) from exc
        return KBOSource._coerce_mapping(value, url)

    def _fallback_html(
        self,
        url: str,
        *,
        method: str,
        data: Mapping[str, Any],
    ) -> str:
        if self.browser_fallback is None:
            raise SourceError(f"no browser fallback configured for {url}")
        value = self.browser_fallback(url, method=method, data=data)
        if not isinstance(value, str) or not value.strip():
            raise SourceError(f"browser fallback for {url} did not return HTML text")
        return value

    @staticmethod
    def _html_has_selected_option(html: str, value: str) -> bool:
        option_pattern = re.compile(
            rf"<option\b(?=[^>]*\bselected(?:\s*=\s*['\"][^'\"]*['\"])?)(?=[^>]*\bvalue\s*=\s*['\"]{re.escape(value)}['\"])[^>]*>",
            re.I,
        )
        return option_pattern.search(html) is not None

    @staticmethod
    def _coerce_mapping(value: Any, url: str) -> Mapping[str, Any]:
        # Some ASP.NET configurations wrap the actual payload in ``d``.
        if isinstance(value, Mapping) and set(value) == {"d"}:
            value = value["d"]
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise SchemaError(f"{url} has an invalid ASP.NET d wrapper") from exc
        if not isinstance(value, Mapping):
            raise SchemaError(f"{url} JSON root must be an object")
        return value

    @staticmethod
    def _validate_game_payload(
        value: Mapping[str, Any], url: str
    ) -> Mapping[str, Any]:
        if "code" not in value:
            raise SchemaError(f"{url} JSON is missing the KBO response code")
        code = value.get("code")
        if str(code) != "100":
            message = value.get("message") or value.get("msg") or "unknown KBO error"
            raise KBOBusinessError(f"{url} returned KBO code {code!r}: {message}")
        return value


__all__ = [
    "BOXSCORE_URL",
    "BrowserFallback",
    "GAME_CENTER_URL",
    "KBOBusinessError",
    "KBOContentTypeError",
    "KBOHTMLResponseError",
    "KBOSource",
    "ROSTER_ALL_URL",
    "ROSTER_URL",
    "SCHEDULE_URL",
    "SCOREBOARD_URL",
]
