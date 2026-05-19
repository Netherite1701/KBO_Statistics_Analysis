import requests
import json
import pprint

def crawl_kbo_game_review(game_id, le_id="1", sr_id="0", season_id="2026"):
    """
    KBO 공식 서버의 비동기 ASMX 백엔드 주소로 POST 요청을 보내어
    스코어보드 및 상세 박스스코어 raw 데이터를 수집하는 함수입니다.
    모든 요청 과정과 서버 응답 상태를 극도로 상세하게 출력(Verbose)합니다.
    """
    print("\n" + "="*80)
    print(f"🚀 [크롤링 시작] KBO 경기 리뷰 데이터 수집 프로세스를 개시합니다.")
    print(f"   - 목표 경기 ID (Game ID)  : {game_id}")
    print(f"   - 리그 ID (League ID)    : {le_id}")
    print(f"   - 시리즈 ID (Series ID)  : {sr_id}")
    print(f"   - 시즌 정보 (Season ID)  : {season_id}")
    print("="*80)
    
    # 1. 브라우저 접속으로 위장하기 위한 HTTP 헤더 정의 및 상세 로깅
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    # 2. 서버 전송용 페이로드(딕셔너리) 구성
    payload = {
        "leId": le_id,
        "srId": sr_id,
        "seasonId": season_id,
        "gameId": game_id
    }
    
    print("\n📋 [HTTP REQUEST CONFIG] 전송할 헤더 및 페이로드 세부 정보:")
    print("  [Headers]")
    pprint.pprint(headers, indent=4)
    print("  [Payload / Data]")
    pprint.pprint(payload, indent=4)
    print("-"*80)
    
    # 3. 스코어보드 데이터 수집 (GetScoreBoardScroll)
    scoreboard_url = "https://www.koreabaseball.com/ws/Schedule.asmx/GetScoreBoardScroll"
    print(f"\n📡 [STEP 1] 스코어보드 API 요청 전송 중...")
    print(f"   - Target URL: {scoreboard_url}")
    
    try:
        res_score = requests.post(scoreboard_url, data=payload, headers=headers)
        print(f"   - HTTP 응답 상태 코드 (Status Code): {res_score.status_code}")
        print(f"   - 수신된 데이터 총 길이 (문자열 수): {len(res_score.text)} 글자")
    except Exception as e:
        print(f"   ❌ [네트워크 에러] 스코어보드 요청 중 치명적 오류 발생: {e}")
        return None, None
        
    # 4. 박스스코어 상세 데이터 수집 (GetBoxScoreScroll)
    boxscore_url = "https://www.koreabaseball.com/ws/Schedule.asmx/GetBoxScoreScroll"
    print(f"\n📡 [STEP 2] 상세 박스스코어(타자/투수 기록) API 요청 전송 중...")
    print(f"   - Target URL: {boxscore_url}")
    
    try:
        res_box = requests.post(boxscore_url, data=payload, headers=headers)
        print(f"   - HTTP 응답 상태 코드 (Status Code): {res_box.status_code}")
        print(f"   - 수신된 데이터 총 길이 (문자열 수): {len(res_box.text)} 글자")
    except Exception as e:
        print(f"   ❌ [네트워크 에러] 박스스코어 요청 중 치명적 오류 발생: {e}")
        return None, None
    
    # 5. HTTP 연결 상태 최종 검증
    print("\n🔄 [STEP 3] HTTP 응답 유효성 검증 단계")
    if res_score.status_code != 200 or res_box.status_code != 200:
        print(f"   ❌ [서버 오류] 정상적인 응답을 받지 못했습니다.")
        print(f"      - 스코어보드 상태: {res_score.status_code} / 박스스코어 상태: {res_box.status_code}")
        return None, None
    print("   ✅ 두 API 요청 모두 HTTP 200 OK 통신 성공을 확인했습니다.")
        
    # 6. Raw 텍스트 데이터를 JSON 객체(파이썬 Dict)로 역직렬화
    print("\n🔄 [STEP 4] 수신된 Raw 텍스트의 JSON 포맷 변환(Deserialization) 시도")
    try:
        score_data = res_score.json()
        print(f"   ✅ 스코어보드 텍스트 -> JSON 파싱 성공 (최상위 데이터 타입: {type(score_data)})")
        
        box_data = res_box.json()
        print(f"   ✅ 박스스코어 텍스트 -> JSON 파싱 성공 (최상위 데이터 타입: {type(box_data)})")
    except Exception as e:
        print(f"   ❌ [파싱 오류] JSON 규격 변환 중 에러가 발생했습니다: {e}")
        print(f"      - 스코어보드 앞부분 샘플: {res_score.text[:150]}")
        print(f"      - 박스스코어 앞부분 샘플: {res_box.text[:150]}")
        return None, None

    # 7. KBO 공식 서버 고유 비즈니스 응답 코드('100') 확인 검증
    print("\n🔄 [STEP 5] KBO 내부 내부 로직 코드('code') 유효성 검증")
    kbo_score_code = score_data.get("code")
    kbo_box_code = box_data.get("code")
    print(f"   - 스코어보드 리턴 코드: '{kbo_score_code}' (정상 기준: '100')")
    print(f"   - 박스스코어 리턴 코드: '{kbo_box_code}' (정상 기준: '100')")
    
    if kbo_score_code != "100" or kbo_box_code != "100":
        print("   ❌ [인증/데이터 오류] KBO 서버가 정상 데이터 반환을 거부했습니다. (code가 100이 아님)")
        return None, None
        
    print("\n✨ [성공] 서버 응답 수신, 데이터 검증 및 1차 파싱이 완벽하게 완료되었습니다.")
    print("="*80 + "\n")
    return score_data, box_data


