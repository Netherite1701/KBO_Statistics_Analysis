import time
import re
import os
import html
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
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SAVE_PATH = os.path.join(PROJECT_ROOT, "data", "game_data", f"KBO_GameData_{TARGET_GAME_ID}.csv")
PLAYER_NAME_CACHE = {}

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

def build_player_name_map(text_relay_data):
    """엔트리 정보에서 선수 코드 -> 이름 맵을 만듭니다."""
    player_map = {}
    for entry_key in ("homeEntry", "awayEntry"):
        entry = text_relay_data.get(entry_key, {})
        for group_key in ("pitcher", "batter"):
            for player in entry.get(group_key, []):
                pcode = str(player.get("pcode", "")).strip()
                name = str(player.get("name", "")).strip()
                if pcode and name:
                    player_map[pcode] = name
    return player_map

def fetch_player_name_from_kbo(player_code):
    """엔트리에 없는 선수 코드는 KBO 선수 페이지에서 보강합니다."""
    player_code = str(player_code or "").strip()
    if not player_code:
        return ""
    if player_code in PLAYER_NAME_CACHE:
        return PLAYER_NAME_CACHE[player_code]

    url = f"https://www.koreabaseball.com/Record/Player/PitcherDetail/Basic.aspx?playerId={player_code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        text = html.unescape(re.sub(r"<[^>]+>", " ", response.text))
        match = re.search(r"선수명:\s*([^\s]+)", text)
        name = match.group(1).strip() if match else ""
    except Exception as e:
        logger.warning(f"⚠️ 투수 코드 {player_code} 이름 조회 실패: {e}")
        name = ""

    PLAYER_NAME_CACHE[player_code] = name
    return name

def get_pitcher_name(text_option, player_map):
    """투구별 textOption의 currentGameState.pitcher 코드로 투수 이름을 찾습니다."""
    game_state = text_option.get("currentGameState", {}) if text_option else {}
    pitcher_code = str(game_state.get("pitcher", "")).strip()

    if pitcher_code in player_map:
        return player_map[pitcher_code]

    name = fetch_player_name_from_kbo(pitcher_code)
    if name:
        player_map[pitcher_code] = name
        return name

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
            
        text_relay_data = data["result"].get("textRelayData", {})
        player_map = build_player_name_map(text_relay_data)
        relays = text_relay_data.get("textRelays", [])
        inning_pitch_count = 0
        
        for relay in reversed(relays):
            inn = relay.get("inn")
            home_away = "Home" if relay.get("homeOrAway") == "1" else "Away"
            b_name = get_batter_name_verbose(relay)
            log_text = " ".join([opt.get("text", "") for opt in relay.get("textOptions", []) if opt.get("type") == 13])
            
            pts_options = relay.get("ptsOptions", [])
            for i, pts in enumerate(pts_options):
                pitch_id = pts.get("pitchId")
                text_opt = next((opt for opt in relay.get("textOptions", []) if opt.get("ptsPitchId") == pitch_id), {})
                p_name = get_pitcher_name(text_opt, player_map) # 💡 투구별 투수명 추출
                
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
        os.makedirs(os.path.dirname(SAVE_PATH), exist_ok=True)
        df.to_csv(SAVE_PATH, index=False, encoding="utf-8-sig")
        
        print("\n" + "=" * 30)
        logger.info(f"💾 저장이 완료되었습니다!")
        logger.info(f"💾 경로: {SAVE_PATH}")
        logger.info(f"📊 최종 수집 데이터: {len(df)}행")
        print("=" * 30 + "\n")
    else:
        logger.error("🛑 추출할 수 있는 데이터가 없습니다.")

if __name__ == "__main__":
    extract_full_game_data(TARGET_GAME_ID)
