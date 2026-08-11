# 연구순서 40~110 공식 기록 수집

`crawl_research_40_110.py`는 이 저장소에 있던 KBO 경기 조회와 Naver 중계 조회 방식을 재사용해, 연구순서 40~110에서 쓸 원본과 표를 만든다.

## 먼저 설치할 것

기존 크롤러와 마찬가지로 Python 3과 `requests`, `beautifulsoup4`가 필요하다.

```powershell
pip install requests beautifulsoup4
```

## 실행 순서

가장 먼저 일정과 1군 등록 선수 표를 모은다. 다음 명령은 2026년 5월만 시험하는 안전한 예시다.

```powershell
python Crawling/final/crawl_research_40_110.py --years 2026 --months 5 --phases schedule roster
```

경기 기록은 요청 수가 많으므로 먼저 한 경기만 시험한다.

```powershell
python Crawling/final/crawl_research_40_110.py --years 2026 --months 5 --phases games --max-games 1
```

투구별 기록은 경기마다 최대 12번을 추가로 조회하므로 가장 마지막에 실행한다.

```powershell
python Crawling/final/crawl_research_40_110.py --years 2026 --months 5 --phases pitches --max-games 1
```

전체 시즌을 받을 때도 서버에 부담을 주지 않도록 기본값인 0.6초보다 더 짧게 설정하지 않는다. 중간에 멈춰도 이미 받은 원본은 다시 받지 않으므로 같은 명령을 다시 실행하면 이어서 진행한다. 정말 새로 받으려면 `--refresh`를 붙인다.

## 만들어지는 파일

모든 결과는 Git에 올리지 않는 `data/research_40_110/`에 저장된다. 원본 응답은 `raw/`, 사람이 확인할 표는 `tables/`, 실패 기록은 `logs/`에 있다.

| 파일 | 한 줄의 뜻 | 확인할 점 |
|---|---|---|
| `tables/game_schedule.csv` | 경기 하나 | `game_id`가 비어 있지 않은 완료 경기인지 |
| `tables/roster_daily.csv` | 날짜별 1군 등록 선수 한 명 | 이름만 확인된 경우 `player_id`는 비워 둠 |
| `tables/player_game_boxscore.csv` | 선수 한 명의 경기 기록 | Naver 중계 기록이라 `quality_flag=CHECK` 상태로 남김 |
| `tables/game_pa_pitch_link.csv` | 공 하나 | 원본에 명시적 타석 번호가 없으면 `pa_id`를 비워 둠 |
| `tables/source_manifest.csv` | 만들어진 표 하나 | 행 수와 파일 지문(SHA-256)으로 버전 확인 |
| `logs/collection_errors.csv` | 실패한 요청 하나 | 실패 원인을 확인하고 다시 실행 |

## 자료 출처와 한계

- 경기 일정·경기 ID·박스스코어 원본: KBO 공식 웹사이트
- 1군 등록 선수: KBO 공식 등록선수 페이지(날짜를 넣어 조회)
- 경기별 선수 기록과 투구 중계: Naver Sports 경기 중계 응답

Naver 경기 ID는 KBO 경기 ID 뒤에 시즌을 붙인 형태를 먼저 시도하지만, 응답의 경기 ID가 다르면 오류로 기록하고 사용하지 않는다. KBO 박스스코어 응답에는 조사 당시 선수 번호와 타격 세부 기록이 바로 들어 있지 않아, 그 값을 임의로 채우지 않는다.

## 제출 전 확인

1. `logs/latest_run_summary.txt`에서 행 수와 오류 수를 확인한다.
2. `collection_errors.csv`가 비어 있지 않으면 해당 원본을 다시 확인한다.
3. 임의로 고른 경기 하나를 KBO 공식 경기 화면과 비교한다.
4. `game_id + player_id` 중복 여부는 `player_game_boxscore.csv`에서 별도로 검사한다.
