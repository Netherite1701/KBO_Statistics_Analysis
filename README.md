# KBO 경기·타석 분석 연구 저장소

이 저장소는 KBO 경기 기록을 모아 **타석별 결과, 투구 흐름, 선수·경기 기록, 장기 평균 출루율 기준선**을 만들기 위한 연구용 저장소입니다.

다른 사람이 이 저장소 링크를 ChatGPT나 다른 챗봇에 붙여넣고 질문할 수 있도록, 연구 목적과 자료 사용 방법을 이 문서에 정리했습니다.

현재 작업 브랜치: [agent/crawl-40-110](https://github.com/Netherite1701/KBO_Statistics_Analysis/tree/agent/crawl-40-110)

## 챗봇에 링크를 붙여넣을 때

아래 문장을 그대로 복사한 뒤 마지막에 질문을 적으면 됩니다.

```text
다음 GitHub 저장소를 연구 자료와 문서의 기준으로 삼아 답해줘:
https://github.com/Netherite1701/KBO_Statistics_Analysis/tree/agent/crawl-40-110

먼저 README.md와 docs/DATA_FORMAT_40_110.md를 읽고, 필요한 경우 관련 문서를 추가로 확인해줘.
답변할 때는 다음 원칙을 지켜줘.
1. 원본에 없는 값을 추정해서 만들지 말 것.
2. 빈칸을 자동으로 0이나 아웃으로 바꾸지 말 것.
3. quality_flag가 CHECK인 자료는 확정 자료와 구분할 것.
4. 파일의 한 행이 무엇을 뜻하는지와 분석에 사용할 분모를 먼저 확인할 것.
5. 자료에서 확인한 사실, 합리적인 해석, 아직 확인할 사항을 구분할 것.

내 질문:
여기에 질문을 적으세요.
```

### 링크만으로 가능한 질문

- 이 연구의 목적과 분석 단위는 무엇인가?
- `core_player_pa.csv`와 `player_game_boxscore.csv`의 차이는 무엇인가?
- `pa_sequence`, `pa_id`, `pa_result`는 어떤 뜻인가?
- 장기 평균 출루율 기준선을 만들 때 어떤 자료를 사용해야 하는가?
- `OK`, `CHECK`, `MISSING`, `INCOMPLETE`를 어떻게 해석해야 하는가?
- 수집 방식과 자료의 한계는 무엇인가?

### CSV 수치 계산이 필요한 질문

ZIP 안의 실제 CSV 행을 계산해야 하는 질문은 저장소 링크만 붙이는 것보다, 필요한 CSV를 내려받아 챗봇에 첨부하는 것이 정확합니다. 예를 들어 다음과 같이 질문합니다.

```text
data-archive.zip에서 연구용 CSV를 내려받았어.
research-2022-core/tables/core_player_pa.csv부터
research-2025-core/tables/core_player_pa.csv까지 사용해서
시즌별 출루 사건 수, 타석 수, 출루율을 계산해줘.
quality_flag가 CHECK인 행은 별도로 집계하고, 빈 pa_result는 임의로 아웃 처리하지 마.
```

챗봇이 LFS 파일을 링크만으로 읽지 못하면, 먼저 ZIP을 내려받아 압축을 풀거나 필요한 CSV 파일을 직접 첨부해야 합니다.

## 자료 받기

### 코드와 문서만 받기

```powershell
git clone -b agent/crawl-40-110 https://github.com/Netherite1701/KBO_Statistics_Analysis.git
cd KBO_Statistics_Analysis
```

### LFS 압축자료까지 받기

Git LFS를 설치한 뒤 다음을 실행합니다.

```powershell
git lfs install
git lfs pull
```

전체 원본·가공표 묶음은 저장소 루트의 `data-archive.zip`에 있습니다. 이 파일은 Git LFS로 관리되므로 LFS 없이 clone하면 실제 ZIP 대신 작은 포인터 파일만 내려올 수 있습니다.

압축을 풀면 다음과 같은 자료 묶음이 들어 있습니다.

```text
data-archive.zip
├─ research-2022-core/
├─ research-2023-core/
├─ research-2024-core/
├─ research-2025-core/
├─ research-2026-to-0811/
├─ research-40-110/
├─ research-80-backfill/
├─ research-merged/
├─ official-player-daily/
└─ ...
```

## 중요한 파일

| 파일 | 설명 |
|---|---|
| `docs/DATA_FORMAT_40_110.md` | 2026년 5월 자료의 폴더 구조와 CSV 열 정의 |
| `docs/RUN_RESULT_2026_05.md` | 2026년 5월 수집 범위와 검사 결과 |
| `docs/COLLECTION_LESSONS_80.md` | 2021~2024년 과거 시즌 수집 결과와 주의사항 |
| `Crawling/final/README_40_110.md` | 수집기 설치·실행·검사 방법 |
| `Crawling/final/crawl_research_40_110.py` | 일정·경기·투구 자료 수집기 |
| `Crawling/final/validate_research_40_110.py` | CSV 형식·중복·품질 검사기 |
| `data-archive.zip` | 연도별 원본과 분석용 CSV를 묶은 LFS 자료 |

## 타석별 결과 자료

장기 평균 출루율 기준선에 사용할 타석별 결과는 압축을 푼 뒤 각 연도 폴더의 `tables/core_player_pa.csv`에서 확인합니다.

```text
research-80-backfill/tables/core_player_pa.csv   # 2021
research-2022-core/tables/core_player_pa.csv     # 2022
research-2023-core/tables/core_player_pa.csv     # 2023
research-2024-core/tables/core_player_pa.csv     # 2024
research-2025-core/tables/core_player_pa.csv     # 2025
```

주요 열은 다음과 같습니다.

| 열 | 뜻 |
|---|---|
| `game_id` | 경기 식별자 |
| `pa_id` | 해당 경기 안의 타석 식별자 |
| `pa_sequence` | 경기 안에서 시간순으로 센 타석 순서 |
| `batter_id`, `batter_name` | 타자 번호와 이름 |
| `pitcher_id`, `pitcher_name` | 투수 번호와 이름 |
| `pa_result` | 타석 종료 결과 문장 |
| `quality_flag` | 자료 품질 상태 |
| `issue_reason` | 추가 확인이 필요한 이유 |

`player_game_boxscore.csv`는 선수×경기 요약표이고, `core_player_pa.csv`는 타석 단위 표입니다. 둘은 분석 단위가 다르므로 서로 대체해서 사용하지 않습니다.

## 품질과 해석 원칙

| 표시 | 뜻 |
|---|---|
| `OK` | 필요한 키와 값이 자료 안에서 확인됨 |
| `CHECK` | 원본은 있으나 다른 원본과 대조하거나 사람이 확인해야 함 |
| `MISSING` | 원본에 필요한 값이 없어 빈칸으로 남김 |
| `INCOMPLETE` | 선택한 기간의 수집이 아직 일정 전체와 맞지 않음 |

반드시 다음 원칙을 지킵니다.

- 빈 값은 자동으로 0으로 채우지 않습니다.
- `pa_result`가 비어 있으면 임의로 아웃이라고 판단하지 않습니다.
- `CHECK` 자료를 확정된 공식 기록처럼 표현하지 않습니다.
- 이름만으로 선수를 연결하지 않고 `player_id`와 경기 식별자를 함께 확인합니다.
- 타석 수와 출루율의 분모를 계산하기 전에 해당 표의 한 행 의미를 확인합니다.
- 1회 중계 자료와 경기 전체 타석 자료를 혼동하지 않습니다.

## 자료 출처

- 경기 일정·경기 식별자·박스스코어: KBO 공식 웹사이트
- 1군 등록 현황: KBO 공식 등록선수 페이지
- 경기별 선수 기록과 투구 중계: Naver Sports 경기 중계 응답

자료는 연구용으로 수집·정리한 것이며, 모든 열이 동일한 수준으로 공식 대조된 것은 아닙니다. 분석 결과를 확정하기 전에 각 파일의 `quality_flag`, `issue_reason`, 검사 로그를 확인해야 합니다.

## 수집기 실행

Python 3과 필요한 패키지를 설치합니다.

```powershell
pip install requests beautifulsoup4
```

2026년 5월 일정·등록선수 자료를 시험 수집하는 예시는 다음과 같습니다.

```powershell
python Crawling/final/crawl_research_40_110.py --years 2026 --months 5 --phases schedule roster
```

한 경기만 시험할 때는 다음처럼 실행합니다.

```powershell
python Crawling/final/crawl_research_40_110.py --years 2026 --months 5 --phases games --max-games 1
```

수집 후 기본 검사는 다음과 같습니다.

```powershell
python Crawling/final/validate_research_40_110.py
```

수집을 다시 실행할 때는 기존 원본을 덮어쓰지 않는지, `data-root`가 다른 시즌 자료와 분리되어 있는지 먼저 확인합니다.

## 챗봇에게 답변을 요청할 때의 기준

챗봇은 다음 순서로 자료를 읽어야 합니다.

1. README에서 연구 목적과 자료 범위를 확인합니다.
2. 관련 문서에서 열 정의와 행의 의미를 확인합니다.
3. 분석에 사용할 파일과 기간을 명시합니다.
4. `quality_flag`별 행 수와 결측을 확인합니다.
5. 계산식과 분모를 적습니다.
6. 확인된 결과와 추가 검증이 필요한 결과를 나누어 답합니다.

저장소의 문서와 데이터가 서로 다르게 보이면, 임의로 하나를 선택하지 말고 파일 경로·행의 의미·검사 로그를 함께 제시해야 합니다.
