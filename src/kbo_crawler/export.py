"""Stable exports for analysis code and the pitch simulator."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


PITCH_EXPORT_COLUMNS = (
    "game_id",
    "plate_appearance_id",
    "pitch_id",
    "inning",
    "half",
    "relay_no",
    "seqno",
    "pitch_num",
    "batter_id",
    "pitcher_id",
    "pitch_result",
    "pitch_type",
    "speed_kph",
    "x0",
    "y0",
    "z0",
    "vx0",
    "vy0",
    "vz0",
    "ax",
    "ay",
    "az",
    "cross_plate_x",
    "cross_plate_y",
    "plate_height",
    "strike_zone_top",
    "strike_zone_bottom",
    "ballcount",
    "result_text",
)


def export_pitches(
    connection: sqlite3.Connection,
    output_path: str | Path,
    *,
    game_id: str | None = None,
    season: int | None = None,
) -> int:
    """Export pitches in source chronology and return the row count."""

    if game_id is not None and season is not None:
        raise ValueError("choose either game_id or season, not both")

    where = ""
    parameters: list[object] = []
    if game_id is not None:
        where = "WHERE p.game_id = ?"
        parameters.append(game_id)
    elif season is not None:
        where = "WHERE g.season = ?"
        parameters.append(season)

    rows = connection.execute(
        f"""
        SELECT
            p.game_id,
            p.plate_appearance_id,
            p.pitch_id,
            pa.inning,
            pa.half,
            pa.relay_no,
            p.seqno,
            p.pitch_num,
            p.batter_id,
            p.pitcher_id,
            COALESCE(p.pitch_result_text, p.pitch_result_code) AS pitch_result,
            p.pitch_type,
            p.speed_kph,
            p.x0,
            p.y0,
            p.z0,
            p.vx0,
            p.vy0,
            p.vz0,
            p.ax,
            p.ay,
            p.az,
            p.cross_plate_x,
            p.cross_plate_y,
            p.plate_height,
            p.strike_zone_top,
            p.strike_zone_bottom,
            p.ballcount,
            pa.result_text
        FROM pitches AS p
        JOIN games AS g ON g.game_id = p.game_id
        LEFT JOIN plate_appearances AS pa
            ON pa.plate_appearance_id = p.plate_appearance_id
        {where}
        ORDER BY
            g.game_date,
            p.game_id,
            COALESCE(pa.relay_no, 2147483647),
            COALESCE(p.seqno, 2147483647),
            COALESCE(p.pitch_num, 2147483647),
            p.pitch_id
        """,
        parameters,
    ).fetchall()

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(PITCH_EXPORT_COLUMNS)
        writer.writerows(tuple(row) for row in rows)
    return len(rows)
