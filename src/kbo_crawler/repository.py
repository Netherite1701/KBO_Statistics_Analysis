"""Idempotent SQLite writes for normalized Naver records."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import Any, Iterable

from .parsers.naver import NaverGame, NaverRelayResult
from .physics import plate_crossing_height
from .quality import QualityIssue


TEAM_NAME_TO_ID = {
    "KIA": "HT",
    "KIA 타이거즈": "HT",
    "한화": "HH",
    "한화 이글스": "HH",
    "LG": "LG",
    "LG 트윈스": "LG",
    "KT": "KT",
    "KT 위즈": "KT",
    "SSG": "SK",
    "SSG 랜더스": "SK",
    "SK": "SK",
    "두산": "OB",
    "두산 베어스": "OB",
    "롯데": "LT",
    "롯데 자이언츠": "LT",
    "삼성": "SS",
    "삼성 라이온즈": "SS",
    "NC": "NC",
    "NC 다이노스": "NC",
    "키움": "WO",
    "키움 히어로즈": "WO",
}


def upsert_schedule_game(
    connection: sqlite3.Connection,
    game: NaverGame,
    *,
    season: int,
    series_type: str = "regular",
) -> None:
    """Create/update a discovered game without fabricating source IDs."""

    for team_code, team_name in (
        (game.away_team_code, game.away_team_name),
        (game.home_team_code, game.home_team_name),
    ):
        if not team_code:
            continue
        connection.execute(
            """
            INSERT INTO teams (team_id, canonical_name, short_name)
            VALUES (?, ?, ?)
            ON CONFLICT(team_id) DO UPDATE SET
                canonical_name = COALESCE(NULLIF(excluded.canonical_name, ''), teams.canonical_name),
                short_name = COALESCE(NULLIF(excluded.short_name, ''), teams.short_name),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            (team_code, team_name or team_code, team_name),
        )
        connection.execute(
            """
            INSERT INTO team_aliases (source, external_team_id, team_id, source_name)
            VALUES ('naver', ?, ?, ?)
            ON CONFLICT(source, external_team_id) DO UPDATE SET
                team_id = excluded.team_id,
                source_name = excluded.source_name
            """,
            (team_code, team_code, team_name),
        )

    game_date = (game.game_date or game.game_date_time or "")[:10]
    if not game_date:
        raise ValueError(f"game {game.game_id} has no schedule date")
    status = game.status_code or game.status_info or "unknown"
    connection.execute(
        """
        INSERT INTO games (
            game_id, season, series_type, game_date, scheduled_start, status,
            away_team_id, home_team_id, is_cancelled, is_suspended,
            away_score, home_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_id) DO UPDATE SET
            season = excluded.season,
            series_type = excluded.series_type,
            game_date = excluded.game_date,
            scheduled_start = excluded.scheduled_start,
            status = excluded.status,
            away_team_id = excluded.away_team_id,
            home_team_id = excluded.home_team_id,
            is_cancelled = excluded.is_cancelled,
            is_suspended = excluded.is_suspended,
            away_score = excluded.away_score,
            home_score = excluded.home_score,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (
            game.game_id,
            season,
            series_type,
            game_date,
            game.game_date_time,
            status,
            game.away_team_code,
            game.home_team_code,
            int(game.cancelled),
            int(game.suspended),
            _integer(game.away_team_score),
            _integer(game.home_team_score),
        ),
    )
    connection.execute(
        """
        INSERT INTO game_source_ids (source, external_game_id, game_id)
        VALUES ('naver', ?, ?)
        ON CONFLICT(source, external_game_id) DO UPDATE SET game_id = excluded.game_id
        """,
        (game.game_id, game.game_id),
    )


def replace_relay_data(
    connection: sqlite3.Connection,
    relay_result: NaverRelayResult,
    *,
    source_request_id: int | None = None,
) -> tuple[int, int, int]:
    """Replace the normalized rows represented by one relay response.

    This function is intended to run inside ``Database.game_transaction``.
    Existing rows for the returned relay numbers are removed first, making a
    replay of the same raw response deterministic.
    """

    game_id = relay_result.game_id
    relay_numbers = [relay.relay_no for relay in relay_result.relays if relay.relay_no is not None]
    for relay_no in relay_numbers:
        connection.execute(
            "DELETE FROM game_events WHERE game_id = ? AND relay_no = ?",
            (game_id, relay_no),
        )
        connection.execute(
            "DELETE FROM plate_appearances WHERE game_id = ? AND relay_no = ?",
            (game_id, relay_no),
        )

    pitch_count = 0
    event_count = 0
    pa_count = 0
    for relay_index, relay in enumerate(relay_result.relays):
        relay_token = relay.relay_no if relay.relay_no is not None else f"unknown-{relay_index}"
        pa_id = f"{game_id}:{relay_token}"
        is_plate_appearance = bool(relay.result_events or relay.pitches)
        batter_id = _first_value(
            [pitch.batter_code for pitch in relay.pitches]
            + [event.batter_code for event in relay.events]
        )
        pitcher_id = _first_value(
            [pitch.pitcher_code for pitch in relay.pitches]
            + [event.pitcher_code for event in relay.events]
        )
        _ensure_player(connection, batter_id)
        _ensure_player(connection, pitcher_id)

        result_event = relay.result_events[-1] if relay.result_events else None
        first_state = next(
            (
                state
                for state in (event.current_game_state for event in relay.events)
                if state
            ),
            {},
        )
        if is_plate_appearance:
            connection.execute(
                """
                INSERT INTO plate_appearances (
                    plate_appearance_id, game_id, relay_no, inning, half,
                    batter_id, pitcher_id, outs_before, balls_before, strikes_before,
                    result_text, result_event_type, is_complete, source_request_id,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pa_id,
                    game_id,
                    relay.relay_no if relay.relay_no is not None else -(relay_index + 1),
                    relay.inning or 1,
                    _half(relay.home_or_away),
                    batter_id,
                    pitcher_id,
                    _state_int(first_state, "out"),
                    _state_int(first_state, "ball"),
                    _state_int(first_state, "strike"),
                    result_event.text if result_event else None,
                    result_event.event_type if result_event else None,
                    int(result_event is not None),
                    source_request_id,
                    _json(relay.raw),
                ),
            )
            pa_count += 1

        for event_index, event in enumerate(relay.events):
            player_id = event.batter_code or event.pitcher_code
            _ensure_player(connection, player_id)
            event_id = (
                f"{game_id}:{relay_token}:"
                f"{event.seqno if event.seqno is not None else 'event-' + str(event_index)}"
            )
            connection.execute(
                """
                INSERT INTO game_events (
                    game_event_id, game_id, relay_no, seqno, inning, half,
                    event_type, event_text, player_id, source_request_id, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    game_id,
                    relay.relay_no,
                    event.seqno,
                    event.inning,
                    _half(event.home_or_away),
                    event.event_type,
                    event.text,
                    player_id,
                    source_request_id,
                    _json(event.raw),
                ),
            )
            event_count += 1

        for pitch_index, pitch in enumerate(relay.pitches):
            _ensure_player(connection, pitch.batter_code)
            _ensure_player(connection, pitch.pitcher_code)
            pitch_id = pitch.pitch_id or (
                f"synthetic:{relay_token}:"
                f"{pitch.seqno if pitch.seqno is not None else 'pitch-' + str(pitch_index)}"
            )
            state = pitch.current_game_state
            height = plate_crossing_height(
                y0=pitch.y0,
                z0=pitch.z0,
                vy0=pitch.vy0,
                vz0=pitch.vz0,
                ay=pitch.ay,
                az=pitch.az,
                plate_y=pitch.cross_plate_y,
            )
            connection.execute(
                """
                INSERT INTO pitches (
                    pitch_id, game_id, plate_appearance_id, pitcher_id, batter_id,
                    seqno, pitch_num, pitch_result_code, pitch_result_text,
                    balls_after, strikes_after, outs_after,
                    runner_on_first, runner_on_second, runner_on_third,
                    pitch_type, speed_kph, batter_stance,
                    x0, y0, z0, vx0, vy0, vz0, ax, ay, az,
                    cross_plate_x, cross_plate_y, plate_height,
                    strike_zone_top, strike_zone_bottom, ballcount,
                    source_request_id, raw_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    pitch_id,
                    game_id,
                    pa_id,
                    pitch.pitcher_code,
                    pitch.batter_code,
                    pitch.seqno,
                    pitch.pitch_num,
                    pitch.pitch_result,
                    pitch.text,
                    _state_int(state, "ball"),
                    _state_int(state, "strike"),
                    _state_int(state, "out"),
                    _occupied(state, "base1"),
                    _occupied(state, "base2"),
                    _occupied(state, "base3"),
                    pitch.stuff,
                    _float(pitch.speed),
                    pitch.stance,
                    pitch.x0,
                    pitch.y0,
                    pitch.z0,
                    pitch.vx0,
                    pitch.vy0,
                    pitch.vz0,
                    pitch.ax,
                    pitch.ay,
                    pitch.az,
                    pitch.cross_plate_x,
                    pitch.cross_plate_y,
                    height,
                    pitch.top_sz,
                    pitch.bottom_sz,
                    str(pitch.ballcount) if pitch.ballcount is not None else None,
                    source_request_id,
                    _json(
                        {
                            "textOption": pitch.raw_text_option,
                            "ptsOption": pitch.raw_pts_option,
                        }
                    ),
                ),
            )
            pitch_count += 1

    return pa_count, pitch_count, event_count


