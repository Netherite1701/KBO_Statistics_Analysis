"""KBO 연구순서 40~110용 공식 기록 수집기.

기존 저장소의 `crawling-game-test2.py`와
`final/_crawling-pitch+game_final.py`가 사용하는 KBO/Naver 요청 방식을
한 프로그램으로 정리했다.  원본 응답은 `data/research_40_110/raw/`에,
분석용 표는 `data/research_40_110/tables/`에 저장한다.

중요: 이 프로그램은 수집되지 않은 값을 0으로 만들지 않는다. 연결할 수
없는 기록은 빈 값과 quality_flag / issue_reason으로 남긴다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "research_40_110"
RAW_ROOT = DATA_ROOT / "raw"
TABLE_ROOT = DATA_ROOT / "tables"
LOG_ROOT = DATA_ROOT / "logs"
KBO_BASE = "https://www.koreabaseball.com"
SCHEDULE_URL = f"{KBO_BASE}/ws/Schedule.asmx/GetScheduleList"
SCOREBOARD_URL = f"{KBO_BASE}/ws/Schedule.asmx/GetScoreBoardScroll"
BOXSCORE_URL = f"{KBO_BASE}/ws/Schedule.asmx/GetBoxScoreScroll"
ROSTER_URL = f"{KBO_BASE}/Player/RegisterAll.aspx"
NAVER_RELAY_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/relay"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

SCHEDULE_COLUMNS = [
    "game_id", "game_date", "season", "away_team", "home_team", "stadium",
    "game_status", "kbo_review_url", "quality_flag", "issue_reason",
]
DAILY_COLUMNS = [
    "player_id", "player_name", "game_date", "game_id", "team", "PA", "AB", "H", "HR", "BB", "SO",
    "record_source", "quality_flag", "issue_reason",
]
MISSING_GAME_COLUMNS = ["game_date", "away_team", "home_team", "stadium", "collection_status", "issue_reason"]
SEASON_CHECK_COLUMNS = ["season", "team", "schedule_game_count", "saved_player_game_count", "difference", "check_result", "note"]
PA_SEQUENCE_COLUMNS = ["game_id", "batter_id", "batter_name", "inning", "half_inning", "pa_sequence", "pa_id", "pa_result", "pitch_count", "sequence_check", "issue_reason"]
PA_BOXSCORE_COLUMNS = ["game_id", "player_id", "player_name", "boxscore_PA", "reconstructed_PA", "difference", "quality_flag", "issue_reason"]
CROSSWALK_COLUMNS = ["kbo_game_id", "naver_game_id", "game_date", "matching_rule", "verification_status", "issue_reason"]
ROSTER_COLUMNS = [
    "player_id", "player_name", "game_date", "team", "position_group",
    "is_in_first_team", "source_url", "quality_flag", "issue_reason",
]
BOX_COLUMNS = [
    "game_id", "game_date", "team", "home_away", "player_id", "player_name",
    "PA", "AB", "H", "HR", "BB", "SO", "stats_source", "quality_flag", "issue_reason",
]
PITCH_COLUMNS = [
    "game_id", "pa_id", "pa_sequence", "pa_result", "pitch_id", "inning", "half_inning", "batter_id",
    "batter_name", "pitcher_id", "pitcher_name", "pitch_number_in_pa", "pitch_type",
    "speed", "plate_x", "plate_y", "quality_flag", "issue_reason",
]
PA_EVENT_COLUMNS = [
    "game_id", "pa_id", "pa_sequence", "inning", "half_inning", "batter_id", "batter_name",
    "pitcher_id", "pitcher_name", "pa_result", "score_difference", "outs", "base_state",
    "quality_flag", "issue_reason",
]
INNING_COLLECTION_COLUMNS = [
    "game_id", "season", "game_date", "inning", "expected_last_inning", "raw_file",
    "relay_event_count", "collection_status", "issue_reason",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KBO 연구순서 40~110 공식 기록 수집기")
    parser.add_argument("--years", nargs="+", type=int, default=[2026], help="수집할 시즌. 예: --years 2021 2022")
    parser.add_argument("--months", nargs="+", type=int, default=list(range(1, 13)), help="수집할 달(1~12)")
    parser.add_argument("--phases", nargs="+", choices=["schedule", "roster", "games", "pitches"], default=["schedule", "roster"], help="실행할 수집 단계")
    parser.add_argument("--max-games", type=int, default=0, help="게임 단계의 최대 경기 수. 0은 제한 없음")
    parser.add_argument("--rate-seconds", type=float, default=0.6, help="요청 사이 대기 시간(초)")
    parser.add_argument("--refresh", action="store_true", help="이미 저장한 원본도 다시 받음")
    parser.add_argument(
        "--data-root",
        type=Path,
        help="결과를 저장할 폴더. 지정하지 않으면 data/research_40_110을 사용한다.",
    )
    return parser.parse_args()


def configure_data_root(data_root: Path | None) -> None:
    """Keep a backfill run separate from an already verified collection."""
    if data_root is None:
        return
    global DATA_ROOT, RAW_ROOT, TABLE_ROOT, LOG_ROOT
    DATA_ROOT = data_root.resolve()
    RAW_ROOT = DATA_ROOT / "raw"
    TABLE_ROOT = DATA_ROOT / "tables"
    LOG_ROOT = DATA_ROOT / "logs"


class Collector:
    def __init__(self, delay: float, refresh: bool) -> None:
        self.delay = delay
        self.refresh = refresh
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{KBO_BASE}/Schedule/Schedule.aspx?seriesId=1",
        })
        self.errors: list[dict[str, str]] = []

    def pause(self) -> None:
        time.sleep(self.delay)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        # 투구 이닝 중계는 간헐적으로 오래 멈출 수 있다. 한 요청 때문에
        # 전체 수집이 멈추지 않게 10초 제한·최대 3회 재시도를 적용한다.
        for attempt in range(3):
            try:
                response = self.session.get(url, params=params, timeout=10)
                response.raise_for_status()
                self.pause()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 + attempt)
        raise RuntimeError(f"GET failed after 3 attempts: {last_error}")

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(url, data=payload, timeout=30)
        response.raise_for_status()
        self.pause()
        return json.loads(response.content.decode("utf-8-sig"))

    def post_html(self, url: str, payload: dict[str, Any]) -> str:
        response = self.session.post(url, data=payload, headers={"Referer": ROSTER_URL}, timeout=30)
        response.raise_for_status()
        self.pause()
        return response.content.decode("utf-8-sig", errors="replace")


def ensure_dirs() -> None:
    for folder in (RAW_ROOT / "schedule", RAW_ROOT / "roster", RAW_ROOT / "games", RAW_ROOT / "pitches", TABLE_ROOT, LOG_ROOT):
        folder.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or "")).replace("&nbsp;", " ")).strip()


def extract_game_id(value: str) -> str:
    match = re.search(r"[?&]gameId=([^&#\"']+)", value)
    return match.group(1) if match else ""


def extract_date(value: str) -> str:
    match = re.search(r"[?&]gameDate=(\d{8})", value)
    if not match:
        return ""
    return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()


def schedule_rows(payload: Any, season: int) -> list[dict[str, str]]:
    """KBO 월별 일정 응답에서 완료 경기의 game_id를 찾는다.

    KBO 응답의 세부 열 이름이 바뀔 수 있어 `review` 링크를 기준으로
    ID를 확인한다. 링크가 없는 일정은 아직 종료되지 않았거나 화면 구조가
    달라진 경우이므로 목록에는 남기되 game_id를 비워 둔다.
    """
    # KBO는 보통 표 모양의 {rows: [{row: [...]}, ...]}를 반환한다. 과거
    # 버전에서 목록 형태를 반환한 경우도 함께 처리한다.
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        table_rows = payload["rows"]
        rows: list[dict[str, str]] = []
        last_game_date = ""
        for table_row in table_rows:
            cells = table_row.get("row", []) if isinstance(table_row, dict) else []
            raw_cells = [str(cell.get("Text", "")) for cell in cells if isinstance(cell, dict)]
            day_cell = next((str(cell.get("Text", "")) for cell in cells if isinstance(cell, dict) and "day" in str(cell.get("Class", "")).lower()), "")
            day_match = re.search(r"(\d{2})\.(\d{2})", day_cell)
            if day_match:
                last_game_date = date(season, int(day_match.group(1)), int(day_match.group(2))).isoformat()
            review_index = next((index for index, value in enumerate(raw_cells) if "gameId=" in value and "REVIEW" in value.upper()), -1)
            review_html = raw_cells[review_index] if review_index >= 0 else ""
            game_id = extract_game_id(review_html)
            game_date = extract_date(review_html) or last_game_date
            # 리뷰 링크가 없는 취소·예정 경기도 빠뜨리지 않고 기록한다.
            play_index = review_index - 1 if review_index > 0 else next((index for index, value in enumerate(raw_cells) if re.search(r">\s*vs\s*<|\bvs\b", value, flags=re.I)), -1)
            play_html = raw_cells[play_index] if play_index >= 0 else ""
            play_text = BeautifulSoup(play_html, "html.parser").get_text(" ", strip=True)
            # 점수 사이의 vs를 기준으로 팀 이름만 남긴다.
            team_match = re.search(r"^\s*(.*?)\s+\d+\s+vs\s+\d+\s+(.*?)\s*$", play_text, flags=re.I)
            plain_team_match = re.search(r"^\s*(.*?)\s+vs\s+(.*?)\s*$", play_text, flags=re.I)
            away_team = team_match.group(1).strip() if team_match else plain_team_match.group(1).strip() if plain_team_match else ""
            home_team = team_match.group(2).strip() if team_match else plain_team_match.group(2).strip() if plain_team_match else ""
            stadium_index = review_index + 4 if review_index >= 0 else play_index + 5
            stadium = text(BeautifulSoup(raw_cells[stadium_index], "html.parser").get_text(" ", strip=True)) if len(raw_cells) > stadium_index else ""
            if not (game_date and (game_id or (away_team and home_team))):
                continue
            is_all_star = {away_team, home_team} == {"나눔", "드림"}
            game_status = "EXCLUDED_ALL_STAR" if is_all_star else "COMPLETE" if game_id else "NO_REVIEW_ID"
            rows.append({
                "game_id": game_id, "game_date": game_date, "season": str(season),
                "away_team": away_team, "home_team": home_team, "stadium": stadium,
                "game_status": game_status,
                "kbo_review_url": f"{KBO_BASE}/Schedule/GameCenter/Main.aspx?gameDate={game_date.replace('-', '')}&gameId={game_id}&section=REVIEW" if game_id and game_date else "",
                "quality_flag": "CHECK" if is_all_star or not (game_id and game_date and away_team and home_team) else "OK",
                "issue_reason": "All-Star game is outside the regular-season research scope" if is_all_star else "" if game_id and game_date and away_team and home_team else "Could not read one or more schedule fields",
            })
        return rows
    candidates = payload if isinstance(payload, list) else payload.get("data", payload.get("list", []))
    rows: list[dict[str, str]] = []
    for item in candidates if isinstance(candidates, list) else []:
        raw_values = {str(key).lower(): str(value or "") for key, value in item.items()} if isinstance(item, dict) else {}
        values = {key: text(value) for key, value in raw_values.items()}
        # HTML 엔터티 처리 과정에서 `&section`이 `§ion`처럼 바뀌지 않도록,
        # 게임 ID가 들어 있는 href는 원문 문자열에서만 찾는다.
        link_text = " ".join(raw_values.values())
        game_id = extract_game_id(link_text)
        game_date = extract_date(link_text) or text(values.get("gamedate") or values.get("game_date"))
        if len(game_date) == 8 and game_date.isdigit():
            game_date = datetime.strptime(game_date, "%Y%m%d").date().isoformat()
        teams = text(values.get("play") or values.get("team") or values.get("match"))
        split = re.split(r"\s*(?:vs|VS|:)\s*", teams)
        away_team = split[0] if len(split) >= 2 else ""
        home_team = split[1] if len(split) >= 2 else ""
        is_all_star = {away_team, home_team} == {"나눔", "드림"}
        rows.append({
            "game_id": game_id,
            "game_date": game_date,
            "season": str(season),
            "away_team": away_team,
            "home_team": home_team,
            "stadium": text(values.get("stadium") or values.get("place")),
            "game_status": "EXCLUDED_ALL_STAR" if is_all_star else "COMPLETE" if game_id else "NO_REVIEW_ID",
            "kbo_review_url": f"{KBO_BASE}{re.search(r'href=[\"\']([^\"\']+)', link_text).group(1)}" if game_id and re.search(r'href=[\"\']([^\"\']+)', link_text) else "",
            "quality_flag": "CHECK" if is_all_star or not (game_id and game_date) else "OK",
            "issue_reason": "All-Star game is outside the regular-season research scope" if is_all_star else "" if game_id and game_date else "KBO schedule row has no usable review link or date",
        })
    return rows


def collect_schedule(collector: Collector, years: list[int], months: list[int]) -> list[dict[str, str]]:
    all_rows: list[dict[str, str]] = []
    for season in years:
        for month in months:
            raw_file = RAW_ROOT / "schedule" / f"schedule_{season}_{month:02d}.json"
            try:
                if raw_file.exists() and not collector.refresh:
                    payload = json.loads(raw_file.read_text(encoding="utf-8"))
                else:
                    payload = collector.post_json(SCHEDULE_URL, {"leId": "1", "srIdList": "0,9", "seasonId": str(season), "gameMonth": f"{month:02d}", "teamId": ""})
                    raw_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                all_rows.extend(schedule_rows(payload, season))
            except Exception as exc:  # retain the other months
                collector.errors.append({"phase": "schedule", "key": f"{season}-{month:02d}", "error": str(exc)})
    deduped = {row["game_id"] or f"{row['season']}|{row['game_date']}|{row['away_team']}|{row['home_team']}": row for row in all_rows}
    result = sorted(deduped.values(), key=lambda row: (row["game_date"], row["game_id"]))
    write_csv(TABLE_ROOT / "game_schedule.csv", SCHEDULE_COLUMNS, result)
    return result


def roster_hidden_fields(collector: Collector) -> dict[str, str]:
    response = collector.session.get(ROSTER_URL, timeout=30)
    response.raise_for_status()
    collector.pause()
    soup = BeautifulSoup(response.content.decode("utf-8-sig", errors="replace"), "html.parser")
    return {str(node.get("name")): str(node.get("value", "")) for node in soup.select("input[type=hidden][name]")}


def parse_roster(html_text: str, game_date: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    rows: list[dict[str, str]] = []
    # 팀명이 th로 들어가므로 th와 td를 모두 읽는다. 열 순서는
    # 구단, 감독, 코치, 투수, 포수, 내야수, 외야수다.
    positions = [(3, "투수"), (4, "포수"), (5, "내야수"), (6, "외야수")]
    for tr in soup.select("tbody tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.select("th, td")]
        if len(cells) < 7 or not re.search(r"\d+명", cells[0]):
            continue
        team = re.sub(r"\s*\d+명.*", "", cells[0]).strip()
        for index, group in positions:
            # 외국인 선수는 당시 등번호가 비어 있어 `이름()`으로 표기될 수
            # 있으므로 숫자가 없는 괄호도 선수 이름으로 인정한다.
            for name in re.findall(r"([^()\s]+)\s*\(\d*\)", cells[index]):
                rows.append({"player_id": "", "player_name": name, "game_date": game_date, "team": team, "position_group": group, "is_in_first_team": "1", "source_url": ROSTER_URL, "quality_flag": "CHECK", "issue_reason": "Official page has name and team but no inspected player ID"})
    return rows


def collect_roster(collector: Collector, schedule: list[dict[str, str]]) -> list[dict[str, str]]:
    game_dates = sorted({row["game_date"] for row in schedule if row["game_id"] and row["game_date"]})
    all_rows: list[dict[str, str]] = []
    for game_date in game_dates:
        raw_file = RAW_ROOT / "roster" / f"roster_{game_date.replace('-', '')}.html"
        try:
            if raw_file.exists() and not collector.refresh:
                page = raw_file.read_text(encoding="utf-8")
            else:
                payload = roster_hidden_fields(collector)
                prefix = "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$"
                payload[f"{prefix}hfSearchDate"] = game_date.replace("-", "")
                payload[f"{prefix}btnSearch"] = ""
                page = collector.post_html(ROSTER_URL, payload)
                raw_file.write_text(page, encoding="utf-8")
            parsed = parse_roster(page, game_date)
            if not parsed:
                collector.errors.append({"phase": "roster", "key": game_date, "error": "No player rows parsed; inspect saved HTML"})
            all_rows.extend(parsed)
        except Exception as exc:
            collector.errors.append({"phase": "roster", "key": game_date, "error": str(exc)})
    deduped = {(row["game_date"], row["team"], row["player_name"], row["position_group"]): row for row in all_rows}
    result = sorted(deduped.values(), key=lambda row: (row["game_date"], row["team"], row["player_name"]))
    write_csv(TABLE_ROOT / "roster_daily.csv", ROSTER_COLUMNS, result)
    return result


def naver_lineup_rows(relay: dict[str, Any], game_id: str, game_date: str, away_team: str, home_team: str) -> list[dict[str, str]]:
    data = relay.get("result", {}).get("textRelayData", {})
    rows: list[dict[str, str]] = []
    # 시즌과 경기마다 Naver 선수 명단의 항목 제공 범위가 다르다. 실제로
    # 2021년 원본에는 PA 항목이 비어 있는 선수가 있으므로, 비어 있는 값을
    # 0으로 바꾸면 "타석이 없었다"는 잘못된 기록이 된다. 확인하지 못한 값은
    # 빈칸으로 유지하고 quality_flag=CHECK로 표시한다.
    def stat(player: dict[str, Any], key: str) -> str:
        value = player.get(key)
        return "" if value in (None, "") else str(value).strip()
    for lineup_key, side in (("homeLineup", "HOME"), ("awayLineup", "AWAY")):
        for player in data.get(lineup_key, {}).get("batter", []):
            player_id, player_name = text(player.get("pcode")), text(player.get("name"))
            if not player_id or not player_name:
                continue
            rows.append({
                "game_id": game_id, "game_date": game_date, "team": text(player.get("teamName")) or (home_team if side == "HOME" else away_team), "home_away": side,
                "player_id": player_id, "player_name": player_name,
                "PA": stat(player, "pa"), "AB": stat(player, "ab"), "H": stat(player, "hit"),
                "HR": stat(player, "hr"), "BB": stat(player, "bb"), "SO": stat(player, "so"),
                "stats_source": "Naver game relay lineup; needs official daily-record check before analysis", "quality_flag": "CHECK", "issue_reason": "KBO boxscore response has no inspected player ID/stat columns",
            })
    return rows


def collect_games(collector: Collector, schedule: list[dict[str, str]], max_games: int) -> list[dict[str, str]]:
    completed = [row for row in schedule if row["game_id"] and row["game_status"] == "COMPLETE"]
    if max_games:
        completed = completed[:max_games]
    all_box: list[dict[str, str]] = []
    for row in completed:
        game_id, game_date, season = row["game_id"], row["game_date"], row["season"]
        raw_dir = RAW_ROOT / "games" / game_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        try:
            payload = {"leId": "1", "srId": "0", "seasonId": season, "gameId": game_id}
            for name, endpoint in (("scoreboard", SCOREBOARD_URL), ("boxscore", BOXSCORE_URL)):
                raw_file = raw_dir / f"kbo_{name}.json"
                if not raw_file.exists() or collector.refresh:
                    data = collector.post_json(endpoint, payload)
                    if data.get("code") != "100":
                        raise RuntimeError(f"KBO {name} business code {data.get('code')!r}")
                    raw_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            naver_game_id = f"{game_id}{season}"
            relay_file = raw_dir / "naver_relay_inning_1.json"
            if relay_file.exists() and not collector.refresh:
                relay = json.loads(relay_file.read_text(encoding="utf-8"))
            else:
                relay = collector.get_json(NAVER_RELAY_URL.format(game_id=naver_game_id), {"inning": 1})
                returned_id = text(relay.get("result", {}).get("textRelayData", {}).get("gameId"))
                if returned_id and returned_id != naver_game_id:
                    raise RuntimeError(f"Naver returned unexpected game ID {returned_id}")
                relay_file.write_text(json.dumps(relay, ensure_ascii=False, indent=2), encoding="utf-8")
            all_box.extend(naver_lineup_rows(relay, game_id, game_date, row["away_team"], row["home_team"]))
        except Exception as exc:
            collector.errors.append({"phase": "games", "key": game_id, "error": str(exc)})
    keys = {(row["game_id"], row["player_id"]): row for row in all_box}
    result = sorted(keys.values(), key=lambda row: (row["game_date"], row["game_id"], row["home_away"], row["player_id"]))
    write_csv(TABLE_ROOT / "player_game_boxscore.csv", BOX_COLUMNS, result)
    return result


def relay_context(relay: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Return relay content and the player-number/name map carried by Naver."""
    text_relay = relay.get("result", {}).get("textRelayData", {})
    player_names: dict[str, str] = {}
    for entry_key in ("homeEntry", "awayEntry"):
        for group in ("pitcher", "batter"):
            for player in text_relay.get(entry_key, {}).get(group, []):
                player_id, player_name = text(player.get("pcode")), text(player.get("name"))
                if player_id and player_name:
                    player_names[player_id] = player_name
    return text_relay, player_names


