# 연구순서 40~110: 생성 파일과 CSV 형식

이 문서는 크롤러가 만드는 **모든 파일의 이름, 저장 위치, 형식, CSV 열 순서**를 기록한다. CSV를 읽을 때는 `utf-8-sig`(UTF-8 + BOM) 인코딩을 사용한다. 첫 줄은 열 이름이고, 행 번호 열은 없다. 값이 없거나 원본에서 확인할 수 없는 값은 빈 칸으로 둔다. 임의로 0이나 새 ID를 넣지 않는다.

## 폴더 구조

| 위치 | 형식 | 내용 |
|---|---|---|
| `data/research_40_110/raw/schedule/schedule_{시즌}_{월}.json` | JSON | KBO 공식 월별 일정 원본 응답 |
| `data/research_40_110/raw/roster/roster_{날짜}.html` | HTML | KBO 공식 날짜별 전체 등록 현황 원본 |
| `data/research_40_110/raw/games/{KBO경기번호}/kbo_scoreboard.json` | JSON | KBO 공식 경기 점수판 원본 |
| `data/research_40_110/raw/games/{KBO경기번호}/kbo_boxscore.json` | JSON | KBO 공식 박스스코어 원본 |
| `data/research_40_110/raw/games/{KBO경기번호}/naver_relay_inning_1.json` | JSON | Naver 경기 중계의 선수 명단·경기 기록 원본 |
| `data/research_40_110/raw/pitches/naver_pitch_{KBO경기번호}.json` | JSON | Naver 이닝별 투구 중계 원본 목록 |
| `data/research_40_110/tables/` | CSV | 아래의 분석·검사용 표 |
| `data/research_40_110/logs/` | CSV, TXT, LOG | 수집 오류, 검사 결과, 실행 요약 |

`{날짜}`는 `YYYYMMDD`, `{시즌}`은 네 자리 연도, `{월}`은 두 자리 월이다. `KBO경기번호`는 KBO 경기 화면의 `gameId`다.

## 공통 품질 표시

| 값 | 뜻 |
|---|---|
| `OK` | 이 파일 안에서 필요한 키와 값이 확인됨 |
| `CHECK` | 원본은 받았지만 다른 원본과의 연결 또는 사람이 확인할 부분이 남음 |
| `MISSING` | 원본에 필요한 값이 없어 빈 칸으로 남김 |
| `INCOMPLETE` | 선택한 기간의 수집이 아직 일정 전체와 맞지 않음 |

## `tables/game_schedule.csv`

한 행은 일정의 경기 하나다. `game_id`가 비어 있으면 KBO 화면에 리뷰 경기 번호가 없었던 일정이며, 취소·연기·예정 또는 화면 구조 변경 여부를 확인한다.

| 순서 | 변수명 | 뜻 |
|---:|---|---|
| 1 | `game_id` | KBO 경기 번호 |
| 2 | `game_date` | 경기 날짜 (`YYYY-MM-DD`) |
| 3 | `season` | 시즌 연도 |
| 4 | `away_team` | 원정 팀 |
| 5 | `home_team` | 홈 팀 |
| 6 | `stadium` | 경기장 |
| 7 | `game_status` | `COMPLETE` 또는 `NO_REVIEW_ID` |
| 8 | `kbo_review_url` | KBO 공식 경기 리뷰 주소 |
| 9 | `quality_flag` | 자료 확인 상태 |
| 10 | `issue_reason` | 확인이 필요한 이유 |

## `tables/roster_daily.csv`

한 행은 특정 날짜의 1군 등록 선수 한 명이다. KBO 등록 현황 화면에 선수 번호가 직접 없으므로 `player_id`는 빈 칸이다. 빈 칸은 미등록이라는 뜻이 아니다.

| 순서 | 변수명 | 뜻 |
|---:|---|---|
| 1 | `player_id` | 선수 번호. 현재 원본에 없으면 빈 칸 |
| 2 | `player_name` | 선수 이름 |
| 3 | `game_date` | 등록 현황을 조회한 날짜 |
| 4 | `team` | 소속 팀 |
| 5 | `position_group` | 투수·포수·내야수·외야수 |
| 6 | `is_in_first_team` | 1이면 1군 등록 표에 있음 |
| 7 | `source_url` | KBO 등록 현황 주소 |
| 8 | `quality_flag` | 자료 확인 상태 |
| 9 | `issue_reason` | 선수 번호가 없는 이유 등 |

## `tables/player_game_boxscore.csv`

한 행은 선수 한 명의 경기 한 번이다. 중복 검사는 `game_id + player_id`로 한다. 현재 타격 기록은 Naver 경기 중계 선수 명단에서 읽으므로, KBO 선수 일별 기록과 대조 전에는 `CHECK` 상태다.

| 순서 | 변수명 | 뜻 |
|---:|---|---|
| 1 | `game_id` | KBO 경기 번호 |
| 2 | `game_date` | 경기 날짜 |
| 3 | `team` | 해당 선수의 팀 |
| 4 | `home_away` | `HOME` 또는 `AWAY` |
| 5 | `player_id` | Naver 선수 번호 |
| 6 | `player_name` | 선수 이름 |
| 7 | `PA` | 타석 수 |
| 8 | `AB` | 타수 |
| 9 | `H` | 안타 수 |
| 10 | `HR` | 홈런 수 |
| 11 | `BB` | 볼넷 수 |
| 12 | `SO` | 삼진 수 |
| 13 | `stats_source` | 기록을 읽은 원본과 확인 상태 |
| 14 | `quality_flag` | 자료 확인 상태 |
| 15 | `issue_reason` | 추가 확인이 필요한 이유 |

