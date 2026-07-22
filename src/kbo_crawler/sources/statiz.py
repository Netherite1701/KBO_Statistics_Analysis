"""Optional STATIZ source used only for independent aggregate validation."""

from __future__ import annotations

from typing import Final

from kbo_crawler.errors import SourceError
from kbo_crawler.http import HttpClient

STATIZ_PLAYER_URL: Final = "https://www.statiz.co.kr/player/"
SUPPORTED_VIEWS: Final = frozenset(
    {"playerinfo", "year", "day", "playlog", "analysis"}
)


class StatizDisabledError(SourceError):
    """STATIZ access was attempted without explicitly enabling the source."""


class StatizSource:
    """Fetch validation-only STATIZ pages.

    This source is opt-in because it is not required for a valid KBO/Naver
    crawl and a STATIZ outage must never block the primary pipeline.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        http: HttpClient | None = None,
    ) -> None:
        self.enabled = enabled
        self.http = http or HttpClient(requests_per_second=1.0)

    def fetch_player(self, player_no: str | int, *, view: str = "playerinfo") -> str:
        if not self.enabled:
            raise StatizDisabledError(
                "STATIZ is disabled; construct StatizSource(enabled=True) to opt in"
            )
        view_key = view.lower()
        if view_key not in SUPPORTED_VIEWS:
            supported = ", ".join(sorted(SUPPORTED_VIEWS))
            raise ValueError(f"unsupported STATIZ view {view!r}; choose one of {supported}")
        return self.http.get_text(
            STATIZ_PLAYER_URL,
            params={"m": view_key, "p_no": str(player_no)},
            headers={"Referer": "https://www.statiz.co.kr/"},
        )

    def fetch_daily(self, player_no: str | int) -> str:
        return self.fetch_player(player_no, view="day")

    def fetch_playlog(self, player_no: str | int) -> str:
        return self.fetch_player(player_no, view="playlog")

    def fetch_analysis(self, player_no: str | int) -> str:
        return self.fetch_player(player_no, view="analysis")


__all__ = [
    "STATIZ_PLAYER_URL",
    "SUPPORTED_VIEWS",
    "StatizDisabledError",
    "StatizSource",
]
