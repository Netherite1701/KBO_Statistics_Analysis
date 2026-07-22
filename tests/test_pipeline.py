from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from kbo_crawler.config import CrawlerConfig
from kbo_crawler.cli import build_parser
from kbo_crawler.db import Database
from kbo_crawler.export import export_pitches
from kbo_crawler.parsers.naver import parse_relay, parse_schedule_games
from kbo_crawler.physics import plate_crossing_height
from kbo_crawler.pipeline import Crawler
from kbo_crawler.quality import validate_game_records
from kbo_crawler.repository import (
    replace_boxscore_data,
    replace_relay_data,
    upsert_schedule_game,
)


FIXTURE = Path(__file__).parent / "fixtures" / "naver_relay_small.json"
GAME_ID = "20260506HHHT02026"


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "kbo.sqlite")
    database.initialize()
    return database


def _schedule_payload() -> dict:
    return {
        "success": True,
        "result": {
            "gameTotalCount": 1,
            "games": [
                {
                    "gameId": GAME_ID,
                    "gameDate": "2026-05-06",
                    "homeTeamCode": "HT",
                    "homeTeamName": "KIA",
                    "awayTeamCode": "HH",
                    "awayTeamName": "한화",
                    "homeTeamScore": 3,
                    "awayTeamScore": 2,
                    "statusCode": "RESULT",
                    "cancel": False,
                    "suspended": False,
                }
            ],
        },
    }


def test_repository_preserves_source_pitch_numbers_and_real_plate_height(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    game = parse_schedule_games(_schedule_payload()).games[0]
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    parsed = parse_relay(payload, game_id=GAME_ID, requested_inning=1)

    with database.transaction() as connection:
        upsert_schedule_game(connection, game, season=2026)
    with database.game_transaction(GAME_ID) as connection:
        pa_count, pitch_count, event_count = replace_relay_data(connection, parsed)

    assert pa_count == 2
    assert pitch_count == 4
    assert event_count == 7
    with database.session() as connection:
        row = connection.execute(
            """
            SELECT pitch_num, z0, plate_height, cross_plate_y
            FROM pitches
            WHERE pitch_id = '260506_190100'
            """
        ).fetchone()
        assert row["pitch_num"] == 1
        assert row["z0"] == pytest.approx(5.7)
        assert row["plate_height"] != pytest.approx(row["cross_plate_y"])
        assert row["plate_height"] != pytest.approx(5.8)


def test_event_only_relay_does_not_create_a_fake_plate_appearance(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    game = parse_schedule_games(_schedule_payload()).games[0]
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["result"]["textRelayData"]["textRelays"].append(
        {
            "title": "9회 종료",
            "no": 99,
            "inn": 9,
            "homeOrAway": "1",
            "textOptions": [{"seqno": 999, "type": 99, "text": "경기 종료"}],
            "ptsOptions": [],
        }
    )
    parsed = parse_relay(payload, game_id=GAME_ID)

    with database.transaction() as connection:
        upsert_schedule_game(connection, game, season=2026)
    with database.game_transaction(GAME_ID) as connection:
        pa_count, _, _ = replace_relay_data(connection, parsed)

    assert pa_count == 2
    with database.session() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM plate_appearances WHERE game_id = ?",
                (GAME_ID,),
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM game_events WHERE game_id = ? AND relay_no = 99",
                (GAME_ID,),
            ).fetchone()[0]
            == 1
        )


