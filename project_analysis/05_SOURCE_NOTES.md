# 출처와 추적성

## Naver Sports

기본 주소:

```text
https://api-gw.sports.naver.com
```

사용 endpoint:

- `/schedule/games`
  - `sectionId=kbaseball`
  - `categoryId=kbo`
  - `fromDate=YYYY-MM-DD`
  - `toDate=YYYY-MM-DD`
- `/schedule/season`
- `/schedule/games/{gameId}/relay?inning=N`

주의사항:

- `date` 하나만 사용하면 요청 날짜가 무시될 수 있으므로
  `fromDate`와 `toDate`를 함께 사용한다.
- 경기 ID를 날짜·팀 코드로 조합하지 않는다.
- type 13만 결과로 간주하면 안타·홈런 등에 사용되는 type 23을 잃는다.
- relay는 타석만 의미하지 않는다. 반이닝 헤더·교체·경기 요약도 포함한다.
- `pitch_id`는 같은 날 동시 경기에서 중복될 수 있다.
- PTS가 없는 일부 투구는 `ptsPitchId="-1"`을 공통 결측값으로 사용한다.
  이는 실제 ID가 아니므로 relay와 seqno 기반 synthetic ID로 대체한다.

## KBO 공식 사이트

기본 주소:

```text
https://www.koreabaseball.com
```

사용 범위:

- `Schedule/Schedule.aspx`
- `Schedule/GameCenter/Main.aspx`
- `ws/Schedule.asmx/GetScoreBoardScroll`
- `ws/Schedule.asmx/GetBoxScoreScroll`
- `Record/Player/HitterDetail/Daily.aspx`
- `Record/Player/PitcherDetail/Daily.aspx`
- `Player/Register.aspx`
- `Player/RegisterAll.aspx`

검사 항목:

- 게임센터 bootstrap과 세션 쿠키
- JSON이어야 할 응답의 HTML 여부
- Content-Type
- ASP.NET `d` wrapper
- KBO 업무 응답 코드
- 요청 시즌·날짜와 실제 페이지 선택값

KBO 장애나 차단은 Naver 원본 수집을 없애지 않는다. 접근 실패는
`source_requests`와 품질 이슈에 별도로 남긴다.

## STATIZ

사용 범위:

- 선수 기본·연도·일별·playlog·analysis 페이지
- WAR, WAA, wRC+, wOBA, OPS, ISO, BABIP, BB%, K%, FIP, WHIP, ERA+, WPA

기본적으로 비활성이다. KBO/Naver와 독립적인 집계 검산에만 사용한다.

## 원본 보존

각 응답은 다음 경로 형태로 gzip 저장한다.

```text
data/raw/{source}/{season}/{game-or-snapshot}/{endpoint}-{paramsHash}-{payloadHash}.json.gz
```

HTML은 `.html.gz`를 사용한다. `source_requests`에는 다음 정보를 기록한다.

- crawl run ID
- source와 endpoint
- HTTP method와 파라미터
- 요청 시각과 상태
- raw 상대 경로
- SHA-256
- 원본·압축 크기
- 오류 메시지

같은 요청에서 upstream 응답이 바뀌면 payload hash가 달라져 새 원본으로
보존된다. 파서가 변경되어도 저장된 원본을 이용해 재현할 수 있다.

## 검증 표본

2026-05-06:

- 일정 경기 5개
- 모든 경기 수집·검증 완료
- 374타석
- 1,405투구
- 2,525이벤트
- 복수 경기에서 공유된 원본 `pitch_id` 82개
- SQLite `integrity_check=ok`

기준 경기 `20260506HHHT02026`:

- 76타석
- 275투구
- type 13 결과 69개
- type 23 결과 7개
- `260506_201009`의 원본 `pitchNum=4`
