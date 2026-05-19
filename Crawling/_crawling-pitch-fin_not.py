import os
import time
import requests
import pandas as pd

TARGET_GAME_ID = "20260506HHHT02026" 

FILE_PREFIX_PITCH = "data/pitch_data/kbo_pitch_data"
FILE_PREFIX_HITTER = "data/game_hitter_data/kbo_hitter_data"

def fetch_kbo_relay_json(game_id, inning):
    """네이버 스포츠 API에서 특정 경기 및 이닝의 원본 JSON 데이터를 가져옵니다."""
    url = f"https://api-gw.sports.naver.com/schedule/games/{game_id}/relay"
    params = {"inning": inning}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, params=params, headers=headers)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"❌ {inning}회 요청 중 통신 오류 발생: {e}")
    return None

def check_max_inning(json_data, current_inning):
    """이닝 스코어 보드를 확인하여 경기가 종료되었거나 데이터가 없는지 확인합니다."""
    if not json_data or "result" not in json_data:
        return False
    
    # 이닝 스코어에 현재 조사 중인 이닝의 점수가 등록되어 있는지 확인
    inning_score = json_data["result"].get("textRelayData", {}).get("inningScore", {})
    home_scores = inning_score.get("home", {})
    away_scores = inning_score.get("away", {})
    
    str_inn = str(current_inning)
    # 홈이나 원정 팀 중 하나라도 해당 이닝의 기록(숫자 또는 종료표시 '-')이 있으면 살아있는 이닝
    if str_inn in home_scores or str_inn in away_scores:
        return True
    
    # 만약 스코어보드에 없더라도 실제 릴레이 텍스트가 존재하면 유효한 이닝으로 판단
    text_relays = json_data["result"].get("textRelayData", {}).get("textRelays", [])
    if text_relays:
        return True
        
    return False

def parse_and_separate_data(json_data):
    """한 이닝의 데이터에서 '투구/구종 데이터'와 '타석/나머지 데이터'를 완벽히 분리 추출합니다."""
    pitch_list = []
    batting_list = []
    
    result_data = json_data.get("result", {})
    text_relay_data = result_data.get("textRelayData", {})
    text_relays = text_relay_data.get("textRelays", [])
    
    for relay in text_relays:
        inn = relay.get("inn")
        home_away = "Home" if relay.get("homeOrAway") == "1" else "Away"
        title = relay.get("title")  # 예: "8번타자 한준수", "4회말 KIA 공격"
        
        # 1. 나머지 데이터 (타석 상황, 타자/투수의 당시 시즌 스탯 및 경기 스탯)
        batter_rec = relay.get("batterRecord", {})
        current_players = relay.get("currentPlayersInfo", {})
        
        # 타자/투수 이름 및 코드
        b_name = batter_rec.get("name", "")
        b_code = batter_rec.get("pcode", "")
        
        # 현재 매칭된 투수 정보는 플레이어 인포에서 추출
        p_name = ""
        p_code = json_data.get("result", {}).get("currentGameState", {}).get("pitcher", "") # 현재 바뀐 투수 정보 백업용
        
        home_player = current_players.get("home", {})
        away_player = current_players.get("away", {})
        
        # 당시 스탯 결합 (시즌 타율, 방어율 등)
        b_season_hra = batter_rec.get("seasonHra", "")
        p_season_era = ""
        
        if home_player.get("playerType") == "pitcher":
            p_season_era = home_player.get("currentSeasonStats", {}).get("era", "")
        elif away_player.get("playerType") == "pitcher":
            p_season_era = away_player.get("currentSeasonStats", {}).get("era", "")

        batting_record = {
            "이닝": inn,
            "공격팀구분": home_away,
            "이벤트타이틀": title,
            "타자명": b_name,
            "타자코드": b_code,
            "타자시즌타율": b_season_hra,
            "투수코드(당시)": p_code,
            "투수시즌방어율": p_season_era,
            "텍스트로그요약": " ".join([opt.get("text", "") for opt in relay.get("textOptions", []) if opt.get("type") == 13])
        }
        batting_list.append(batting_record)
        
        # 2. 투구 구종 및 위치 트래킹 데이터 분리
        pts_options = relay.get("ptsOptions", [])
        text_options = relay.get("textOptions", [])
        
        for i, pts in enumerate(pts_options):
            pitch_id = pts.get("pitchId")
            
            # 구종 및 구속 매핑
            stuff = "알수없음"
            speed = "0"
            pitch_num = i + 1
            
            for opt in text_options:
                if opt.get("ptsPitchId") == pitch_id:
                    stuff = opt.get("stuff", "알수없음")
                    speed = opt.get("speed", "0")
                    pitch_num = opt.get("pitchNum", pitch_num)
                    break
            
            pitch_record = {
                "이닝": inn,
                "공격팀구분": home_away,
                "타자명": b_name,
                "투구ID": pitch_id,
                "상대타석내구수": pitch_num,
                "구종(stuff)": stuff,
                "구속(speed)": float(speed) if speed else 0.0,
                "좌우위치(crossPlateX)": pts.get("crossPlateX"),
                "상하위치(crossPlateY)": pts.get("crossPlateY"),
                "S존상단(topSz)": pts.get("topSz"),
                "S존하단(bottomSz)": pts.get("bottomSz"),
                "타자타석방향(stance)": pts.get("stance"),
                "초속X(vx0)": pts.get("vx0"),
                "초속Y(vy0)": pts.get("vy0"),
                "초속Z(vz0)": pts.get("vz0"),
                "가속도X(ax)": pts.get("ax"),
                "가속도Y(ay)": pts.get("ay"),
                "가속도Z(az)": pts.get("az")
            }
            pitch_list.append(pitch_record)
            
    return pitch_list, batting_list