def test_pitch_id_is_unique_within_game_not_across_simultaneous_games(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    first_game = parse_schedule_games(_schedule_payload()).games[0]
    second_schedule = _schedule_payload()
    second_id = "20260506NCSK02026"
    second_schedule["result"]["games"][0]["gameId"] = second_id
    second_schedule["result"]["games"][0]["homeTeamCode"] = "SK"
    second_schedule["result"]["games"][0]["awayTeamCode"] = "NC"
    second_game = parse_schedule_games(second_schedule).games[0]
    first_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    second_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    second_payload["result"]["textRelayData"]["gameId"] = second_id

    with database.transaction() as connection:
        upsert_schedule_game(connection, first_game, season=2026)
        upsert_schedule_game(connection, second_game, season=2026)
    with database.game_transaction(GAME_ID) as connection:
        replace_relay_data(
            connection,
            parse_relay(first_payload, game_id=GAME_ID),
        )
    with database.game_transaction(second_id) as connection:
        replace_relay_data(
            connection,
            parse_relay(second_payload, game_id=second_id),
        )

    with database.session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pitches").fetchone()[0] == 8
        assert (
            connection.execute(
                """
                SELECT COUNT(*) FROM pitches
                WHERE pitch_id = '260506_190100'
                """
            ).fetchone()[0]
            == 2
        )


def test_missing_source_pitch_ids_receive_stable_unique_ids(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    game = parse_schedule_games(_schedule_payload()).games[0]
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    relay = next(
        relay
        for relay in payload["result"]["textRelayData"]["textRelays"]
        if relay["no"] == 1
    )
    for option in relay["textOptions"]:
        if option.get("pitchNum") is not None:
            option["ptsPitchId"] = "-1"
    relay["ptsOptions"] = []
    parsed = parse_relay(payload, game_id=GAME_ID)
    missing = [
        pitch
        for pitch in parsed.pitches
        if pitch.relay_no == 1
    ]
    assert len(missing) == 2
    assert all(pitch.pitch_id is None for pitch in missing)

    with database.transaction() as connection:
        upsert_schedule_game(connection, game, season=2026)
    with database.game_transaction(GAME_ID) as connection:
        replace_relay_data(connection, parsed)

    with database.session() as connection:
        rows = list(
            connection.execute(
                """
                SELECT pitch_id, raw_json FROM pitches
                WHERE game_id = ? AND pitch_id LIKE 'synthetic:%'
                ORDER BY seqno
                """,
                (GAME_ID,),
            )
        )
    assert [row["pitch_id"] for row in rows] == [
        "synthetic:1:11",
        "synthetic:1:12",
    ]
    assert all('"ptsPitchId":"-1"' in row["raw_json"] for row in rows)


def test_export_uses_relay_and_event_chronology(tmp_path: Path) -> None:
    database = _database(tmp_path)
    game = parse_schedule_games(_schedule_payload()).games[0]
    parsed = parse_relay(
        json.loads(FIXTURE.read_text(encoding="utf-8")),
        game_id=GAME_ID,
    )
    with database.transaction() as connection:
        upsert_schedule_game(connection, game, season=2026)
    with database.game_transaction(GAME_ID) as connection:
        replace_relay_data(connection, parsed)

    output = tmp_path / "pitches.csv"
    with database.session() as connection:
        assert export_pitches(connection, output, game_id=GAME_ID) == 4
    text = output.read_text(encoding="utf-8-sig").splitlines()
    assert "plate_appearance_id" in text[0]
    assert text[1].startswith(f"{GAME_ID},{GAME_ID}:1,260506_190000")


def test_plate_height_requires_recorded_release_geometry() -> None:
    assert (
        plate_crossing_height(
            y0=None,
            z0=5.8,
            vy0=-130,
            vz0=-5,
            ay=20,
            az=-18,
            plate_y=0.7083,
        )
        is None
    )


def test_implausible_reconstructed_height_is_kept_but_warned() -> None:
    issues = validate_game_records(
        game_id=GAME_ID,
        pitches=[
            {
                "pitch_id": "p1",
                "plate_appearance_id": "pa1",
                "batter_id": "b1",
                "pitcher_id": "r1",
                "seqno": 1,
                "pitch_num": 1,
                "plate_height": -0.25,
            }
        ],
        plate_appearances=[{"plate_appearance_id": "pa1"}],
    )
    assert [(issue.code, issue.severity) for issue in issues] == [
        ("implausible_plate_height", "warning")
    ]


def test_official_boxscore_rows_are_idempotent(tmp_path: Path) -> None:
    database = _database(tmp_path)
    game = parse_schedule_games(_schedule_payload()).games[0]
    boxscore = {
        "batting": [
            {
                "team_side": "away",
                "team_id": "HH",
                "team_name": "한화",
                "row_index": 0,
                "external_player_id": "44444",
                "player_name": "테스트 타자",
                "is_total": False,
                "metrics": {
                    "plate_appearances": "4",
                    "at_bats": "3",
                    "runs": "2",
                    "hits": "1",
                },
            }
        ],
        "pitching": [
            {
                "team_side": "home",
                "team_id": "HT",
                "team_name": "KIA",
                "row_index": 0,
                "external_player_id": "11111",
                "player_name": "테스트 투수",
                "is_total": False,
                "metrics": {
                    "innings_pitched": "5.2",
                    "pitches": "88",
                    "runs": "2",
                    "earned_runs": "1",
                },
            }
        ],
    }
    with database.transaction() as connection:
        upsert_schedule_game(connection, game, season=2026)
    for _ in range(2):
        with database.game_transaction(GAME_ID) as connection:
            assert replace_boxscore_data(
                connection,
                game_id=GAME_ID,
                boxscore=boxscore,
            ) == (1, 1)
    with database.session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM batting_boxscores").fetchone()[0] == 1
        pitching = connection.execute(
            "SELECT outs_recorded, pitches FROM pitching_boxscores"
        ).fetchone()
        assert pitching["outs_recorded"] == 17
        assert pitching["pitches"] == 88
        assert (
            connection.execute(
                """
                SELECT canonical_name FROM players WHERE player_id = '11111'
                """
            ).fetchone()[0]
            == "테스트 투수"
        )


class _FakeNaver:
    def __init__(self, relay_payload: dict) -> None:
        self.relay_payload = relay_payload
        self.innings: list[int] = []

    def fetch_schedule(self, game_date: date) -> dict:
        return _schedule_payload()

    def fetch_relay(self, game_id: str, inning: int) -> dict:
        self.innings.append(inning)
        if inning == 1:
            return self.relay_payload
        return {
            "success": True,
            "result": {
                "textRelayData": {
                    "gameId": game_id,
                    "inn": inning,
                    "textRelays": [],
                }
            },
        }


def test_end_to_end_pipeline_uses_discovered_id_and_quarantines_only_errors(
    tmp_path: Path,
) -> None:
    config = CrawlerConfig(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "kbo.sqlite",
        raw_dir=tmp_path / "data" / "raw",
    )
    source = _FakeNaver(json.loads(FIXTURE.read_text(encoding="utf-8")))
    crawler = Crawler(config, naver=source)
    crawler.initialize()

    assert crawler.discover_date(date(2026, 5, 6)) == (GAME_ID,)
    pa_count, pitch_count, issues = crawler.fetch_game(
        GAME_ID,
        validate_kbo=False,
    )

    assert pa_count == 2
    assert pitch_count == 4
    assert source.innings == list(range(1, 11))
    assert {issue.code for issue in issues} == {"unmatched_pts_pitch"}
    with crawler.database.session() as connection:
        game = connection.execute(
            "SELECT ingestion_status FROM games WHERE game_id = ?",
            (GAME_ID,),
        ).fetchone()
        assert game["ingestion_status"] == "validated"
        assert connection.execute("SELECT COUNT(*) FROM source_requests").fetchone()[0] == 11
        assert connection.execute("SELECT COUNT(*) FROM pitches").fetchone()[0] == 4

    source.innings.clear()
    messages: list[str] = []
    summary = crawler.run_dates(
        [date(2026, 5, 6)],
        validate_kbo=False,
        skip_validated=True,
        run_type="period",
        progress=messages.append,
    )
    assert summary.skipped == 1
    assert summary.fetched == 0
    assert source.innings == []
    assert any("이미 검증됨" in message for message in messages)


def test_period_wrapper_requires_an_explicit_date_range() -> None:
    arguments = build_parser().parse_args(
        [
            "period",
            "--from-date",
            "2025-03-01",
            "--to-date",
            "2025-11-30",
            "--with-player-daily",
        ]
    )
    assert arguments.from_date == date(2025, 3, 1)
    assert arguments.to_date == date(2025, 11, 30)
    assert arguments.with_player_daily is True
