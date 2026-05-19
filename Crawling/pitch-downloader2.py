import os
import json
import requests
import pandas as pd


def fetch_kbo_pitch_data(game_id, inning):
    """네이버 스포츠 GW API에서 특정 경기 및 이닝의 투구 위치/구종 데이터를 가져옵니다."""
    url = f"https://api-gw.sports.naver.com/schedule/games/{game_id}/relay"
    params = {"inning": inning}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        if response.status_code != 200:
            print(
                f"❌ 데이터를 가져오지 못했습니다. (상태 코드: {response.status_code})"
            )
            return None

        data = response.json()
        return data

    except Exception as e:
        print(f"❌ 요청 중 오류 발생: {e}")
        return None


def parse_pitch_data(json_data):
    """중첩된 네이버 JSON 구조에서 투구 트래킹(PTS) 및 타석 데이터를 추출합니다."""
    if not json_data or "result" not in json_data:
        return pd.DataFrame()

    result_data = json_data["result"]
    text_relay_data = result_data.get("textRelayData", {})
    text_relays = text_relay_data.get("textRelays", [])

    pitch_records = []

    # 각 타석별 릴레이 루프 순회
    for relay in text_relays:
        # 타석 기본 정보
        inning = relay.get("inn")
        home_away = "Home" if relay.get("homeOrAway") == "1" else "Away"

        # ptsOptions(투구 트래킹 데이터 리스트) 추출
        pts_options = relay.get("ptsOptions", [])

        # 각 투구별 상세 텍스트 옵션 정보 추출 (구종, 구속 매핑용)
        text_options = relay.get("textOptions", [])

        # 1개의 타석 안에서 일어난 투구들을 순회하며 데이터 결합
        for i, pts in enumerate(pts_options):
            pitch_id = pts.get("pitchId")

            # 동일한 pitchId를 가진 텍스트 옵션을 찾아 구종(stuff)과 구속(speed) 추출
            stuff = "알수없음"
            speed = "0"
            pitch_num = i + 1

            for opt in text_options:
                if opt.get("ptsPitchId") == pitch_id:
                    stuff = opt.get("stuff", "알수없음")
                    speed = opt.get("speed", "0")
                    pitch_num = opt.get("pitchNum", pitch_num)
                    break

            # 딕셔너리로 행(Row) 데이터 구성
            record = {
                "이닝": inning,
                "공격팀구분": home_away,
                "투구ID": pitch_id,
                "타석내투구순서": pitch_num,
                "구종(stuff)": stuff,
                "구속(speed)": float(speed) if speed else 0.0,
                "좌우좌표(crossPlateX)": pts.get("crossPlateX"),
                "상하좌표(crossPlateY)": pts.get("crossPlateY"),
                "초속X(vx0)": pts.get("vx0"),
                "초속Y(vy0)": pts.get("vy0"),
                "초속Z(vz0)": pts.get("vz0"),
                "가속도X(ax)": pts.get("ax"),
                "가속도Y(ay)": pts.get("ay"),
                "가속도Z(az)": pts.get("az"),
                "S존상단(topSz)": pts.get("topSz"),
                "S존하단(bottomSz)": pts.get("bottomSz"),
                "타자타석방향": pts.get("stance"),
            }
            pitch_records.append(record)

    # 데이터프레임 변환
    df = pd.DataFrame(pitch_records)
    return df


# --- 프로그램 가동 예시 ---
if __name__ == "__main__":
    # 1. 대상 경기 및 이닝 설정
    TARGET_GAME = "20260506HHHT02026"  # 한화 vs KIA 경기 ID
    TARGET_INNING = 4  # 4이닝

    print(
        f"⚾ 네이버 KBO PTS 수집기 가동 [{TARGET_GAME} - {TARGET_INNING}이닝]"
    )

    # 2. 실시간 GW API 호출
    raw_json = fetch_kbo_pitch_data(TARGET_GAME, TARGET_INNING)

    if raw_json:
        # 3. 중첩 JSON 파싱 및 구조 정제
        df_pitch = parse_pitch_data(raw_json)

        if not df_pitch.empty:
            # 4. 콘솔 출력 및 CSV 저장
            print("\n📊 [수집 완료된 투구 위치 데이터 일부]")
            print(
                df_pitch[
                    [
                        "이닝",
                        "공격팀구분",
                        "타석내투구순서",
                        "구종(stuff)",
                        "구속(speed)",
                        "좌우좌표(crossPlateX)",
                    ]
                ].head()
            )

            # 파일 저장
            file_name = f"pitch_data_{TARGET_GAME}_inn{TARGET_INNING}.csv"
            df_pitch.to_csv(file_name, index=False, encoding="utf-8-sig")
            print(f"\n💾 데이터가 성공적으로 저장되었습니다! 파일명: {file_name}")
        else:
            print("⚠️ 해당 이닝에 추출 가능한 투구 데이터(PTS)가 없습니다.")