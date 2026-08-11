"""Build 2021--2025 KBO core research tables from saved raw responses.

This program never makes an HTTP request.  A game is included in the PA/pitch
tables only when every inning that the KBO official scoreboard says was played
has a readable saved Naver relay response.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]


def load_collector() -> Any:
    path = Path(__file__).with_name("crawl_research_40_110.py")
    spec = importlib.util.spec_from_file_location("kbo_collector", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the collection module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def open_writer(path: Path, columns: list[str]) -> tuple[Any, csv.DictWriter]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    return handle, writer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build KBO core marts from saved raw files.")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--years", nargs="+", type=int, default=[2021, 2022, 2023, 2024, 2025])
    return parser.parse_args()


PLAYER_GAME_COLUMNS = [
    "player_game_id", "game_id", "game_date", "season", "player_id", "player_name", "team", "opponent",
    "home_away", "rest_days", "PA", "AB", "H", "HR", "BB", "SO", "quality_flag", "issue_reason",
]
PA_COLUMNS = [
    "game_id", "game_date", "season", "pa_id", "pa_sequence", "inning", "half_inning", "batter_id", "batter_name",
    "pitcher_id", "pitcher_name", "pa_result", "score_difference", "outs", "base_state", "quality_flag", "issue_reason",
]
PITCH_COLUMNS = [
    "game_id", "game_date", "season", "pa_id", "pa_sequence", "pa_result", "pitch_id", "inning", "half_inning",
    "batter_id", "batter_name", "pitcher_id", "pitcher_name", "pitch_number_in_pa", "pitch_type", "speed", "plate_x",
    "plate_y", "quality_flag", "issue_reason",
]
INNING_QUALITY_COLUMNS = [
    "game_id", "season", "game_date", "expected_last_inning", "saved_inning_count", "game_status", "issue_reason",
]
QUALITY_COLUMNS = ["table_name", "row_count", "duplicate_key_count", "missing_or_check_count", "included_game_count", "excluded_game_count"]


def last_played_inning(module: Any, scoreboard_file: Path) -> int:
    return module.completed_innings(scoreboard_file)


def build_player_games(data_root: Path, years: set[str]) -> tuple[int, int, int]:
    tables = data_root / "tables"
    schedule = {row["game_id"]: row for row in read_csv(tables / "game_schedule.csv") if row["season"] in years and row["game_status"] == "COMPLETE"}
    source = [row for row in read_csv(tables / "player_game_boxscore.csv") if row["game_id"] in schedule]
    source.sort(key=lambda row: (row["player_id"], row["game_date"], row["game_id"]))
    rows: list[dict[str, str]] = []
    previous_date: dict[str, date] = {}
    for row in source:
        game = schedule[row["game_id"]]
        current_date = date.fromisoformat(row["game_date"])
        prior = previous_date.get(row["player_id"])
        rest_days = "" if prior is None else str(max(0, (current_date - prior).days - 1))
        previous_date[row["player_id"]] = current_date
        team = row["team"]
        home_away = row["home_away"]
        opponent = game["away_team"] if home_away == "HOME" else game["home_team"]
        rows.append({
            "player_game_id": f"{row['game_id']}_{row['player_id']}", "game_id": row["game_id"], "game_date": row["game_date"],
            "season": game["season"], "player_id": row["player_id"], "player_name": row["player_name"], "team": team,
            "opponent": opponent, "home_away": home_away, "rest_days": rest_days, "PA": row["PA"], "AB": row["AB"],
            "H": row["H"], "HR": row["HR"], "BB": row["BB"], "SO": row["SO"], "quality_flag": row["quality_flag"],
            "issue_reason": row["issue_reason"],
        })
    handle, writer = open_writer(tables / "core_player_game.csv", PLAYER_GAME_COLUMNS)
    with handle:
        writer.writerows(rows)
    duplicates = len(rows) - len({(row["game_id"], row["player_id"]) for row in rows})
    flagged = sum(row["quality_flag"] != "OK" for row in rows)
    return len(rows), duplicates, flagged


def build_relay_tables(data_root: Path, years: set[str], module: Any) -> tuple[int, int, int, int, int]:
    tables, raw = data_root / "tables", data_root / "raw"
    schedule = [row for row in read_csv(tables / "game_schedule.csv") if row["season"] in years and row["game_status"] == "COMPLETE" and row["game_id"]]
    schedule.sort(key=lambda row: (row["game_date"], row["game_id"]))
    pa_handle, pa_writer = open_writer(tables / "core_player_pa.csv", PA_COLUMNS)
    pitch_handle, pitch_writer = open_writer(tables / "core_pitch.csv", PITCH_COLUMNS)
    check_handle, check_writer = open_writer(tables / "core_inning_quality.csv", INNING_QUALITY_COLUMNS)
    pa_count = pitch_count = included = excluded = 0
    seen_pa: set[tuple[str, str]] = set()
    seen_pitch: set[tuple[str, str]] = set()
    with pa_handle, pitch_handle, check_handle:
        for index, game in enumerate(schedule, start=1):
            game_id = game["game_id"]
            try:
                last_inning = last_played_inning(module, raw / "games" / game_id / "kbo_scoreboard.json")
                relays = []
                for inning in range(1, last_inning + 1):
                    relay_file = raw / "pitches" / game_id / f"inning_{inning:02d}.json"
                    relay = module.read_saved_relay(relay_file)
                    if relay is None:
                        raise FileNotFoundError(f"missing or invalid inning {inning}")
                    relays.append(relay)
                check_writer.writerow({"game_id": game_id, "season": game["season"], "game_date": game["game_date"], "expected_last_inning": last_inning, "saved_inning_count": len(relays), "game_status": "COMPLETE", "issue_reason": ""})
                included += 1
                pa_rows: dict[str, dict[str, str]] = {}
                pitch_rows: dict[str, dict[str, str]] = {}
                for relay in relays:
                    for row in module.relay_pa_rows(relay, game_id):
                        pa_rows[row["pa_id"]] = row
                    for row in module.pitch_rows(relay, game_id):
                        if row["pitch_id"]:
                            pitch_rows[row["pitch_id"]] = row
                ordered_pa = sorted(pa_rows.values(), key=lambda row: int(row["__relay_no"]))
                sequence_by_pa = {row["pa_id"]: str(sequence) for sequence, row in enumerate(ordered_pa, start=1)}
                for row in ordered_pa:
                    row["pa_sequence"] = sequence_by_pa[row["pa_id"]]
                    pa_writer.writerow({**{key: game[key] for key in ("game_date", "season")}, **row})
                    seen_pa.add((game_id, row["pa_id"]))
                    pa_count += 1
                for row in sorted(pitch_rows.values(), key=lambda item: (int(item["__relay_no"]), int(item["pitch_number_in_pa"]))):
                    row["pa_sequence"] = sequence_by_pa.get(row["pa_id"], "")
                    pitch_writer.writerow({**{key: game[key] for key in ("game_date", "season")}, **row})
                    seen_pitch.add((game_id, row["pitch_id"]))
                    pitch_count += 1
            except Exception as exc:
                excluded += 1
                check_writer.writerow({"game_id": game_id, "season": game["season"], "game_date": game["game_date"], "expected_last_inning": "", "saved_inning_count": "", "game_status": "INCOMPLETE", "issue_reason": str(exc)})
            if index % 100 == 0 or index == len(schedule):
                print(f"build: {index}/{len(schedule)} games; complete={included}; incomplete={excluded}", flush=True)
    return pa_count, pitch_count, len(seen_pa), len(seen_pitch), excluded


def main() -> None:
    args = parse_args()
    data_root = args.data_root.resolve()
    years = {str(year) for year in args.years}
    module = load_collector()
    game_rows, game_dups, game_flagged = build_player_games(data_root, years)
    pa_rows, pitch_rows, unique_pa, unique_pitch, excluded = build_relay_tables(data_root, years, module)
    quality = [
        {"table_name": "core_player_game", "row_count": game_rows, "duplicate_key_count": game_dups, "missing_or_check_count": game_flagged, "included_game_count": "", "excluded_game_count": ""},
        {"table_name": "core_player_pa", "row_count": pa_rows, "duplicate_key_count": pa_rows - unique_pa, "missing_or_check_count": "", "included_game_count": "", "excluded_game_count": excluded},
        {"table_name": "core_pitch", "row_count": pitch_rows, "duplicate_key_count": pitch_rows - unique_pitch, "missing_or_check_count": "", "included_game_count": "", "excluded_game_count": excluded},
    ]
    handle, writer = open_writer(data_root / "tables" / "core_quality_report.csv", QUALITY_COLUMNS)
    with handle:
        writer.writerows(quality)
    print(json.dumps({"player_game_rows": game_rows, "player_game_duplicates": game_dups, "pa_rows": pa_rows, "pitch_rows": pitch_rows, "incomplete_games": excluded}, ensure_ascii=False))


if __name__ == "__main__":
    main()
