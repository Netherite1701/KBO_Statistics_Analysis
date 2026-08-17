#!/usr/bin/env python3
"""Merge the collected KBO tables into one cleaned, provenance-aware dataset.

The first inning is already present in the normalized PA/pitch tables.  In the
raw crawl it is stored as ``raw/games/<game_id>/naver_relay_inning_1.json``;
this script records that source instead of copying the large raw JSON files.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TABLES = {
    "game_schedule": [
        "game_id", "game_date", "season", "away_team", "home_team",
        "stadium", "game_status", "kbo_review_url", "quality_flag",
        "issue_reason",
    ],
    "game_pa_event": [
        "game_id", "pa_id", "pa_sequence", "inning", "half_inning",
        "batter_id", "batter_name", "pitcher_id", "pitcher_name",
        "pa_result", "score_difference", "outs", "base_state",
        "quality_flag", "issue_reason",
    ],
    "game_pa_pitch_link": [
        "game_id", "pa_id", "pa_sequence", "pa_result", "pitch_id",
        "inning", "half_inning", "batter_id", "batter_name", "pitcher_id",
        "pitcher_name", "pitch_number_in_pa", "pitch_type", "speed",
        "plate_x", "plate_y", "quality_flag", "issue_reason",
    ],
    "player_game_boxscore": [
        "game_id", "game_date", "team", "home_away", "player_id",
        "player_name", "PA", "AB", "H", "HR", "BB", "SO",
        "stats_source", "quality_flag", "issue_reason",
    ],
}


@dataclass(frozen=True)
class Source:
    name: str
    priority: int
    seasons: tuple[str, ...]


SOURCES = (
    Source("research-80-backfill", 30, ("2021",)),
    Source("research-2022-core", 50, ("2022",)),
    Source("research-2023-core", 50, ("2023",)),
    Source("research-2024-core", 50, ("2024",)),
    Source("research-2025-core", 50, ("2025",)),
    Source("research-40-110", 30, ("2026",)),
    Source("research-2026-to-0811", 20, ("2026",)),
)


def read_csv(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def value(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def table_key(table: str, row: dict[str, str]) -> tuple[str, ...] | None:
    game_id = value(row, "game_id")
    if not game_id:
        return None
    if table == "game_schedule":
        return (game_id,)
    if table == "game_pa_event":
        pa_id = value(row, "pa_id")
        return (game_id, "pa", pa_id) if pa_id else (
            game_id, "pa-fallback", value(row, "pa_sequence"),
            value(row, "inning"), value(row, "half_inning"),
            value(row, "batter_id"),
        )
    if table == "game_pa_pitch_link":
        pitch_id = value(row, "pitch_id")
        return (game_id, "pitch", pitch_id) if pitch_id else (
            game_id, "pitch-fallback", value(row, "pa_id"),
            value(row, "pitch_number_in_pa"), value(row, "inning"),
        )
    player_id = value(row, "player_id")
    return (game_id, "player", value(row, "team"), value(row, "home_away"),
            player_id, value(row, "player_name"))


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
            count += 1
    return count


def sort_rows(table: str, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if table == "game_schedule":
        return sorted(rows, key=lambda r: (value(r, "game_date"), value(r, "game_id")))
    if table == "game_pa_event":
        return sorted(rows, key=lambda r: (value(r, "game_id"),
                                           value(r, "pa_sequence"), value(r, "pa_id")))
    if table == "game_pa_pitch_link":
        return sorted(rows, key=lambda r: (value(r, "game_id"),
                                           value(r, "pa_sequence"),
                                           value(r, "pitch_number_in_pa"),
                                           value(r, "pitch_id")))
    return sorted(rows, key=lambda r: (value(r, "game_date"), value(r, "game_id"),
                                       value(r, "team"), value(r, "player_id"),
                                       value(r, "player_name")))


def input_candidates(source_root: Path, table: str) -> list[Path]:
    """Prefer marts rebuilt with the first-inning fallback when available."""
    preferred = {
        "game_pa_event": "core_player_pa.csv",
        "game_pa_pitch_link": "core_pitch.csv",
    }.get(table)
    candidates = []
    if preferred:
        candidates.append(source_root / "tables" / preferred)
    candidates.append(source_root / "tables" / f"{table}.csv")
    return candidates


def in_scope(source: Source, table: str, row: dict[str, str]) -> bool:
    """Keep regular-season games through the stated 2026 crawl cutoff."""
    if value(row, "game_status").startswith("EXCLUDED_"):
        return False
    if source.name == "research-2026-to-0811":
        game_date = value(row, "game_date") or value(row, "game_id")[:8]
        if game_date and game_date > "2026-08-11":
            return False
    return True


def build_first_inning_report(repo_root: Path, output_root: Path,
                              schedule_rows: list[dict[str, str]],
                              source_for_game: dict[str, Source],
                              pa_rows: list[dict[str, str]],
                              pitch_rows: list[dict[str, str]]) -> int:
    pa_games = {value(row, "game_id") for row in pa_rows if value(row, "inning") == "1"}
    pitch_games = {value(row, "game_id") for row in pitch_rows if value(row, "inning") == "1"}
    report: list[dict[str, str]] = []
    for schedule in schedule_rows:
        game_id = value(schedule, "game_id")
        source = source_for_game.get(game_id)
        root = repo_root / "data" / source.name if source else Path()
        raw_first = root / "raw" / "games" / game_id / "naver_relay_inning_1.json"
        normalized_first = root / "raw" / "pitches" / game_id / "inning_01.json"
        raw_exists = bool(source and raw_first.is_file())
        normalized_exists = bool(source and normalized_first.is_file())
        has_pa = game_id in pa_games
        has_pitch = game_id in pitch_games
        if has_pa and has_pitch:
            status = "TABLES_HAVE_INNING_1"
        elif has_pa and raw_exists:
            status = "PA_EVENT_FROM_RAW_FIRST_INNING"
        elif has_pitch:
            status = "PITCH_LINK_HAVE_INNING_1"
        elif raw_exists:
            status = "RAW_FIRST_INNING_ONLY"
        else:
            status = "NO_FIRST_INNING_FOUND"
        report.append({
            "game_id": game_id,
            "game_date": value(schedule, "game_date"),
            "season": value(schedule, "season"),
            "source_root": source.name if source else "",
            "raw_first_inning": str(raw_first.relative_to(repo_root)).replace("\\", "/") if raw_exists else "",
            "standardized_first_inning": str(normalized_first.relative_to(repo_root)).replace("\\", "/") if normalized_exists else "",
            "pa_event_inning_1": "Y" if has_pa else "N",
            "pitch_link_inning_1": "Y" if has_pitch else "N",
            "status": status,
        })
    fields = ["game_id", "game_date", "season", "source_root", "raw_first_inning",
              "standardized_first_inning", "pa_event_inning_1", "pitch_link_inning_1", "status"]
    return write_csv(output_root / "first_inning_source.csv", fields,
                     sorted(report, key=lambda r: (r["game_date"], r["game_id"])))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, default=Path("data/research-merged"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_root = (repo_root / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    all_rows: dict[str, dict[tuple[str, ...], dict[str, str]]] = {table: {} for table in TABLES}
    source_for_game: dict[str, Source] = {}
    manifests: list[dict[str, str]] = []
    unresolved: dict[str, list[dict[str, str]]] = defaultdict(list)
    first_seen: dict[str, dict[tuple[str, ...], dict[str, str]]] = {table: {} for table in TABLES}

    for source in SOURCES:
        source_root = repo_root / "data" / source.name
        for table, fields in TABLES.items():
            path = next((candidate for candidate in input_candidates(source_root, table)
                         if candidate.is_file()), None)
            if path is None:
                manifests.append({"source_root": source.name, "season_filter": ",".join(source.seasons),
                                  "table": table, "input_rows": "0", "accepted_rows": "0",
                                  "duplicate_rows": "0", "conflicting_duplicates": "0",
                                  "unresolved_rows": "0", "excluded_rows": "0",
                                  "note": "file_missing"})
                continue
            input_rows = accepted = duplicates = conflicts = unresolved_count = excluded = 0
            for row in read_csv(path):
                season = value(row, "season") or value(row, "game_id")[:4]
                if season not in source.seasons:
                    continue
                if not in_scope(source, table, row):
                    excluded += 1
                    continue
                input_rows += 1
                key = table_key(table, row)
                if key is None:
                    unresolved[table].append(row)
                    unresolved_count += 1
                    continue
                old = all_rows[table].get(key)
                if old is None:
                    all_rows[table][key] = row
                    first_seen[table][key] = {"source_root": source.name, "priority": str(source.priority)}
                    accepted += 1
                    if table == "game_schedule":
                        source_for_game[value(row, "game_id")] = source
                    continue
                duplicates += 1
                if old != row:
                    conflicts += 1
                old_source = first_seen[table][key]
                if source.priority > int(old_source["priority"]):
                    all_rows[table][key] = row
                    first_seen[table][key] = {"source_root": source.name, "priority": str(source.priority)}
                    if table == "game_schedule":
                        source_for_game[value(row, "game_id")] = source
            manifests.append({"source_root": source.name, "season_filter": ",".join(source.seasons),
                              "table": table, "input_rows": str(input_rows), "accepted_rows": str(accepted),
                              "duplicate_rows": str(duplicates), "conflicting_duplicates": str(conflicts),
                              "unresolved_rows": str(unresolved_count), "excluded_rows": str(excluded),
                              "note": path.name if path.name.startswith("core_") else ""})

    merged: dict[str, list[dict[str, str]]] = {}
    for table, fields in TABLES.items():
        merged[table] = sort_rows(table, list(all_rows[table].values()))
        write_csv(output_root / "tables" / f"{table}.csv", fields, merged[table])
        if unresolved[table]:
            write_csv(output_root / "tables" / f"unresolved_{table}.csv", fields, unresolved[table])

    manifest_fields = ["source_root", "season_filter", "table", "input_rows", "accepted_rows",
                       "duplicate_rows", "conflicting_duplicates", "unresolved_rows", "excluded_rows", "note"]
    write_csv(output_root / "merge_manifest.csv", manifest_fields, manifests)
    first_count = build_first_inning_report(
        repo_root, output_root, merged["game_schedule"], source_for_game,
        merged["game_pa_event"], merged["game_pa_pitch_link"]
    )
    quality_fields = ["table", "merged_rows", "blank_game_id_rows", "inning_1_rows", "quality"]
    quality_rows = []
    for table, rows in merged.items():
        blank = sum(1 for row in rows if not value(row, "game_id"))
        inning_1 = sum(1 for row in rows if value(row, "inning") == "1")
        quality_rows.append({"table": table, "merged_rows": str(len(rows)),
                             "blank_game_id_rows": str(blank), "inning_1_rows": str(inning_1),
                             "quality": "OK" if blank == 0 else "CHECK"})
    quality_rows.append({"table": "first_inning_source", "merged_rows": str(first_count),
                         "blank_game_id_rows": "0", "inning_1_rows": "",
                         "quality": "CHECK_RAW_FIRST_INNING_ONLY_ROWS"})
    write_csv(output_root / "merge_quality_report.csv", quality_fields, quality_rows)
    print(f"Merged dataset: {output_root}")
    for table, rows in merged.items():
        print(f"  {table}: {len(rows):,} rows")
    print(f"  first_inning_source: {first_count:,} games")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
