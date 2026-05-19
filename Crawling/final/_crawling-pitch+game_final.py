#TODO: get  pitcher name 

import time
import requests
import pandas as pd
import logging

# 💡 로그 설정을 통해 프로그램의 상태를 예쁘게 출력합니다.
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

TARGET_GAME_ID = "20260506HHHT02026"
SAVE_PATH = r"C:\dev\Python_Projects\KBO_Stat_Analysis\data\game_data\\" + f"KBO_GameData_{TARGET_GAME_ID}.csv"

def fetch_kbo_relay_json(game_id, inning):
    """네이버 스포츠 API에서 JSON 데이터를 가져옵니다."""
    url = f"https://api-gw.sports.naver.com/schedule/games/{game_id}/relay"
    params = {"inning": inning}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        response = requests.get(url, params=params, headers=headers)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"🚨 네트워크 오류: {e}")
    return None

def get_batter_name_verbose(relay_data):
    """텍스트로그에서 타자 이름을 안정적으로 추출합니다."""
    batter_rec = relay_data.get("batterRecord", {})
    name = batter_rec.get("name")
    if name: return name
    
    text_options = relay_data.get("textOptions", [])
    for opt in text_options:
        if opt.get("type") == 13:
            text = opt.get("text", "")
            if ":" in text:
                return text.split(":")[0].strip()
    return "N/A"

def get_pitcher_name(relay_data):
    """💡 currentPlayersInfo에서 투수 이름 추출"""
    players = relay_data.get("currentPlayersInfo", {})
    # home 또는 away 객체 안에서 playerType이 pitcher인 데이터를 찾습니다.
    for team in ['home', 'away']:
        player = players.get(team, {})
        if player.get("playerType") == "pitcher":
            return player.get("name", "알수없음")
    return "알수없음"

def extract_full_game_data(game_id):
    all_rows = []
    print("\n" + "✨" * 10 + " KBO 데이터 추출 시스템 가동 " + "✨" * 10)
    print(f"📡 경기 ID: {game_id}")
    print("=" * 50 + "\n")

    for inning in range(1, 13):
        logger.info(f"⚾️ [{inning}회] 데이터 수집 시작...")
        data = fetch_kbo_relay_json(game_id, inning)
        
        if not data or "result" not in data:
            logger.warning(f"⚠️ [{inning}회] 데이터 없음 -> 패스합니다.")
            continue
            
        relays = data["result"].get("textRelayData", {}).get("textRelays", [])
        inning_pitch_count = 0
        
        for relay in reversed(relays):
            inn = relay.get("inn")
            home_away = "Home" if relay.get("homeOrAway") == "1" else "Away"
            b_name = get_batter_name_verbose(relay)
            p_name = get_pitcher_name(relay) # 💡 투수명 추출
            log_text = " ".join([opt.get("text", "") for opt in relay.get("textOptions", []) if opt.get("type") == 13])
            
            pts_options = relay.get("ptsOptions", [])
            for i, pts in enumerate(pts_options):
                pitch_id = pts.get("pitchId")
                text_opt = next((opt for opt in relay.get("textOptions", []) if opt.get("ptsPitchId") == pitch_id), {})
                
                row = {
                    "이닝": inn, 
                    "공격팀구분": home_away, 
                    "타자명": b_name, 
                    "투수명": p_name, # 💡 CSV 저장 항목에 투수명 추가
                    "투구ID": pitch_id, 
                    "상대타석내구수": i + 1,
                    "구종(stuff)": text_opt.get("stuff", "알수없음"),
                    "구속(speed)": float(text_opt.get("speed", 0.0)),
                    "좌우위치(crossPlateX)": pts.get("crossPlateX"),
                    "상하위치(crossPlateY)": pts.get("crossPlateY"),
                    "S존상단(topSz)": pts.get("topSz"), 
                    "S존하단(bottomSz)": pts.get("bottomSz"),
                    "타자타석방향(stance)": pts.get("stance"),
                    "초속X(vx0)": pts.get("vx0"), "초속Y(vy0)": pts.get("vy0"), "초속Z(vz0)": pts.get("vz0"),
                    "가속도X(ax)": pts.get("ax"), "가속도Y(ay)": pts.get("ay"), "가속도Z(az)": pts.get("az"),
                    "텍스트로그": log_text
                }
                all_rows.append(row)
                inning_pitch_count += 1
        
        logger.info(f"✅ [{inning}회] 완료! (추출: {inning_pitch_count}개)")
        time.sleep(0.5)

    if all_rows:
        df = pd.DataFrame(all_rows)
        df = df.sort_values(by=['이닝', '공격팀구분', '상대타석내구수']).reset_index(drop=True)
        df.to_csv(SAVE_PATH, index=False, encoding="utf-8-sig")
        
        print("\n" + "🎉" * 15)
        logger.info(f"💾 저장이 완료되었습니다! 경로: {SAVE_PATH}")
        logger.info(f"📊 최종 수집 데이터: {len(df)}행")
        print("🎉" * 15 + "\n")
    else:
        logger.error("🛑 추출할 수 있는 데이터가 없습니다.")

if __name__ == "__main__":
    extract_full_game_data(TARGET_GAME_ID)