def parse_hitter_data(box_data):
    """
    수신된 대용량 박스스코어 데이터에서 타자 성적 테이블을 
    구조 추적 및 예외 처리를 곁들여 가장 상세하게 해부(Parsing)합니다.
    """
    print("="*80)
    print("🔍 [데이터 세부 파싱 체인 가동] 타자 데이터 추출 및 심층 트래킹을 시작합니다.")
    print("="*80)
    
    if not box_data:
        print("❌ [중단 오류] 입력된 box_data 객체가 비어있어(None) 파싱을 진행할 수 없습니다.")
        return

    # 최상위 키 목록 노출
    top_keys = list(box_data.keys())
    print(f"ℹ️ [구조 분석] 수신된 box_data의 최상위 Key 리스트: {top_keys}")
    
    # arrHitter 데이터 추출
    arr_hitter = box_data.get("arrHitter", [])
    print(f"ℹ️ [구조 분석] 'arrHitter' 추출 결과 -> 데이터 타입: {type(arr_hitter)}, 포함된 원소 개수: {len(arr_hitter)}개")
    
    if not arr_hitter:
        print("⚠️ [경고] 'arrHitter' 내부 배열이 비어있습니다. 경기 취소 혹은 데이터 누락일 수 있습니다.")
        return

    # arrHitter 내부는 통상 [0] = 원정팀 기록, [1] = 홈팀 기록 구조임
    for idx, team_hitter_raw in enumerate(arr_hitter):
        team_label = "원정팀 (Index 0 - 예: KIA)" if idx == 0 else "홈팀 (Index 1 - 예: 삼성)"
        print(f"\n" + "하위 파싱 구간 진입 " + f"[{idx+1} / {len(arr_hitter)}] ----------------------------------------")
        print(f"🎯 분석 대상 그룹: {team_label}")
        print(f"   - 추출 직후 'team_hitter_raw' 객체의 원본 타입: {type(team_hitter_raw)}")
        
        # 🔥 [치명적 구간 대책] KBO 서버 특성상 데이터가 JSON 문자열(str)로 압축되어 들어오는 오류 유발 케이스 방어
        if isinstance(team_hitter_raw, str):
            print("   ⚠️ [구조적 특이점 발견] 데이터가 일반 딕셔너리가 아닌 '문자열(String)' 형태로 격리되어 있습니다.")
            print("   🔄 [자동 긴급 조치] json.loads()를 수행하여 텍스트를 파이썬 딕셔너리 구조로 복원합니다.")
            try:
                team_hitter_raw = json.loads(team_hitter_raw)
                print(f"   ✅ [복원 성공] 변환 후 데이터 타입이 정상적으로 갱신되었습니다: {type(team_hitter_raw)}")
            except Exception as inner_e:
                print(f"   ❌ [복원 실패] 문자열 역직렬화 도중 에러 발생: {inner_e}")
                print(f"      - 문제의 데이터 스니펫: {str(team_hitter_raw)[:200]}...")
                continue # 다음 팀 데이터로 패스
                
        # 정상 딕셔너리화 해제 확인 후 키 조회
        if isinstance(team_hitter_raw, dict):
            sub_keys = list(team_hitter_raw.keys())
            print(f"   - 변환이 완료된 팀 객체의 내부 하위 Key 리스트: {sub_keys}")
        else:
            print(f"   ❌ [구조 왜곡 오류] 데이터 정제에 실패하여 하위 키를 읽을 수 없습니다. (타입: {type(team_hitter_raw)})")
            continue

        # 타자 테이블은 보통 table1(기초 성적), table2(타석 결과 세부) 등으로 나뉩니다. 기본 table1 타겟팅
        target_tables = ["table1"]
        for t_key in target_tables:
            print(f"\n   📊 [테이블 분석] 현재 탐색 중인 세부 세그먼트: '{t_key}'")
            table_content = team_hitter_raw.get(t_key, {})
            print(f"     - '{t_key}' 내용물의 데이터 타입: {type(table_content)}")
            
            # 2차 중첩 문자열 구조 방어형 검사
            if isinstance(table_content, str):
                print(f"     ⚠️ [중중첩 구조 경고] '{t_key}' 내부 데이터마저 문자열(str) 형태입니다.")
                print(f"     🔄 [2차 긴급 조치] json.loads()를 적용하여 내부 딕셔너리를 추출합니다.")
                try:
                    table_content = json.loads(table_content)
                    print(f"     ✅ [2차 복원 성공] 최종 타입: {type(table_content)}")
                except Exception as inner_e2:
                    print(f"     ❌ [2차 복원 실패] 디코딩 실패: {inner_e2}")
                    continue

            if not isinstance(table_content, dict):
                print(f"     ❌ [스키마 불일치] '{t_key}'의 데이터가 유효한 딕셔너리가 아니므로 스킵합니다.")
                continue

            # 실제 행 데이터(rows) 수집 구간 진입
            rows = table_content.get("rows", [])
            print(f"     ℹ️ '{t_key}' 내에 포진한 'rows' 리스트의 총 데이터 행 수: {len(rows)}개")
            
            if not rows:
                print(f"     ⚠️ '{t_key}' 내부에 추출 가능한 'rows' 데이터 행이 비어있습니다.")
                continue

            print(f"     📝 [전체 행 순회 및 셀단위 데이터 해체 작업 개시]")
            
            # 각 선수/항목별 데이터 행 순회
            for r_idx, row in enumerate(rows):
                print(f"\n        📍 [Row {r_idx:02d} / 총 {len(rows)}개 중] 상세 트래킹 정보")
                print(f"           - 현재 row 객체의 자체 타입: {type(row)}")
                
                # 가끔 row마저 문자열로 유입되는 최악의 상황 보완
                if isinstance(row, str):
                    try:
                        row = json.loads(row)
                    except:
                        pass
                
                if not isinstance(row, dict):
                    print(f"           ❌ [타입 에러] 데이터 행이 딕셔너리가 아닙니다. 무시하고 다음 행으로 이동합니다.")
                    continue

                # 하나의 행 내부에 실제 셀(칸) 데이터들이 모여있는 리스트('row') 추출
                row_cells = row.get("row", [])
                print(f"           - 본 행에 탑사된 총 셀(Cells/Columns) 개수: {len(row_cells)}개")
                
                # 각 셀 내부의 'Text' 속성을 하나씩 분석하여 완전한 리스트로 조립
                parsed_text_list = []
                for c_idx, cell in enumerate(row_cells):
                    if isinstance(cell, dict):
                        cell_text = cell.get("Text")
                        cell_class = cell.get("Class") # HTML 클래스 속성 (포지션 구분용, 색상용 등)
                        
                        parsed_text_list.append(cell_text)
                        
                        # 극도로 자세히 찍고 싶을 때 하단 주석을 해제하시면 셀 하나하나의 속성까지 터미널에 노출됩니다.
                        # print(f"             * [Cell {c_idx:02d}] Text='{cell_text}', Class='{cell_class}'")
                    else:
                        parsed_text_list.append(None)
                        print(f"             ⚠️ [Cell {c_idx:02d} 경고] 셀 객체가 정상적인 딕셔너리 포맷이 아닙니다.")

                # 추출 정제 완료된 행 단위 리스트 최종 보고
                print(f"           ✨ [행 파싱 완료]최종 추출 데이터 -> {parsed_text_list}")
                
                # 데이터 정제 단계 힌트 (분석 불필요 데이터 필터링 시점 트래킹)
                if parsed_text_list and parsed_text_list[0] and "합계" in str(parsed_text_list[0]):
                    print(f"           ℹ️ [정제 필터 안내] 해당 행은 '팀 전체 기록 합계 행'으로 감지되었습니다. 추후 선수 개인 분석 시 제거 필요.")
                    
    print("\n" + "="*80)
    print("✅ [파싱 종료] 모든 팀과 모든 하위 테이블 셀의 정밀 추적이 안전하게 끝났습니다.")
    print("="*80)


# ==============================================================================
# 실제 구동 테스트 베드 실행 블록
# ==============================================================================
if __name__ == "__main__":
    print("▶️ [SYSTEM] KBO 초정밀 디버깅 크롤러 테스트 스크립트를 작동합니다.")
    
    # 분석 타겟팅: 대구 KIA vs 삼성 경기 고유 ID (2026년 5월 15일 경기)
    TARGET_GAME_ID = "20260515HTSS0" 
    
    # 1. 크롤링 및 네트워크 통신 실행 (매우 상세한 내부 출력 포함)
    score_result, box_result = crawl_kbo_game_review(
        game_id=TARGET_GAME_ID,
        le_id="1",
        sr_id="0",
        season_id="2026"
    )
    
    # 2. 크롤링 성공 여부에 따른 후속 파싱 연계 및 로깅 완료 처리
    if box_result:
        print("🎉 [데이터 확보 성공] 후속 정밀 파싱 함수(parse_hitter_data)로 제어권을 이양합니다.\n")
        parse_hitter_data(box_result)
    else:
        print("❌ [데이터 확보 실패] 네트워크 응답 오류 혹은 유효하지 않은 Game ID로 인해 세부 파싱을 생략합니다.")