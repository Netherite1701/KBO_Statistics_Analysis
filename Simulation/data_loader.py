"""Read normalized pitch data without reconstructing plate appearances."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {
    "game_id",
    "plate_appearance_id",
    "pitch_id",
    "inning",
    "half",
    "relay_no",
    "pitch_num",
    "x0",
    "y0",
    "z0",
    "vx0",
    "vy0",
    "vz0",
    "ax",
    "ay",
    "az",
    "cross_plate_y",
}


def list_games(database_path: str | Path) -> pd.DataFrame:
    with sqlite3.connect(database_path) as connection:
        return pd.read_sql_query(
            """
            SELECT game_id, game_date, away_team_id, home_team_id,
                   away_score, home_score, ingestion_status
            FROM games
            WHERE EXISTS (
                SELECT 1 FROM pitches WHERE pitches.game_id = games.game_id
            )
            ORDER BY game_date DESC, game_id
            """,
            connection,
        )


def load_game(database_path: str | Path, game_id: str) -> pd.DataFrame:
    with sqlite3.connect(database_path) as connection:
        frame = pd.read_sql_query(
            """
            SELECT
                p.game_id, p.plate_appearance_id, p.pitch_id,
                pa.inning, pa.half, pa.relay_no, p.seqno, p.pitch_num,
                p.batter_id, batter.canonical_name AS batter_name,
                p.pitcher_id, pitcher.canonical_name AS pitcher_name,
                p.pitch_result_text AS pitch_result,
                p.pitch_type, p.speed_kph,
                p.x0, p.y0, p.z0, p.vx0, p.vy0, p.vz0,
                p.ax, p.ay, p.az, p.cross_plate_x, p.cross_plate_y,
                p.plate_height, p.strike_zone_top, p.strike_zone_bottom,
                pa.result_text
            FROM pitches AS p
            JOIN plate_appearances AS pa
              ON pa.plate_appearance_id = p.plate_appearance_id
            LEFT JOIN players AS batter ON batter.player_id = p.batter_id
            LEFT JOIN players AS pitcher ON pitcher.player_id = p.pitcher_id
            WHERE p.game_id = ?
            ORDER BY pa.relay_no, COALESCE(p.seqno, 2147483647),
                     COALESCE(p.pitch_num, 2147483647), p.pitch_id
            """,
            connection,
            params=(game_id,),
        )
    _validate(frame)
    return frame


def load_export(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    _validate(frame)
    return frame


def _validate(frame: pd.DataFrame) -> None:
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(
            "This file is not a normalized crawler export. Missing columns: "
            + ", ".join(missing)
        )