def relay_pa_rows(relay: dict[str, Any], game_id: str) -> list[dict[str, str]]:
    """Make one row per Naver relay batting event, including an event with no pitch."""
    out: list[dict[str, str]] = []
    text_relay, player_names = relay_context(relay)
    for relay_item in reversed(text_relay.get("textRelays", [])):
        relay_no = text(relay_item.get("no"))
        options = relay_item.get("textOptions", [])
        batter_option = next((option for option in options if option.get("batterRecord")), {})
        batter_record = batter_option.get("batterRecord", {})
        batter, batter_id = text(batter_record.get("name")), text(batter_record.get("pcode"))
        if not relay_no or not batter_id:
            continue
        result_option = next((option for option in reversed(options) if batter and text(option.get("text")).startswith(f"{batter} :")), {})
        result_text = text(result_option.get("text"))
        pa_result = result_text.split(":", 1)[1].strip() if ":" in result_text else ""
        state = next((option.get("currentGameState", {}) for option in reversed(options) if option.get("currentGameState")), {})
        pitcher_id = text(state.get("pitcher"))
        out.append({
            "game_id": game_id, "pa_id": f"{game_id}_relay_{int(relay_no):04d}", "pa_sequence": "",
            "inning": text(relay_item.get("inn")), "half_inning": "HOME" if text(relay_item.get("homeOrAway")) == "1" else "AWAY",
            "batter_id": batter_id, "batter_name": batter, "pitcher_id": pitcher_id, "pitcher_name": player_names.get(pitcher_id, ""),
            "pa_result": pa_result, "score_difference": text(state.get("scoreGap") or state.get("scoreDifference")),
            "outs": text(state.get("outCount") or state.get("out")), "base_state": text(state.get("base") or state.get("baseState")),
            "quality_flag": "OK" if pa_result else "CHECK", "issue_reason": "" if pa_result else "The Naver relay has a batter event but no final result text.",
            "__relay_no": relay_no,
        })
    return out


