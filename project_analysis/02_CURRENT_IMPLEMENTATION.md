# 현재 구현

## 디렉터리

| 위치 | 역할 |
|---|---|
| `src/kbo_crawler/` | 수집, 파싱, 저장, 검증, CLI |
| `src/kbo_crawler/sources/` | Naver, KBO, STATIZ HTTP 어댑터 |
| `src/kbo_crawler/parsers/` | 원본 응답의 순수 파서 |
| `src/kbo_crawler/migrations/` | SQLite 마이그레이션 |
| `tests/` | 픽스처 기반 단위·통합 테스트 |
| `Simulation/` | SQLite 기반 PTS 궤적 시각화 |
| `Crawling/` | 제거된 레거시 크롤러의 전환 안내 |
| `data/raw/` | gzip 원본 응답, Git 제외 |
| `data/kbo.sqlite` | 정규화 데이터베이스, Git 제외 |

## 기간 래퍼

```powershell
python -m kbo_crawler period `
  --from-date 2025-03-01 `
  --to-date 2025-11-30
```

기간의 모든 날짜를 순서대로 확인한다. 발견된 종료 경기는 모든 이닝의
중계·PTS를 수집하고, KBO 공식 응답을 보관·검산한다. 이미
`validated`인 경기는 건너뛰므로 중단 후 같은 명령을 다시 실행할 수 있다.

옵션:

- `--refresh`: 검증 완료 경기도 다시 수집
- `--with-rosters`: 기간의 모든 날짜에 1군 등록 명단 추가 수집
- `--with-player-daily`: 관측 선수×시즌×역할별 공식 일별 페이지 수집
- `--no-kbo`: KBO 공식 게임센터 검산 생략
- `--include-live`: 종료 상태가 아닌 경기에도 수집 시도

## 데이터 수집

### Naver

- `/schedule/games`의 `fromDate`/`toDate`로 경기 ID 발견
- 이닝별 relay 수집
- `textOptions`와 `ptsOptions` outer join
- type 13과 type 23 타석 결과 보존
- `relay.no`, `seqno`, 원본 `pitchNum` 보존
- PTS가 없거나 텍스트 이벤트가 없는 행도 손실 없이 보존

### KBO

- 게임센터 세션 bootstrap
- ASMX 스코어보드와 박스스코어
- 선수 타자/투수 일별 기록
- 1군 등록·말소와 전체 등록 현황
- HTML 오응답, 잘못된 Content-Type, 업무 오류 코드 검사

### STATIZ

- 기본 비활성 검산 소스
- WAR, wRC+, FIP, WHIP, BABIP 등 집계 지표 파싱
- 핵심 사실 데이터의 주 출처로 사용하지 않는다.

## 저장과 검증

- SQLite foreign key, WAL, busy timeout
- 마이그레이션 체크섬과 원자적 적용
- 경기 단위 트랜잭션과 멱등 교체 적재
- gzip 원본, SHA-256, 요청 파라미터와 provenance
- 중복/누락 투구, 고아 타석, 타자 혼합, 비단조 투구 순서 검사
- KBO 득점과 일정 득점 비교
- 물리 외삽 높이 0~6ft 밖의 행은 삭제하지 않고 경고

## 실제 검증 결과

2026-05-06 전체 5경기:

| 항목 | 결과 |
|---|---:|
| 경기 | 5 |
| 검증 완료 | 5 |
| 타석 | 374 |
| 투구 | 1,405 |
| 이벤트 | 2,525 |
| 원본 파일 | 51 |
| SQLite integrity check | `ok` |

동일 날짜의 다른 경기에서 같은 Naver `pitch_id`가 82개 발견되었다.
이를 통해 전역 투구 기본키 결함을 확인했고, 마이그레이션 002에서
`(game_id, pitch_id)` 복합키로 수정했다.

현재 자동 테스트는 50개이며 모두 통과한다.