## `tables/player_daily_official.csv`

한 행은 선수 한 명의 하루 경기 기록이다. 파일명은 기존 연구 계획을 따르지만, `record_source`를 먼저 확인해야 한다. KBO 선수 일별 화면과 아직 대조하지 않은 기록은 공식 기록이라고 단정하지 않는다.

| 순서 | 변수명 | 뜻 |
|---:|---|---|
| 1 | `player_id` | 선수 번호 |
| 2 | `player_name` | 선수 이름 |
| 3 | `game_date` | 경기 날짜 |
| 4 | `game_id` | KBO 경기 번호 |
| 5 | `team` | 선수 팀 |
| 6 | `PA` | 타석 수 |
| 7 | `AB` | 타수 |
| 8 | `H` | 안타 수 |
| 9 | `HR` | 홈런 수 |
| 10 | `BB` | 볼넷 수 |
| 11 | `SO` | 삼진 수 |
| 12 | `record_source` | 실제 기록 출처 |
| 13 | `quality_flag` | 자료 확인 상태 |
| 14 | `issue_reason` | 추가 확인이 필요한 이유 |

## 경기 수·누락·번호 연결 표

| 파일 | 한 행의 뜻 | CSV 열 순서 |
|---|---|---|
| `missing_game_list.csv` | 리뷰 번호가 없는 일정 한 건 | `game_date`, `away_team`, `home_team`, `stadium`, `collection_status`, `issue_reason` |
| `season_game_count_check.csv` | 선택 기간의 팀별 경기 수 비교 한 건 | `season`, `team`, `schedule_game_count`, `saved_player_game_count`, `difference`, `check_result`, `note` |
| `game_id_crosswalk.csv` | KBO·Naver 경기 번호 연결 한 건 | `kbo_game_id`, `naver_game_id`, `game_date`, `matching_rule`, `verification_status`, `issue_reason` |

`season_game_count_check.csv`의 경기 수는 실행할 때 선택한 달만 대상으로 한다. 이 파일만 보고 시즌 전체 경기 수라고 해석하면 안 된다.

## 투구·타석 연결 표

| 파일 | 한 행의 뜻 | CSV 열 순서 |
|---|---|---|
| `game_pa_pitch_link.csv` | 투구 하나 | `game_id`, `pa_id`, `pa_sequence`, `pa_result`, `pitch_id`, `inning`, `half_inning`, `batter_id`, `batter_name`, `pitcher_id`, `pitcher_name`, `pitch_number_in_pa`, `pitch_type`, `speed`, `plate_x`, `plate_y`, `quality_flag`, `issue_reason` |
| `pa_sequence_check.csv` | 투구 원본에서 확인한 타석 연결 한 건 | `game_id`, `batter_id`, `batter_name`, `inning`, `half_inning`, `pa_sequence`, `pa_id`, `pa_result`, `pitch_count`, `sequence_check`, `issue_reason` |
| `pa_boxscore_count_check.csv` | 선수 한 명·경기 한 번의 공식 PA와 재구성 타석 수 비교 | `game_id`, `player_id`, `player_name`, `boxscore_PA`, `reconstructed_PA`, `difference`, `quality_flag`, `issue_reason` |

Naver 중계의 `textRelays.no`는 경기 안에서 증가하는 중계 사건 번호다. 타자 정보·투구·타석 결과가 함께 있는 사건만 골라 `pa_id = game_id + relay_no`로 만들고, 그 순서대로 `pa_sequence`을 1부터 센다. 이것은 KBO가 따로 제공한 타석 번호가 아니라 원본 중계 사건 번호로 재현 가능한 연결값이다. 타자·투구·결과가 같이 없는 사건은 타석으로 만들지 않는다.

## 출처·오류·검사 파일

| 파일 | 한 행의 뜻 | CSV 열 순서 |
|---|---|---|
| `source_manifest.csv` | 생성한 표 파일 하나 | `file_name`, `row_count`, `sha256`, `created_or_checked_at` |
| `logs/collection_errors.csv` | 수집 중 실패한 요청 하나 | `phase`, `key`, `error` |
| `logs/validation_40_110.csv` | 형식 또는 중복 검사 하나 | `check_name`, `result`, `count`, `detail` |
| `logs/sample_record_validation.csv` | 선수 한 명·경기 한 번의 수치 비교 한 건 | `game_id`, `game_date`, `player_id`, `player_name`, `field`, `source_value`, `kbo_daily_value`, `comparison_status`, `source_url` |

`logs/latest_run_summary.txt`는 사람이 빠르게 보는 실행 요약이고, `games_*.stdout.log`와 `games_*.stderr.log`는 백그라운드 수집의 출력 기록이다.

`raw/validation/kbo_hitter_daily_{선수번호}.html`은 위의 표를 만들 때 직접 내려받은 KBO 선수 일별 기록 원본이다.

## 검사 명령

```powershell
python Crawling/final/validate_research_40_110.py
```

이 명령은 외부 사이트에 접속하지 않는다. 각 CSV의 열 순서, 경기 번호 중복, `player_id + game_id` 중복, 투구 번호 중복, 품질 표시 개수를 `logs/validation_40_110.csv`에 기록한다.
