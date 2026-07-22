# KBO Statistics Crawler

타자의 컨디션 사이클을 경기별 벡터와 변화량으로 모델링할 수 있도록,
KBO 경기·타석·투구·선수 일별 기록·1군 등록 현황을 재현 가능한 형태로
수집하는 프로젝트입니다. 신경망 없이 상태공간 모형, Kalman filter,
HMM, 변화점 탐지, 동적 회귀에 바로 넣을 수 있는 일자별 데이터 기반을
만드는 것이 목적입니다.

프로젝트 설계, 현재 구현, 데이터 사전과 모델링 로드맵은
[project_analysis/README.md](project_analysis/README.md)에서 시작합니다.

## 수집 범위와 출처

- Naver Sports
  - 날짜별 실제 경기 ID 발견
  - 이닝별 문자 중계, 모든 이벤트, PTS 투구 추적값
  - type 13과 type 23 타석 결과
  - 원본 `relay.no`, `seqno`, `pitchNum`, 선수 코드와 경기 상태
- KBO 공식 사이트
  - 월별 일정과 게임센터 스코어보드·박스스코어
  - 타자/투수 일별 공식 기록과 월 합계
  - 날짜별 1군 등록·말소 현황
- STATIZ
  - 기본 비활성인 검산 전용 소스
  - WAR, wRC+, FIP, WHIP, BABIP 등 집계 지표

기본 백필 범위는 2021년부터 현재까지이며 시범경기, 정규시즌,
포스트시즌을 `series_type`으로 구분합니다. 경기 ID는 문자열을 조합해
추측하지 않고 일정 API가 반환한 ID만 사용합니다.

## 설치

```powershell
python -m pip install -e ".[dev]"
python -m kbo_crawler init
```

환경변수로 저장 위치를 바꿀 수 있습니다.

- `KBO_DATA_DIR` (기본 `data`)
- `KBO_DATABASE_PATH` (기본 `data/kbo.sqlite`)
- `KBO_RAW_DIR` (기본 `data/raw`)
- `KBO_SQLITE_BUSY_TIMEOUT_MS` (기본 `5000`)

## 실행

전날까지 최근 3일의 종료 경기를 재확인하는 기본 배치:

```powershell
python -m kbo_crawler sync
```

2021년부터 현재까지 백필:

```powershell
python -m kbo_crawler backfill --start-year 2021
```

명시한 기간의 모든 날짜를 순회하는 재개 가능한 래퍼:

```powershell
python -m kbo_crawler period `
  --from-date 2025-03-01 `
  --to-date 2025-11-30
```

이 명령은 기간의 휴식일도 일정 API로 확인하고, 발견된 종료 경기의 모든
타석·투구·이벤트·박스스코어를 수집합니다. 다시 실행하면
`validated` 경기는 건너뛰고 미완료·실패·격리 경기만 다시 시도합니다.
검증된 경기까지 다시 받으려면 `--refresh`를 사용합니다.

```powershell
# 매일의 1군 명단도 함께 수집
python -m kbo_crawler period `
  --from-date 2025-03-01 --to-date 2025-11-30 `
  --with-rosters

# 기간에 실제 등장한 모든 타자·투수의 시즌 일별 페이지까지 수집
python -m kbo_crawler period `
  --from-date 2025-03-01 --to-date 2025-11-30 `
  --with-player-daily
```

`--with-rosters`는 경기 수와 관계없이 기간의 모든 날짜에 KBO 요청을
추가합니다. `--with-player-daily`는 경기 수집 후 관측된 선수×시즌×역할별로
한 번씩 추가 요청하므로 전체 시즌에서는 실행 시간이 크게 늘어납니다.

한 경기 재수집, 품질 검사, CSV 내보내기:

```powershell
python -m kbo_crawler fetch-game 20260506HHHT02026 --date 2026-05-06
python -m kbo_crawler validate --game-id 20260506HHHT02026
python -m kbo_crawler export data/exports/20260506.csv --game-id 20260506HHHT02026
python -m kbo_crawler coverage
```

1군 등록 현황과 선수 일별 기록:

```powershell
python -m kbo_crawler roster 2026-07-19
python -m kbo_crawler player-daily 67893 --season 2026 --role both
```

## 저장 및 품질 보증

- 모든 JSON/HTML 원본은 gzip으로 보관하며 SHA-256과 요청 파라미터를
  `source_requests`에 기록합니다.
- SQLite는 foreign key, WAL, busy timeout과 마이그레이션 체크섬을
  사용합니다.
- 한 경기의 정규화 쓰기는 단일 트랜잭션이며 재실행 시 같은 결과가
  나오도록 교체 적재합니다.
- 중복/누락 투구 ID, 고아 타석, 한 타석 내 타자 혼합, 투구 순서,
  KBO 공식 득점과 Naver 일정 득점 불일치를 검사합니다.
- 실패한 KBO 응답이 HTML인지, Content-Type이 올바른지, ASMX 업무
  코드가 정상인지 확인합니다.
- 오류가 있는 경기는 삭제하지 않고 `quarantined` 상태로 남깁니다.

`crossPlateY`는 높이가 아니라 플레이트 방향의 Y 좌표입니다. 시뮬레이터와
내보내기는 고정 `z0=5.8`을 사용하지 않고 원본 `y0/z0`, 속도, 가속도로
실제 플레이트 통과 높이(`plate_height`)를 계산합니다.

## 스키마

핵심 테이블은 `games`, `plate_appearances`, `pitches`, `game_events`,
`batting_boxscores`, `pitching_boxscores`, `roster_daily`,
`player_daily_official`, `source_requests`, `data_quality_issues`입니다.
원본과 정규화 데이터가 함께 있어 파서 변경 후 원본을 다시 내려받지 않고
재처리할 수 있습니다.

## 시뮬레이터

```powershell
python -m pip install -e ".[simulation]"
streamlit run Simulation/pitch_sim_streamlit.py
```

시뮬레이터는 SQLite의 실제 `plate_appearance_id`를 사용하므로 투구 번호가
리셋되는지를 보고 타석을 추정하지 않습니다.

## 테스트

```powershell
python -m pytest -q
```

테스트에는 원본 보관·SQLite 트랜잭션, Naver/KBO/STATIZ 파서, type 23
결과, PTS outer join, 이벤트 전용 relay, 박스스코어 멱등 적재와 투구
물리 계산이 포함됩니다.
