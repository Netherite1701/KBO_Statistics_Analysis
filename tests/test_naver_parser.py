from __future__ import annotations

import json
from pathlib import Path

import pytest

from kbo_crawler.errors import SchemaError
from kbo_crawler.parsers.naver import (
    parse_relay,
    parse_schedule_games,
    parse_season,
)

FIXTURE = Path(__file__).parent / "fixtures" / "naver_relay_small.json"


def test_schedule_parser_accepts_only_source_game_ids() -> None:
    schedule = parse_schedule_games(
        {
            "code": 200,
            "success": True,
            "result": {
                "games": [
                    {
                        "gameId": "source-owned-id",
                        "categoryId": "kbo",
                        "gameDate": "2026-05-06",
                        "homeTeamCode": "HT",
                        "awayTeamCode": "HH",
                        "statusCode": "RESULT",
                        "cancel": False,
                        "suspended": False,
                        "futureField": {"kept": 1},
                    }
                ],
                "gameTotalCount": 1,
            },
        }
    )

    assert schedule.games[0].game_id == "source-owned-id"
    assert schedule.games[0].raw["futureField"] == {"kept": 1}


def test_schedule_parser_rejects_missing_game_id_instead_of_guessing() -> None:
    with pytest.raises(SchemaError, match="gameId"):
        parse_schedule_games(
            {"success": True, "result": {"games": [{"gameDate": "2026-05-06"}]}}
        )


def test_season_parser_preserves_phase_metadata() -> None:
    season = parse_season(
        {
            "code": 200,
            "success": True,
            "result": {
                "seasonYear": 2026,
                "season": "2026",
                "startDate": "2026-03-12",
                "endDate": "2026-09-06",
                "months": [{"yearMonth": "2026-03", "gameCount": 15}],
                "postSeasons": [{"phaseCode": "kbo_ps_ks", "gameCount": 0}],
                "unknownSeasonField": "preserved",
            },
        }
    )

    assert season.months[0]["gameCount"] == 15
    assert season.post_seasons[0]["phaseCode"] == "kbo_ps_ks"
    assert season.raw_result["unknownSeasonField"] == "preserved"


def test_relay_parser_preserves_chronology_results_and_physics() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    parsed = parse_relay(payload, game_id="20260506HHHT02026", requested_inning=1)

    assert [relay.relay_no for relay in parsed.relays] == [1, 2]
    assert [(event.event_type, event.text) for event in parsed.result_events] == [
        (13, "테스트하나 : 볼넷"),
        (23, "테스트둘 : 우익수 뒤 홈런"),
    ]

    by_id = {pitch.pitch_id: pitch for pitch in parsed.pitches}
    tracked = by_id["260506_190100"]
    assert tracked.seqno == 21
    assert tracked.pitch_num == 1
    assert tracked.pitch_result == "H"
    assert tracked.pitcher_code == "11111"
    assert tracked.batter_code == "22222"
    assert tracked.current_game_state["out"] == "1"
    assert tracked.x0 == 1.8
    assert tracked.y0 == 50.0
    assert tracked.z0 == 5.7
    assert tracked.cross_plate_x == 0.25
    assert tracked.raw_text_option["unknownTextField"] == "preserved"
    assert tracked.raw_pts_option["unknownPtsField"] == 99
    assert parsed.raw_text_relay_data["sourceOnlyTopField"]["mustSurvive"] is True


def test_relay_parser_outer_joins_missing_tracking_and_text() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    parsed = parse_relay(payload)
    by_id = {pitch.pitch_id: pitch for pitch in parsed.pitches}

    no_tracking = by_id["260506_190010"]
    assert no_tracking.seqno == 12
    assert no_tracking.pitch_num == 2
    assert no_tracking.has_tracking is False
    assert no_tracking.raw_text_option is not None
    assert no_tracking.raw_pts_option is None

    tracking_only = by_id["260506_tracking_only"]
    assert tracking_only.has_tracking is True
    assert tracking_only.raw_text_option is None
    assert tracking_only.ballcount == 3
    assert tracking_only.z0 == 5.9


def test_relay_parser_rejects_mismatched_game_id() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    with pytest.raises(SchemaError, match="mismatch"):
        parse_relay(payload, game_id="another-game")