def record_quality_issues(
    connection: sqlite3.Connection,
    *,
    issues: Iterable[QualityIssue],
    game_id: str,
    crawl_run_id: int | None,
    source: str = "naver",
) -> int:
    connection.execute(
        "DELETE FROM data_quality_issues WHERE game_id = ? AND source = ? AND status = 'open'",
        (game_id, source),
    )
    count = 0
    for issue in issues:
        connection.execute(
            """
            INSERT INTO data_quality_issues (
                crawl_run_id, game_id, source, severity, issue_code,
                message, context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                crawl_run_id,
                game_id,
                source,
                issue.severity,
                issue.code,
                issue.message,
                _json(issue.context),
            ),
        )
        count += 1
    return count


def replace_boxscore_data(
    connection: sqlite3.Connection,
    *,
    game_id: str,
    boxscore: dict[str, list[dict[str, Any]]],
    source_request_id: int | None = None,
) -> tuple[int, int]:
    """Replace official non-total player box-score rows for one game."""

    game = connection.execute(
        "SELECT away_team_id, home_team_id FROM games WHERE game_id = ?",
        (game_id,),
    ).fetchone()
    if game is None:
        raise LookupError(f"game {game_id} was not discovered")
    connection.execute("DELETE FROM batting_boxscores WHERE game_id = ?", (game_id,))
    connection.execute("DELETE FROM pitching_boxscores WHERE game_id = ?", (game_id,))

    counts = {"batting": 0, "pitching": 0}
    for category in ("batting", "pitching"):
        for row in boxscore.get(category, []):
            if row.get("is_total") or not row.get("external_player_id"):
                continue
            player_id = str(row["external_player_id"])
            player_name = str(row.get("player_name") or player_id)
            _ensure_external_player(
                connection,
                source="kbo",
                external_id=player_id,
                name=player_name,
            )
            team_id = (
                game["away_team_id"]
                if row.get("team_side") == "away"
                else game["home_team_id"]
            )
            source_team_id = row.get("team_id")
            if source_team_id and team_id:
                connection.execute(
                    """
                    INSERT INTO team_aliases (
                        source, external_team_id, team_id, source_name
                    ) VALUES ('kbo', ?, ?, ?)
                    ON CONFLICT(source, external_team_id) DO UPDATE SET
                        team_id = excluded.team_id,
                        source_name = excluded.source_name
                    """,
                    (str(source_team_id), team_id, row.get("team_name")),
                )
            metrics = row.get("metrics") or {}
            sequence = _integer(
                metrics.get("lineup_seq")
                if category == "batting"
                else metrics.get("appearance_seq")
            )
            sequence = int(row.get("row_index", 0)) if sequence is None else sequence
            if category == "batting":
                connection.execute(
                    """
                    INSERT INTO batting_boxscores (
                        game_id, team_id, player_id, lineup_seq,
                        plate_appearances, at_bats, runs, hits, doubles, triples,
                        home_runs, rbi, walks, intentional_walks, hit_by_pitch,
                        strikeouts, sacrifice_hits, sacrifice_flies, stolen_bases,
                        caught_stealing, source_request_id
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        game_id,
                        team_id,
                        player_id,
                        sequence,
                        _integer(metrics.get("plate_appearances")),
                        _integer(metrics.get("at_bats")),
                        _integer(metrics.get("runs")),
                        _integer(metrics.get("hits")),
                        _integer(metrics.get("doubles")),
                        _integer(metrics.get("triples")),
                        _integer(metrics.get("home_runs")),
                        _integer(metrics.get("rbi")),
                        _integer(metrics.get("walks")),
                        _integer(metrics.get("intentional_walks")),
                        _integer(metrics.get("hit_by_pitch")),
                        _integer(metrics.get("strikeouts")),
                        _integer(metrics.get("sacrifice_hits")),
                        _integer(metrics.get("sacrifice_flies")),
                        _integer(metrics.get("stolen_bases")),
                        _integer(metrics.get("caught_stealing")),
                        source_request_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO pitching_boxscores (
                        game_id, team_id, player_id, appearance_seq,
                        outs_recorded, batters_faced, pitches, hits, home_runs,
                        walks, intentional_walks, hit_by_pitch, strikeouts,
                        runs, earned_runs, result, source_request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        team_id,
                        player_id,
                        sequence,
                        _innings_to_outs(metrics.get("innings_pitched")),
                        _integer(metrics.get("batters_faced")),
                        _integer(metrics.get("pitches")),
                        _integer(metrics.get("hits")),
                        _integer(metrics.get("home_runs")),
                        _integer(metrics.get("walks")),
                        _integer(metrics.get("intentional_walks")),
                        _integer(metrics.get("hit_by_pitch")),
                        _integer(metrics.get("strikeouts")),
                        _integer(metrics.get("runs")),
                        _integer(metrics.get("earned_runs")),
                        metrics.get("result"),
                        source_request_id,
                    ),
                )
            counts[category] += 1
    return counts["batting"], counts["pitching"]


def replace_roster_data(
    connection: sqlite3.Connection,
    *,
    roster_date: str,
    records: Iterable[dict[str, Any]],
    source_request_id: int | None = None,
) -> int:
    """Replace the KBO roster snapshot rows represented by one response."""

    rows = [row for row in records if row.get("external_player_id")]
    team_ids = {
        _resolve_team(connection, str(row.get("team_name") or "unknown"))
        for row in rows
    }
    for team_id in team_ids:
        connection.execute(
            "DELETE FROM roster_daily WHERE roster_date = ? AND team_id = ?",
            (roster_date, team_id),
        )

    count = 0
    for row in rows:
        external_id = str(row["external_player_id"])
        name = str(row.get("player_name") or external_id)
        _ensure_external_player(
            connection,
            source="kbo",
            external_id=external_id,
            name=name,
        )
        team_id = _resolve_team(connection, str(row.get("team_name") or "unknown"))
        connection.execute(
            """
            INSERT INTO roster_daily (
                roster_date, team_id, player_id, roster_status, position,
                transaction_type, source_request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                roster_date,
                team_id,
                external_id,
                row.get("roster_status") or "registered",
                row.get("position"),
                row.get("transaction_type"),
                source_request_id,
            ),
        )
        count += 1
    return count


def replace_player_daily_data(
    connection: sqlite3.Connection,
    *,
    records: Iterable[dict[str, Any]],
    source_request_id: int | None = None,
) -> int:
    count = 0
    for record in records:
        player_id = record.get("external_player_id")
        if not player_id:
            continue
        player_id = str(player_id)
        _ensure_external_player(
            connection,
            source="kbo",
            external_id=player_id,
            name=player_id,
        )
        connection.execute(
            """
            INSERT INTO player_daily_official (
                record_date, player_id, team_id, record_type, is_month_total,
                metrics_json, source_request_id
            ) VALUES (?, ?, NULL, ?, ?, ?, ?)
            ON CONFLICT(record_date, player_id, record_type, is_month_total)
            DO UPDATE SET
                metrics_json = excluded.metrics_json,
                source_request_id = excluded.source_request_id
            """,
            (
                record["record_date"],
                player_id,
                record["record_type"],
                int(bool(record.get("is_month_total"))),
                _json(record.get("metrics") or {}),
                source_request_id,
            ),
        )
        count += 1
    return count


def set_ingestion_status(
    connection: sqlite3.Connection,
    game_id: str,
    status: str,
) -> None:
    cursor = connection.execute(
        """
        UPDATE games
        SET ingestion_status = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE game_id = ?
        """,
        (status, game_id),
    )
    if cursor.rowcount != 1:
        raise LookupError(f"game {game_id} was not discovered")


def _ensure_player(connection: sqlite3.Connection, external_id: str | None) -> None:
    if not external_id:
        return
    connection.execute(
        """
        INSERT INTO players (player_id, canonical_name)
        VALUES (?, ?)
        ON CONFLICT(player_id) DO NOTHING
        """,
        (external_id, external_id),
    )
    connection.execute(
        """
        INSERT INTO player_external_ids (
            source, external_player_id, player_id, source_name
        ) VALUES ('naver', ?, ?, NULL)
        ON CONFLICT(source, external_player_id) DO UPDATE SET
            player_id = excluded.player_id
        """,
        (external_id, external_id),
    )


def _ensure_external_player(
    connection: sqlite3.Connection,
    *,
    source: str,
    external_id: str,
    name: str,
) -> None:
    connection.execute(
        """
        INSERT INTO players (player_id, canonical_name)
        VALUES (?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            canonical_name = CASE
                WHEN players.canonical_name = players.player_id
                THEN excluded.canonical_name
                ELSE players.canonical_name
            END,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (external_id, name),
    )
    connection.execute(
        """
        INSERT INTO player_external_ids (
            source, external_player_id, player_id, source_name
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT(source, external_player_id) DO UPDATE SET
            player_id = excluded.player_id,
            source_name = excluded.source_name
        """,
        (source, external_id, external_id, name),
    )


def _resolve_team(connection: sqlite3.Connection, source_name: str) -> str:
    normalized = source_name.strip()
    team_id = TEAM_NAME_TO_ID.get(normalized)
    if team_id is None:
        row = connection.execute(
            """
            SELECT team_id FROM teams
            WHERE canonical_name = ? OR short_name = ?
            LIMIT 1
            """,
            (normalized, normalized),
        ).fetchone()
        team_id = str(row["team_id"]) if row else f"KBO:{normalized}"
    connection.execute(
        """
        INSERT INTO teams (team_id, canonical_name, short_name)
        VALUES (?, ?, ?)
        ON CONFLICT(team_id) DO UPDATE SET
            canonical_name = CASE
                WHEN teams.canonical_name = teams.team_id
                THEN excluded.canonical_name
                ELSE teams.canonical_name
            END,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (team_id, normalized, normalized),
    )
    connection.execute(
        """
        INSERT INTO team_aliases (source, external_team_id, team_id, source_name)
        VALUES ('kbo-name', ?, ?, ?)
        ON CONFLICT(source, external_team_id) DO UPDATE SET
            team_id = excluded.team_id,
            source_name = excluded.source_name
        """,
        (normalized, team_id, normalized),
    )
    return team_id
def _half(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return "bottom" if normalized in {"1", "home", "bottom", "b"} else "top"


def _first_value(values: Iterable[str | None]) -> str | None:
    return next((value for value in values if value), None)


def _state_int(state: dict[str, Any], key: str) -> int | None:
    return _integer(state.get(key))


def _occupied(state: dict[str, Any], key: str) -> int | None:
    if key not in state:
        return None
    return int(str(state.get(key, "0")) not in {"", "0", "None", "none", "null"})


def _integer(value: Any) -> int | None:
    try:
        return None if value is None else int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _innings_to_outs(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if " " in text and "/" in text:
            whole, fraction = text.split(None, 1)
            numerator, denominator = fraction.split("/", 1)
            return int(whole) * 3 + round(int(numerator) * 3 / int(denominator))
        number = float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    whole = int(number)
    decimal = round((number - whole) * 10)
    if decimal in (0, 1, 2):
        return whole * 3 + decimal
    return round(number * 3)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
