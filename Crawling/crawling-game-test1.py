import requests
import json

def crawl_kbo_game_review(game_id, le_id="1", sr_id="0", season_id="2026"):
    # 브라우저 접속으로 위장하기 위한 헤더 세팅
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    # POST 요청 시 전송할 페이로드 데이터
    payload = {
        "leId": le_id,
        "srId": sr_id,
        "seasonId": season_id,
        "gameId": game_id
    }
    
    # 1. 스코어보드 데이터 수집 (GetScoreBoardScroll)
    scoreboard_url = "https://www.koreabaseball.com/ws/Schedule.asmx/GetScoreBoardScroll"
    print(f"📡 [1] KBO 서버에 스코어보드 API 요청 중... (Game ID: {game_id})")
    res_score = requests.post(scoreboard_url, data=payload, headers=headers)
    
    # 2. 박스스코어 상세 데이터 수집 (GetBoxScoreScroll)
    boxscore_url = "https://www.koreabaseball.com/ws/Schedule.asmx/GetBoxScoreScroll"
    print(f"📡 [2] KBO 서버에 상세 박스스코어 API 요청 중...")
    res_box = requests.post(boxscore_url, data=payload, headers=headers)
    
    # 연결 상태 확인
    if res_score.status_code != 200 or res_box.status_code != 200:
        print("❌ 서버 응답 실패 (HTTP Status Code 오류)")
        return None, None
        
    try:
        score_data = res_score.json()
        box_data = res_box.json()
    except Exception as e:
        print(f"❌ JSON 변환 에러 발생: {e}")
        return None, None

    # KBO 서버 고유의 성공 응답 코드 확인 ('100')
    if score_data.get("code") != "100" or box_data.get("code") != "100":
        print("❌ 서버 응답 코드가 올바르지 않습니다.")
        return None, None
        
    print("📡 [3] 서버 응답 수신 및 파싱 완료 (응답 코드: 100)")
    return score_data, box_data

def parse_hitter_data(box_data):
    """
    수신된 박스스코어 데이터에서 타자 기록을 안전하게 파싱하는 예시 함수
    """
    # arrHitter 내부에는 [0]: 원정팀 타자 기록, [1]: 홈팀 타자 기록이 포함됨
    arr_hitter = box_data.get("arrHitter", [])
    
    for idx, team_hitter_raw in enumerate(arr_hitter):
        team_label = "원정팀(KIA)" if idx == 0 else "홈팀(삼성)"
        print(f"\n==================================================🔍 [{team_label} 타자 데이터 파싱]")
        
        # ⚠️ KBO 서버 특성상 내부 데이터(table1, table2 등)가 JSON 객체가 아닌 
        # 직렬화된 '문자열(str)' 형태로 내려올 수 있으므로 타입을 강제 전환해 줍니다.
        table1_data = team_hitter_raw.get("table1", {})
        if isinstance(table1_data, str):
            table1_data = json.loads(table1_data)
            
        rows = table1_data.get("rows", [])
        print(f"ℹ️ 수집된 타자 Row 개수: {len(rows)}개")
        
        # 상위 3명의 선수 이름 데이터 샘플 출력 구조 추적
        for i, row in enumerate(rows[:3]):
            row_cells = row.get("row", [])
            # cell 내부의 'Text' 속성에 선수명 및 포지션이 들어있음
            parsed_text = [cell.get("Text") for cell in row_cells if cell.get("Text") is not None]
            print(f"  -> [타자 Row {i}] 파싱 데이터: {parsed_text}")

# 실제 실행 테스트
if __name__ == "__main__":
    # 제공해주신 대구 KIA vs 삼성 경기 고유 ID
    TARGET_GAME_ID = "20260515HTSS0" 
    
    score_result, box_result = crawl_kbo_game_review(TARGET_GAME_ID)
    
    if box_result:
        parse_hitter_data(box_result)