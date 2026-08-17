"""선수×경기 표의 한 행을 KBO 공식 선수 일별 기록과 직접 대조한다."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from crawl_research_40_110 import RAW_ROOT, TABLE_ROOT, LOG_ROOT, USER_AGENT


FIELDS = ["Date", "Opponent", "AVG1", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "HBP", "SO", "GDP", "AVG2"]
COMPARE_FIELDS = ["PA", "AB", "H", "HR", "BB", "SO"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="선수×경기 표 한 행의 KBO 공식 일별 기록 대조")
    parser.add_argument("--game-id", help="검사할 KBO game_id. 생략하면 표의 첫 행")
    parser.add_argument("--player-id", help="검사할 선수 번호. game-id와 같이 쓴다.")
    parser.add_argument("--data-root", type=Path, help="검사할 수집 결과 폴더. 기본값은 data/research-40-110.")
    return parser.parse_args()


def load_target(args: argparse.Namespace, table_root: Path) -> dict[str, str]:
    with (table_root / "player_game_boxscore.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if args.game_id or args.player_id:
        for row in rows:
            if row["game_id"] == args.game_id and row["player_id"] == args.player_id:
                return row
        raise SystemExit("지정한 game_id + player_id 행을 찾지 못했습니다.")
    if not rows:
        raise SystemExit("player_game_boxscore.csv가 비어 있습니다.")
    return rows[0]


def kbo_daily_row(player_id: str, game_date: str, raw_root: Path) -> tuple[dict[str, str] | None, str]:
    url = f"https://www.koreabaseball.com/Record/Player/HitterDetail/Daily.aspx?playerId={player_id}"
    session = requests.Session()
    response = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    # KBO's daily-record page opens on the present season.  Its season selector
    # is an ASP.NET postback, so selecting the target season is required before
    # looking for a historical game.
    initial_soup = BeautifulSoup(response.content.decode("utf-8-sig", errors="replace"), "html.parser")
    season_field = "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$ddlYear"
    post_data = {
        str(node.get("name")): str(node.get("value", ""))
        for node in initial_soup.select("input[type=hidden][name]")
    }
    post_data.update({
        "__EVENTTARGET": season_field,
        "__EVENTARGUMENT": "",
        season_field: game_date[:4],
        "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$ddlSeries": "0",
    })
    response = session.post(url, data=post_data, headers={"User-Agent": USER_AGENT, "Referer": url}, timeout=30)
    response.raise_for_status()
    source_dir = raw_root / "validation"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / f"kbo_hitter_daily_{player_id}.html").write_bytes(response.content)
    soup = BeautifulSoup(response.content.decode("utf-8-sig", errors="replace"), "html.parser")
    target_date = game_date[5:].replace("-", ".")
    for table in soup.select(".tbl-type02"):
        for tr in table.select("tbody tr"):
            values = [cell.get_text(" ", strip=True) for cell in tr.select("td")]
            if len(values) == len(FIELDS) and values[0] == target_date:
                return dict(zip(FIELDS, values)), url
    return None, url


def main() -> None:
    args = parse_args()
    data_root = args.data_root.resolve() if args.data_root else None
    table_root = data_root / "tables" if data_root else TABLE_ROOT
    raw_root = data_root / "raw" if data_root else RAW_ROOT
    log_root = data_root / "logs" if data_root else LOG_ROOT
    target = load_target(args, table_root)
    official, url = kbo_daily_row(target["player_id"], target["game_date"], raw_root)
    results = []
    for field in COMPARE_FIELDS:
        official_value = official.get(field, "") if official else ""
        results.append({
            "game_id": target["game_id"], "game_date": target["game_date"], "player_id": target["player_id"], "player_name": target["player_name"],
            "field": field, "source_value": target[field], "kbo_daily_value": official_value,
            "comparison_status": "MATCH" if official and target[field] == official_value else "MISSING_KBO_ROW" if not official else "MISMATCH",
            "source_url": url,
        })
    log_root.mkdir(parents=True, exist_ok=True)
    output = log_root / "sample_record_validation.csv"
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    matches = sum(row["comparison_status"] == "MATCH" for row in results)
    print(f"{output}: {matches}/{len(results)} fields matched")


if __name__ == "__main__":
    main()