def collect_full_game_data(game_id):
    """1회부터 경기 종료까지 추적하며 데이터를 분리 수집 및 저장합니다."""
    all_pitches = []
    all_battings = []
    
    current_inning = 1
    consecutive_empty_count = 0  # 혹시 모를 데이터 빈 칸 방어용
    
    print(f"🚀 KBO 경기 [{game_id}] 전이닝 추적 수집을 시작합니다.")
    
    while True:
        print(f"🔄 {current_inning}회차 데이터 다운로드 중...", end="", flush=True)
        json_data = fetch_kbo_relay_json(game_id, current_inning)
        
        # 해당 이닝에 실제 데이터가 유효한지 검증
        if not check_max_inning(json_data, current_inning):
            consecutive_empty_count += 1
            print(" -> [데이터 없음 또는 경기 종료 판정]")
            # 2개 이닝 연속으로 데이터가 아예 없다면 정규/연장전이 완전히 끝난 것으로 간주하고 루프 탈출
            if consecutive_empty_count >= 2 or current_inning > 12: 
                break
            current_inning += 1
            continue
        
        consecutive_empty_count = 0
        
        # 파싱 및 구종/나머지 데이터 이원화 분리
        pitches, battings = parse_and_separate_data(json_data)
        all_pitches.extend(pitches)
        all_battings.extend(battings)
        
        print(f" -> [완료] (투구: {len(pitches)}건 / 타석로그: {len(battings)}건 추출)")
        
        current_inning += 1
        time.sleep(0.5)  # 네이버 서버 과부하 및 차단 방지용 딜레이
        
    # --- 엑셀(CSV) 저장 단계 ---
    if all_pitches:
        df_pitches = pd.DataFrame(all_pitches)
        pitch_file = f"{FILE_PREFIX_PITCH}_구종_위치_데이터_{game_id}.csv"
        df_pitches.to_csv(pitch_file, index=False, encoding="utf-8-sig")
        print(f"💾 구종/트래킹 데이터 저장 완료: {pitch_file} ({len(df_pitches)}건)")
    else:
        print("⚠️ 수집된 투구 데이터가 없습니다.")
        
    if all_battings:
        df_battings = pd.DataFrame(all_battings)
        batting_file = f"{FILE_PREFIX_HITTER}_타석_나머지_데이터_{game_id}.csv"
        df_battings.to_csv(batting_file, index=False, encoding="utf-8-sig")
        print(f"💾 타석/나머지 기록 데이터 저장 완료: {batting_file} ({len(df_battings)}건)")
    else:
        print("⚠️ 수집된 타석 기록 데이터가 없습니다.")

# --- 수집기 실행 ---
if __name__ == "__main__":
    # 원하는 KBO 경기 ID를 입력하세요.
    collect_full_game_data(TARGET_GAME_ID)