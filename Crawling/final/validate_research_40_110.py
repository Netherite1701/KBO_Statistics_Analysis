"""연구순서 40~110 CSV의 형식과 기본 연결 규칙을 검사한다.

수집기를 다시 호출하지 않는다. 이미 만들어진 CSV만 읽고
`data/research_40_110/logs/validation_40_110.csv`를 만든다.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from crawl_research_40_110 import (
    BOX_COLUMNS, CROSSWALK_COLUMNS, DAILY_COLUMNS, MISSING_GAME_COLUMNS,
    PA_SEQUENCE_COLUMNS, PA_BOXSCORE_COLUMNS, PITCH_COLUMNS, ROSTER_COLUMNS, SCHEDULE_COLUMNS,
    SEASON_CHECK_COLUMNS, TABLE_ROOT, LOG_ROOT,
)


EXPECTED = {
    "game_schedule.csv": SCHEDULE_COLUMNS,
    "roster_daily.csv": ROSTER_COLUMNS,
    "player_game_boxscore.csv": BOX_COLUMNS,
    "player_daily_official.csv": DAILY_COLUMNS,
    "missing_game_list.csv": MISSING_GAME_COLUMNS,
    "season_game_count_check.csv": SEASON_CHECK_COLUMNS,
    "game_id_crosswalk.csv": CROSSWALK_COLUMNS,
    "game_pa_pitch_link.csv": PITCH_COLUMNS,
    "pa_sequence_check.csv": PA_SEQUENCE_COLUMNS,
    "pa_boxscore_count_check.csv": PA_BOXSCORE_COLUMNS,
}


def read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames or [], list(reader)


def add(results: list[dict[str, object]], name: str, result: str, count: int, detail: str) -> None:
    results.append({"check_name": name, "result": result, "count": count, "detail": detail})


def main() -> None:
    results: list[dict[str, object]] = []
    loaded: dict[str, list[dict[str, str]]] = {}
    for filename, expected_columns in EXPECTED.items():
        path = TABLE_ROOT / filename
        if not path.exists():
            add(results, f"{filename}: 존재", "MISSING", 1, "수집기를 실행해 파일을 만든다.")
            continue
        columns, rows = read(path)
        loaded[filename] = rows
        add(results, f"{filename}: 열 순서", "OK" if columns == expected_columns else "FAIL", len(columns), "CSV 첫 행은 문서에 적은 열 순서와 같아야 한다.")
        add(results, f"{filename}: 행 수", "INFO", len(rows), "빈 파일도 헤더는 유지한다.")

    schedule = loaded.get("game_schedule.csv", [])
    schedule_ids = [row["game_id"] for row in schedule if row["game_id"]]
    add(results, "일정 game_id 중복", "OK" if len(schedule_ids) == len(set(schedule_ids)) else "FAIL", len(schedule_ids) - len(set(schedule_ids)), "완료 경기의 KBO game_id는 한 번만 있어야 한다.")

    box = loaded.get("player_game_boxscore.csv", [])
    box_keys = [(row["game_id"], row["player_id"]) for row in box if row["game_id"] and row["player_id"]]
    add(results, "선수×경기 중복", "OK" if len(box_keys) == len(set(box_keys)) else "FAIL", len(box_keys) - len(set(box_keys)), "player_id + game_id 기준 중복 행 수다.")

    pitch = loaded.get("game_pa_pitch_link.csv", [])
    pitch_ids = [row["pitch_id"] for row in pitch if row["pitch_id"]]
    add(results, "투구 ID 중복", "OK" if len(pitch_ids) == len(set(pitch_ids)) else "FAIL", len(pitch_ids) - len(set(pitch_ids)), "pitch_id가 비어 있지 않은 행만 검사한다.")
    pa_missing = sum(not row["pa_id"] for row in pitch)
    add(results, "투구의 타석 연결 누락", "OK" if pa_missing == 0 else "FAIL", pa_missing, "Naver relay 사건 번호를 재현 가능한 pa_id로 바꾼 뒤 빈 값이 없어야 한다.")

    pa_boxscore = loaded.get("pa_boxscore_count_check.csv", [])
    pa_difference = sum(row.get("difference", "0") != "0" for row in pa_boxscore)
    add(results, "박스스코어 PA와 재구성 타석 차이", "OK" if pa_difference == 0 else "CHECK", pa_difference, "차이는 무투구 타석·중계 누락 여부를 원본에서 확인해야 한다.")

    flags = Counter(row.get("quality_flag", "") for rows in loaded.values() for row in rows if "quality_flag" in row)
    for flag, count in sorted(flags.items()):
        add(results, f"품질 표시: {flag or '(빈 값)'}", "INFO", count, "값의 의미는 DATA_FORMAT_40_110.md를 따른다.")

    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    output = LOG_ROOT / "validation_40_110.csv"
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["check_name", "result", "count", "detail"])
        writer.writeheader()
        writer.writerows(results)
    print(output)
    for row in results:
        print(f"{row['result']:5} {row['check_name']}: {row['count']}")


if __name__ == "__main__":
    main()
