"""Collect KBO official hitter daily-record pages for the saved player seasons.

The existing player_daily_official tables are Naver-derived and intentionally
flagged CHECK. This collector keeps KBO HTML separately and writes a new
official_player_daily.csv without overwriting those tables. It is resumable:
already saved player-season HTML files are skipped.
"""

from __future__ import annotations

import argparse
import csv
import html
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data" / "official-player-daily"
URL = "https://www.koreabaseball.com/Record/Player/HitterDetail/Daily.aspx"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
FIELDS = ["Date", "Opponent", "AVG1", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "HBP", "SO", "GDP", "AVG2"]
OUTPUT_FIELDS = [
    "player_id", "player_name", "game_date", "game_id", "team", "opponent",
    "AVG1", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS",
    "BB", "HBP", "SO", "GDP", "AVG2", "record_source", "quality_flag", "issue_reason", "source_file",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect KBO official hitter daily records.")
    parser.add_argument("--delay", type=float, default=0.6, help="Delay between KBO requests in seconds.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start-index", type=int, default=1, help="1-based inclusive target index.")
    parser.add_argument("--end-index", type=int, default=None, help="1-based inclusive target index.")
    parser.add_argument("--part-name", default="", help="Write a separate partial CSV/log for parallel workers.")
    return parser.parse_args()


def source_roots() -> list[tuple[Path, int, int]]:
    return [
        (ROOT / "data" / "research-80-backfill", 2021, 2024),
        (ROOT / "data" / "research-2025-core", 2025, 2025),
        (ROOT / "data" / "research-40-110", 2026, 2026),
        (ROOT / "data" / "research-2026-to-0811", 2026, 2026),
    ]


def load_targets() -> tuple[dict[tuple[int, str], str], dict[tuple[int, str, str], list[dict[str, str]]]]:
    names: dict[tuple[int, str], str] = {}
    games: dict[tuple[int, str, str], list[dict[str, str]]] = defaultdict(list)
    for root, first_year, last_year in source_roots():
        rows = read_csv(root / "tables" / "player_game_boxscore.csv")
        schedule = {row.get("game_id", ""): row for row in read_csv(root / "tables" / "game_schedule.csv")}
        for row in rows:
            player_id = row.get("player_id", "").strip()
            game_date = row.get("game_date", "").strip()
            if not player_id or not game_date:
                continue
            year = int(game_date[:4])
            if not first_year <= year <= last_year:
                continue
            names[(year, player_id)] = row.get("player_name", "").strip()
            game = schedule.get(row.get("game_id", ""), {})
            team = row.get("team", "").strip()
            opponent = game.get("home_team", "") if row.get("home_away") == "AWAY" else game.get("away_team", "")
            games[(year, player_id, game_date)].append({"game_id": row.get("game_id", ""), "team": team, "opponent": opponent})
    return names, games


def post_season(session: requests.Session, player_id: str, year: int) -> bytes:
    url = f"{URL}?playerId={player_id}"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content.decode("utf-8-sig", errors="replace"), "html.parser")
    season_field = "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$ddlYear"
    payload = {
        str(node.get("name")): str(node.get("value", ""))
        for node in soup.select("input[type=hidden][name]")
    }
    payload.update({
        "__EVENTTARGET": season_field,
        "__EVENTARGUMENT": "",
        season_field: str(year),
        "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$ddlSeries": "0",
    })
    response = session.post(url, data=payload, headers={"Referer": url}, timeout=30)
    response.raise_for_status()
    return response.content


def parse_rows(content: bytes, year: int) -> list[dict[str, str]]:
    soup = BeautifulSoup(content.decode("utf-8-sig", errors="replace"), "html.parser")
    rows: list[dict[str, str]] = []
    for table in soup.select(".tbl-type02"):
        for tr in table.select("tbody tr"):
            values = [html.unescape(cell.get_text(" ", strip=True)).replace("\xa0", "").strip() for cell in tr.select("td")]
            if len(values) != len(FIELDS) or "." not in values[0]:
                continue
            month, day = values[0].split(".", 1)
            try:
                game_date = date(year, int(month), int(day)).isoformat()
            except ValueError:
                continue
            rows.append({**dict(zip(FIELDS, values)), "game_date": game_date})
    return rows


def write_output(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda row: (row["game_date"], row["player_id"], row["game_id"]))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    output_root = args.output_root.resolve()
    raw_root = output_root / "raw"
    log_root = output_root / "logs"
    suffix = f".{args.part_name}" if args.part_name else ""
    output_file = output_root / f"official_player_daily{suffix}.csv"
    names, games = load_targets()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest"})
    existing = read_csv(output_file)
    all_targets = sorted(names)
    start = max(1, args.start_index)
    end = min(len(all_targets), args.end_index or len(all_targets))
    targets = all_targets[start - 1:end]
    errors: list[dict[str, str]] = []
    selected_player_seasons = set(targets)
    existing = [
        row for row in existing
        if not args.part_name
        or (row.get("player_id", ""), row.get("game_date", "")[:4]) in {
            (player_id, str(year)) for year, player_id in selected_player_seasons
        }
    ]
    by_key = {(row.get("player_id", ""), row.get("game_date", ""), row.get("game_id", "")): row for row in existing}
    for index, (year, player_id) in enumerate(targets, start=1):
        raw_file = raw_root / str(year) / f"kbo_hitter_daily_{player_id}.html"
        try:
            if raw_file.exists():
                content = raw_file.read_bytes()
            else:
                content = post_season(session, player_id, year)
                raw_file.parent.mkdir(parents=True, exist_ok=True)
                raw_file.write_bytes(content)
            for parsed in parse_rows(content, year):
                matches = games.get((year, player_id, parsed["game_date"]), [])
                match = matches[0] if len(matches) == 1 else {}
                key = (player_id, parsed["game_date"], match.get("game_id", ""))
                by_key[key] = {
                    "player_id": player_id, "player_name": names[(year, player_id)], "game_date": parsed["game_date"],
                    "game_id": match.get("game_id", ""), "team": match.get("team", ""), "opponent": parsed["Opponent"],
                    **{field: parsed[field] for field in FIELDS[2:] if field != "Date"},
                    "record_source": "KBO official HitterDetail/Daily.aspx",
                    "quality_flag": "OK" if len(matches) == 1 else "CHECK",
                    "issue_reason": "" if len(matches) == 1 else "Official daily row has no unique game_id mapping (doubleheader or unmatched opponent).",
                    "source_file": str(raw_file.relative_to(output_root)),
                }
            if index % 20 == 0:
                write_output(output_file, list(by_key.values()))
                print(f"official daily: {index}/{len(targets)} player-seasons; rows={len(by_key)}", flush=True)
        except Exception as exc:
            errors.append({"year": str(year), "player_id": player_id, "error": str(exc)})
        time.sleep(args.delay)
    write_output(output_file, list(by_key.values()))
    log_root.mkdir(parents=True, exist_ok=True)
    error_file = log_root / f"collection_errors{suffix}.csv"
    with error_file.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["year", "player_id", "error"])
        writer.writeheader(); writer.writerows(errors)
    print(f"official_daily_target_range={start}-{end}")
    print(f"official_daily_player_seasons={len(targets)}")
    print(f"official_daily_rows={len(by_key)}")
    print(f"errors={len(errors)}")


if __name__ == "__main__":
    main()
