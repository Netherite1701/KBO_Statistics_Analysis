# 데이터 사전

## 핵심 식별자

| 개체 | 키 | 설명 |
|---|---|---|
| 경기 | `games.game_id` | 일정 API에서 발견한 원본 경기 ID |
| 외부 경기 ID | `(source, external_game_id)` | 출처별 경기 ID 매핑 |
| 타석 | `plate_appearance_id` | `game_id:relay_no` |
| 투구 | `(game_id, pitch_id)` | Naver 투구 ID는 경기 안에서만 고유 |
| 이벤트 | `game_event_id` | 경기·relay·seqno 기반 내부 ID |
| 선수 | `player_id` | 내부 선수 ID |
| 외부 선수 ID | `(source, external_player_id)` | KBO/Naver/STATIZ ID 매핑 |

## 주요 테이블

### `games`

시즌, 시리즈 유형, 경기일, 상태, 홈/원정 팀, 점수와 수집 상태를 저장한다.

`ingestion_status`:

- `discovered`
- `raw`
- `parsed`
- `validated`
- `quarantined`

`series_type`은 `preseason`, `regular`, `postseason` 구분에 사용한다.

### `plate_appearances`

실제 투구 또는 결과 이벤트가 있는 relay만 타석으로 저장한다.
반이닝 헤더, 대타 교체 전 빈 relay, 경기 종료 요약은
`game_events`에만 저장한다.

주요 필드:

- `relay_no`, `inning`, `half`
- `batter_id`, `pitcher_id`
- `outs_before`, `balls_before`, `strikes_before`
- `result_text`, `result_event_type`
- `is_complete`

### `pitches`

| 필드 | 의미 |
|---|---|
| `pitch_id` | Naver 원본 투구 ID |
| `seqno` | 경기 이벤트 스트림 순서 |
| `pitch_num` | 원본 타석 내 투구 번호, 재계산하지 않음 |
| `pitch_result_code/text` | 볼·스트라이크·인플레이 결과 |
| `balls_after`, `strikes_after`, `outs_after` | 투구 후 경기 상태 |
| `runner_on_first/second/third` | 베이스 점유 상태 |
| `pitch_type`, `speed_kph` | 구종과 구속 |
| `x0`, `y0`, `z0` | 원본 초기 위치 |
| `vx0`, `vy0`, `vz0` | 원본 초기 속도 |
| `ax`, `ay`, `az` | 원본 가속도 |
| `cross_plate_x` | 플레이트 좌우 좌표 |
| `cross_plate_y` | 높이가 아닌 플레이트 방향 Y 좌표 |
| `plate_height` | 운동식으로 외삽한 플레이트 통과 Z 높이 |
| `strike_zone_top/bottom` | 해당 타자의 스트라이크존 |
| `raw_json` | 결합에 사용한 text/PTS 원본 |

`plate_height`는 측정 원본이 아니라 원본 궤적 계수로 계산한 값이다.
땅에 닿기 전후의 외삽이나 소스 fit 이상으로 0ft 미만이 될 수 있으므로
이상치를 지우지 않고 품질 경고를 남긴다.

Naver가 PTS 없는 투구에 `ptsPitchId="-1"` 또는 다른 결측 sentinel을
보내면 이를 실제 ID로 사용하지 않는다. 크롤러는
`synthetic:{relay_no}:{seqno}` 형식의 안정적인 ID를 부여하고
`missing_source_pitch_id` 경고를 남긴다. 원본 `-1`은 `raw_json`에
그대로 보존한다.

### `game_events`

투구, 타석 결과, 교체, 반이닝 헤더, 경기 요약을 포함한 모든 문자 중계
이벤트를 원본 순서대로 저장한다.

### 공식 기록

- `batting_boxscores`: 경기별 타자 공식 기록
- `pitching_boxscores`: 경기별 투수 공식 기록
- `player_daily_official`: 선수 일별 기록과 월 합계
- `roster_daily`: 날짜별 1군 등록·말소
- `statiz_metrics`: 선택적 검산 집계값

### 추적성과 품질

- `crawl_runs`: 기간/동기화 실행 상태와 요약
- `source_requests`: endpoint, 파라미터, 상태, raw 경로, SHA-256
- `data_quality_issues`: 경기별 경고·오류와 문맥
- `schema_migrations`: 적용 마이그레이션과 체크섬

## 시간 순서

분석과 내보내기의 기본 정렬은 다음 순서를 사용한다.

```text
game_date
→ game_id
→ relay_no
→ seqno
→ pitch_num
→ pitch_id
```

타석 번호나 투구 번호가 리셋되는지만 보고 타석 경계를 추정하지 않는다.