def pitch_rows(relay: dict[str, Any], game_id: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    text_relay, player_names = relay_context(relay)
    for relay_item in reversed(text_relay.get("textRelays", [])):
        relay_no = text(relay_item.get("no"))
        options = relay_item.get("textOptions", [])
        batter_option = next((option for option in options if option.get("batterRecord")), {})
        batter_record = batter_option.get("batterRecord", {})
        batter, batter_id = text(batter_record.get("name")), text(batter_record.get("pcode"))
        # 삼진·범타(type 13)뿐 아니라 홈런 같은 타격 결과는 다른 type으로
        # 오기도 한다. 타자 이름으로 시작하고 콜론 뒤 결과가 있는 마지막
        # 문장을 해당 타석 결과로 사용한다.
        result_option = next((
            option for option in reversed(options)
            if batter and text(option.get("text")).startswith(f"{batter} :")
        ), {})
        result_text = text(result_option.get("text"))
        pa_result = result_text.split(":", 1)[1].strip() if ":" in result_text else ""
        # 한 투구 묶음이 한 타석인지 확인할 수 있는 조건이다. `no`는
        # Naver 원본의 중계 사건 번호이므로 재실행해도 같은 pa_id를 만든다.
        if not relay_no or not batter_id or not relay_item.get("ptsOptions"):
            continue
        pa_id = f"{game_id}_relay_{int(relay_no):04d}"
        for number, point in enumerate(relay_item.get("ptsOptions", []), start=1):
            pitch_id = text(point.get("pitchId"))
            option = next((x for x in options if text(x.get("ptsPitchId")) == pitch_id), {})
            state = option.get("currentGameState", {})
            pitcher_id = text(state.get("pitcher"))
            out.append({
                "game_id": game_id, "pa_id": pa_id, "pa_sequence": "", "pa_result": pa_result, "pitch_id": pitch_id, "inning": text(relay_item.get("inn")),
                "half_inning": "HOME" if text(relay_item.get("homeOrAway")) == "1" else "AWAY", "batter_id": batter_id, "batter_name": batter,
                "pitcher_id": pitcher_id, "pitcher_name": player_names.get(pitcher_id, ""), "pitch_number_in_pa": str(number),
                "pitch_type": text(option.get("stuff")), "speed": text(option.get("speed")), "plate_x": text(point.get("crossPlateX")), "plate_y": text(point.get("crossPlateY")),
                "quality_flag": "OK" if pa_result else "CHECK",
                "issue_reason": "pa_id is reproducibly derived from the Naver relay event number" if pa_result else "Naver relay has pitches and a batter but no type-13 result text",
                "__relay_no": relay_no,
            })
    return out


def collect_pitches(collector: Collector, schedule: list[dict[str, str]], max_games: int) -> list[dict[str, str]]:
    games = [row for row in schedule if row["game_id"]]
    if max_games:
        games = games[:max_games]
    all_rows: list[dict[str, str]] = []
    for row in games:
        game_id, season = row["game_id"], row["season"]
        raw_file = RAW_ROOT / "pitches" / f"naver_pitch_{game_id}.json"
        try:
            if raw_file.exists() and not collector.refresh:
                innings = json.loads(raw_file.read_text(encoding="utf-8"))
            else:
                innings = []
                # 일반 경기는 9회까지만 요청한다. 연장 여부는 이미 받은
                # KBO 점수판의 최종 점수로 판단한다. 10~12회를 무조건
                # 요청하면 존재하지 않는 이닝에서 긴 시간 제한이 반복된다.
                inning_numbers = range(1, 10)
                scoreboard_file = RAW_ROOT / "games" / game_id / "kbo_scoreboard.json"
                if scoreboard_file.exists():
                    scoreboard = json.loads(scoreboard_file.read_text(encoding="utf-8"))
                    away_score = text(scoreboard.get("T_SCORE_CN"))
                    home_score = text(scoreboard.get("B_SCORE_CN"))
                    if away_score and home_score and away_score == home_score:
                        inning_numbers = range(1, 13)
                for inning in inning_numbers:
                    relay = collector.get_json(NAVER_RELAY_URL.format(game_id=f"{game_id}{season}"), {"inning": inning})
                    if relay.get("result", {}).get("textRelayData", {}).get("textRelays"):
                        innings.append(relay)
                raw_file.write_text(json.dumps(innings, ensure_ascii=False, indent=2), encoding="utf-8")
            for relay in innings:
                all_rows.extend(pitch_rows(relay, game_id))
        except Exception as exc:
            collector.errors.append({"phase": "pitches", "key": game_id, "error": str(exc)})
    keys = {row["pitch_id"]: row for row in all_rows if row["pitch_id"]}
    result = sorted(keys.values(), key=lambda row: (row["game_id"], int(row["__relay_no"]), int(row["pitch_number_in_pa"])))
    seen_pa: dict[tuple[str, str], int] = {}
    current_game, sequence = "", 0
    for row in result:
        key = (row["game_id"], row["pa_id"])
        if key not in seen_pa:
            if row["game_id"] != current_game:
                current_game, sequence = row["game_id"], 0
            sequence += 1
            seen_pa[key] = sequence
        row["pa_sequence"] = str(seen_pa[key])
    write_csv(TABLE_ROOT / "game_pa_pitch_link.csv", PITCH_COLUMNS, result)
    return result


def completed_innings(scoreboard_file: Path) -> int:
    """Use the rightmost real official inning score, not the fixed table width."""
    scoreboard = json.loads(scoreboard_file.read_text(encoding="utf-8"))
    table = load_json(scoreboard.get("table2", {}))
    played = [
        index
        for source_row in table.get("rows", [])
        for index, cell in enumerate(source_row.get("row", []), start=1)
        if text(cell.get("Text")) not in {"", "-"}
    ]
    if not played:
        raise ValueError("Official scoreboard has no readable inning score.")
    return max(played)


def read_saved_relay(path: Path) -> dict[str, Any] | None:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return saved if isinstance(saved, dict) else None


def collect_full_pitches(collector: Collector, schedule: list[dict[str, str]], max_games: int, seasons: set[str]) -> list[dict[str, str]]:
    """Collect every inning and persist each source response independently.

    An existing, readable inning file is reused.  This makes an interrupted run
    restart from the missing inning rather than request the whole game again.
    """
    games = [row for row in schedule if row["game_id"] and row["game_status"] == "COMPLETE" and row["season"] in seasons]
    if max_games:
        games = games[:max_games]
    all_rows: list[dict[str, str]] = []
    all_pa_rows: list[dict[str, str]] = []
    inning_status_rows: list[dict[str, str]] = []
    for game_number, row in enumerate(games, start=1):
        game_id, season = row["game_id"], row["season"]
        try:
            last_inning = completed_innings(RAW_ROOT / "games" / game_id / "kbo_scoreboard.json")
            game_dir = RAW_ROOT / "pitches" / game_id
            game_dir.mkdir(parents=True, exist_ok=True)
            for inning in range(1, last_inning + 1):
                raw_file = game_dir / f"inning_{inning:02d}.json"
                relay = None if collector.refresh else read_saved_relay(raw_file)
                if relay is None and inning == 1 and not collector.refresh:
                    relay = read_saved_relay(RAW_ROOT / "games" / game_id / "naver_relay_inning_1.json")
                if relay is None:
                    relay = collector.get_json(NAVER_RELAY_URL.format(game_id=f"{game_id}{season}"), {"inning": inning})
                    raw_file.write_text(json.dumps(relay, ensure_ascii=False, indent=2), encoding="utf-8")
                relay_count = len(relay.get("result", {}).get("textRelayData", {}).get("textRelays", []))
                inning_status_rows.append({
                    "game_id": game_id, "season": season, "game_date": row["game_date"], "inning": str(inning),
                    "expected_last_inning": str(last_inning), "raw_file": str(raw_file.relative_to(DATA_ROOT)),
                    "relay_event_count": str(relay_count), "collection_status": "COMPLETE",
                    "issue_reason": "" if relay_count else "Saved response has no relay event; it remains an explicit empty inning.",
                })
                all_rows.extend(pitch_rows(relay, game_id))
                all_pa_rows.extend(relay_pa_rows(relay, game_id))
        except Exception as exc:
            collector.errors.append({"phase": "pitches", "key": game_id, "error": str(exc)})
        if game_number % 10 == 0 or game_number == len(games):
            write_csv(LOG_ROOT / "inning_collection_progress.csv", INNING_COLLECTION_COLUMNS, inning_status_rows)
            print(f"pitch collection: {game_number}/{len(games)} games, {len(inning_status_rows)} inning files", flush=True)
    keys = {(row["game_id"], row["pitch_id"]): row for row in all_rows if row["pitch_id"]}
    result = sorted(keys.values(), key=lambda row: (row["game_id"], int(row["__relay_no"]), int(row["pitch_number_in_pa"])))
    seen_pa: dict[tuple[str, str], int] = {}
    current_game, sequence = "", 0
    for row in result:
        key = (row["game_id"], row["pa_id"])
        if key not in seen_pa:
            if row["game_id"] != current_game:
                current_game, sequence = row["game_id"], 0
            sequence += 1
            seen_pa[key] = sequence
        row["pa_sequence"] = str(seen_pa[key])
    write_csv(TABLE_ROOT / "game_pa_pitch_link.csv", PITCH_COLUMNS, result)
    pa_keys = {(row["game_id"], row["pa_id"]): row for row in all_pa_rows}
    pa_result = sorted(pa_keys.values(), key=lambda item: (item["game_id"], int(item["__relay_no"])))
    current_game, sequence = "", 0
    for item in pa_result:
        if item["game_id"] != current_game:
            current_game, sequence = item["game_id"], 0
        sequence += 1
        item["pa_sequence"] = str(sequence)
    write_csv(TABLE_ROOT / "game_pa_event.csv", PA_EVENT_COLUMNS, pa_result)
    write_csv(LOG_ROOT / "inning_collection_progress.csv", INNING_COLLECTION_COLUMNS, inning_status_rows)
    return result


def write_manifest(schedule: list[dict[str, str]], roster: list[dict[str, str]], box: list[dict[str, str]], pitch: list[dict[str, str]], collector: Collector) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    build_derived_tables(schedule, box, pitch)
    files = [
        TABLE_ROOT / "game_schedule.csv", TABLE_ROOT / "roster_daily.csv", TABLE_ROOT / "player_game_boxscore.csv",
        TABLE_ROOT / "player_daily_official.csv", TABLE_ROOT / "missing_game_list.csv", TABLE_ROOT / "season_game_count_check.csv",
        TABLE_ROOT / "game_id_crosswalk.csv", TABLE_ROOT / "game_pa_pitch_link.csv", TABLE_ROOT / "game_pa_event.csv",
        TABLE_ROOT / "pa_sequence_check.csv", TABLE_ROOT / "pa_boxscore_count_check.csv", LOG_ROOT / "inning_collection_progress.csv",
    ]
    rows = []
    for file in files:
        if not file.exists():
            continue
        rows.append({"file_name": file.name, "row_count": max(0, sum(1 for _ in file.open(encoding="utf-8-sig")) - 1), "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "created_or_checked_at": now})
    write_csv(TABLE_ROOT / "source_manifest.csv", ["file_name", "row_count", "sha256", "created_or_checked_at"], rows)
    write_csv(LOG_ROOT / "collection_errors.csv", ["phase", "key", "error"], collector.errors)
    summary = [
        f"수집 시각(UTC): {now}", f"일정 행: {len(schedule)}", f"1군 등록 행: {len(roster)}", f"선수별 경기 기록 행: {len(box)}", f"투구 연결 행: {len(pitch)}", f"오류 수: {len(collector.errors)}",
        "주의: player_id가 없는 1군 등록표와 PA ID가 없는 투구표는 빈 값을 유지했다. 오류 목록과 원본 응답을 먼저 확인한다.",
    ]
    (LOG_ROOT / "latest_run_summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")


def build_derived_tables(schedule: list[dict[str, str]], box: list[dict[str, str]], pitch: list[dict[str, str]]) -> None:
    """수집표에서 40~110 단계가 요구하는 검사표를 만든다.

    아직 공식 선수 일별 페이지와 연결하지 않은 경기 기록은 파일명과 달리
    `record_source`와 `quality_flag`에 출처·상태를 그대로 표시한다.
    """
    daily = [{
        "player_id": row["player_id"], "player_name": row["player_name"], "game_date": row["game_date"], "game_id": row["game_id"],
        "team": row["team"], "PA": row["PA"], "AB": row["AB"], "H": row["H"], "HR": row["HR"], "BB": row["BB"], "SO": row["SO"],
        "record_source": row["stats_source"], "quality_flag": row["quality_flag"], "issue_reason": row["issue_reason"],
    } for row in box]
    write_csv(TABLE_ROOT / "player_daily_official.csv", DAILY_COLUMNS, daily)
    missing = [{
        "game_date": row["game_date"], "away_team": row["away_team"], "home_team": row["home_team"], "stadium": row["stadium"],
        "collection_status": row["game_status"], "issue_reason": row["issue_reason"] or "No KBO review game ID; verify cancellation, postponement, or schedule structure",
    } for row in schedule if not row["game_id"]]
    write_csv(TABLE_ROOT / "missing_game_list.csv", MISSING_GAME_COLUMNS, missing)
    saved_counts = Counter()
    for row in box:
        saved_counts[(row["game_id"], row["team"])] += 1
    schedule_counts = Counter()
    for row in schedule:
        if row["game_id"] and row["game_status"] == "COMPLETE":
            schedule_counts[(row["season"], row["away_team"])] += 1
            schedule_counts[(row["season"], row["home_team"])] += 1
    saved_game_counts = Counter()
    for game_id, team in saved_counts:
        season = next((row["season"] for row in schedule if row["game_id"] == game_id), "")
        saved_game_counts[(season, team)] += 1
    checks = []
    for season_team, count in sorted(schedule_counts.items()):
        saved = saved_game_counts[season_team]
        checks.append({
            "season": season_team[0], "team": season_team[1], "schedule_game_count": count, "saved_player_game_count": saved,
            "difference": count - saved, "check_result": "OK" if count == saved else "INCOMPLETE",
            "note": "Counts cover only the months selected when running this program, not an asserted full season total.",
        })
    write_csv(TABLE_ROOT / "season_game_count_check.csv", SEASON_CHECK_COLUMNS, checks)
    crosswalk = [{
        "kbo_game_id": row["game_id"], "naver_game_id": f"{row['game_id']}{row['season']}", "game_date": row["game_date"],
        "matching_rule": "KBO game ID + season; Naver response game ID is checked when collected", "verification_status": "VERIFIED" if (RAW_ROOT / "games" / row["game_id"] / "naver_relay_inning_1.json").exists() else "NOT_COLLECTED",
        "issue_reason": "" if (RAW_ROOT / "games" / row["game_id"] / "naver_relay_inning_1.json").exists() else "Naver lineup has not been collected for this game",
    } for row in schedule if row["game_id"] and row["game_status"] == "COMPLETE"]
    write_csv(TABLE_ROOT / "game_id_crosswalk.csv", CROSSWALK_COLUMNS, crosswalk)
    pa_by_id: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in pitch:
        pa_by_id.setdefault((row["game_id"], row["pa_id"]), []).append(row)
    pa_checks = []
    for _, pitch_rows_for_pa in sorted(pa_by_id.items(), key=lambda item: (item[1][0]["game_id"], int(item[1][0]["pa_sequence"]))):
        first = pitch_rows_for_pa[0]
        pa_checks.append({
            "game_id": first["game_id"], "batter_id": first["batter_id"], "batter_name": first["batter_name"], "inning": first["inning"], "half_inning": first["half_inning"],
            "pa_sequence": first["pa_sequence"], "pa_id": first["pa_id"], "pa_result": first["pa_result"], "pitch_count": len(pitch_rows_for_pa),
            "sequence_check": "OK", "issue_reason": first["issue_reason"],
        })
    write_csv(TABLE_ROOT / "pa_sequence_check.csv", PA_SEQUENCE_COLUMNS, pa_checks)
    reconstructed = Counter((row["game_id"], row["batter_id"]) for row in pa_checks)
    pa_boxscore_checks = []
    for row in box:
        pa_value = row["PA"]
        actual = reconstructed[(row["game_id"], row["player_id"])]
        expected = int(pa_value) if pa_value else None
        difference = actual - expected if expected is not None else None
        pa_boxscore_checks.append({
            "game_id": row["game_id"], "player_id": row["player_id"], "player_name": row["player_name"],
            "boxscore_PA": pa_value, "reconstructed_PA": actual, "difference": "" if difference is None else difference,
            "quality_flag": "UNKNOWN" if expected is None else ("OK" if difference == 0 else "CHECK"),
            "issue_reason": "Box score PA is blank; do not convert it to zero." if expected is None else ("" if difference == 0 else "A plate appearance may have no tracked pitch or relay event; inspect raw relay before correction."),
        })
    write_csv(TABLE_ROOT / "pa_boxscore_count_check.csv", PA_BOXSCORE_COLUMNS, pa_boxscore_checks)


def main() -> None:
    args = parse_args()
    configure_data_root(args.data_root)
    ensure_dirs()
    collector = Collector(args.rate_seconds, args.refresh)
    schedule = read_csv(TABLE_ROOT / "game_schedule.csv")
    roster = read_csv(TABLE_ROOT / "roster_daily.csv")
    box = read_csv(TABLE_ROOT / "player_game_boxscore.csv")
    pitch = read_csv(TABLE_ROOT / "game_pa_pitch_link.csv")
    if "schedule" in args.phases:
        schedule = collect_schedule(collector, args.years, args.months)
    if not schedule:
        raise SystemExit("game_schedule.csv가 없습니다. 먼저 --phases schedule 을 실행하세요.")
    if "roster" in args.phases:
        roster = collect_roster(collector, schedule)
    if "games" in args.phases:
        box = collect_games(collector, schedule, args.max_games)
    if "pitches" in args.phases:
        pitch = collect_full_pitches(collector, schedule, args.max_games, {str(year) for year in args.years})
    write_manifest(schedule, roster, box, pitch, collector)
    print((LOG_ROOT / "latest_run_summary.txt").read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
