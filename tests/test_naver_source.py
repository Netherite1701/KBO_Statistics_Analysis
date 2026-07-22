from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from kbo_crawler.sources.naver import NaverSource


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(self, url: str, *, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        return {"code": 200, "success": True, "result": {}}


def test_schedule_uses_actual_date_range_contract() -> None:
    client = FakeClient()
    source = NaverSource(client, base_url="https://example.invalid/")

    payload = source.fetch_schedule(date(2026, 5, 6))

    assert payload["success"] is True
    assert client.calls == [
        (
            "https://example.invalid/schedule/games",
            {
                "sectionId": "kbaseball",
                "categoryId": "kbo",
                "fromDate": "2026-05-06",
                "toDate": "2026-05-06",
            },
        )
    ]


def test_source_uses_discovered_game_id_verbatim() -> None:
    client = FakeClient()
    source = NaverSource(client, base_url="https://example.invalid")

    source.fetch_relay("opaque-source-id", 12)

    assert client.calls[-1] == (
        "https://example.invalid/schedule/games/opaque-source-id/relay",
        {"inning": 12},
    )


def test_season_fetch_has_no_import_or_constructor_io() -> None:
    client = FakeClient()
    source = NaverSource(client)
    assert client.calls == []

    source.fetch_season(2025)

    assert client.calls[0][1]["seasonYear"] == 2025


@pytest.mark.parametrize("value", ["20260506", "2026-13-01", ""])
def test_invalid_schedule_date_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        NaverSource(FakeClient()).fetch_schedule(value)
