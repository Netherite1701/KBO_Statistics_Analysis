"""Merge range-sharded official daily-record CSVs into one canonical table."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "data" / "official-player-daily"
KEY = ("player_id", "game_date", "game_id")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    root = args.output_root.resolve()
    part_files = sorted(root.glob("official_player_daily.part-*.csv"))
    if not part_files:
        raise SystemExit("No part CSVs found")

    fieldnames: list[str] = []
    rows_by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    duplicate_keys = 0
    source_rows = 0
    for path in part_files:
        current_fields, rows = read_csv(path)
        if not fieldnames:
            fieldnames = current_fields
        if current_fields != fieldnames:
            raise SystemExit(f"Field mismatch: {path}")
        for row in rows:
            source_rows += 1
            key = tuple(row.get(name, "") for name in KEY)
            if key in rows_by_key:
                duplicate_keys += 1
            rows_by_key[key] = row

    output = root / "official_player_daily.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(rows_by_key.values(), key=lambda row: tuple(row.get(name, "") for name in ("game_date", "player_id", "game_id"))))

    error_rows: list[dict[str, str]] = []
    for path in sorted((root / "logs").glob("collection_errors.part-*.csv")):
        _, rows = read_csv(path)
        error_rows.extend(rows)
    error_output = root / "logs" / "collection_errors.csv"
    error_output.parent.mkdir(parents=True, exist_ok=True)
    with error_output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["year", "player_id", "error"])
        writer.writeheader()
        writer.writerows(error_rows)

    print(f"part_files={len(part_files)}")
    print(f"source_rows={source_rows}")
    print(f"merged_rows={len(rows_by_key)}")
    print(f"duplicate_keys={duplicate_keys}")
    print(f"errors={len(error_rows)}")


if __name__ == "__main__":
    main()
