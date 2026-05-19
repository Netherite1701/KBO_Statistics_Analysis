import requests
import pandas as pd
import json

def crawl_naver_pts_data(game_id="20260516HTSS02026"):
    # 1. 네이버 스포츠 API Gateway 주소 생성
    url = f"https://api-gw.sports.naver.com/schedule/games/{game_id}/relay/highLight"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    
    print(f"📡 네이버 PTS API 요청 중... (Game ID: {game_id})")
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"❌ 데이터 요청 실패 (응답 코드: {response.status_code})")
        return None
        
    # 2. JSON 데이터 파싱
    try:
        data = response.json()
    except json.JSONDecodeError:
        print("❌ JSON 파싱 에러: 응답 형식이 올바르지 않습니다.")
        return None

    # 3. 투구 트래킹 데이터(ptsOptions)만 추출하여 리스트에 적재
    # API 내부 트리 구조(예: result나 주석 탭 리스트 순회)에 따라 경로 설정이 필요합니다.
    # 아래는 일반적인 네이버 스포츠 릴레이 데이터 포맷에 맞춘 예시 파싱 루프입니다.
    
    all_pitches = []
    
    # 예시: 응답 데이터의 하이라이트/타석 텍스트 리스트나 별도 탭 내 구조 탐색
    # (실제 API 전체 JSON 구조에 'result'나 'records'가 있다면 맞춰서 접근)
    records = data.get('result', data).get('relayList', []) 
    
    for record in records:
        # 각 타석 정보 내에 ptsOptions 또는 투구 데이터가 포함되어 있는지 확인
        pts_options = record.get('ptsOptions', [])
        
        # 만약 찾으신 데이터 구조가 특정 리스트 아래에 바로 있다면 해당 변수를 루프 돌립니다.
        for pitch in pts_options:
            pitch_info = {
                "pitchId": pitch.get("pitchId"),
                "inn": pitch.get("inn"),
                "ballcount": pitch.get("ballcount"),
                "crossPlateX": pitch.get("crossPlateX"),
                "crossPlateY": pitch.get("crossPlateY"),
                "topSz": pitch.get("topSz"),
                "bottomSz": pitch.get("bottomSz"),
                "vy0": pitch.get("vy0"),
                "vz0": pitch.get("vz0"),
                "vx0": pitch.get("vx0"),
                "x0": pitch.get("x0"),
                "y0": pitch.get("y0"),
                "z0": pitch.get("z0"),
                "ax": pitch.get("ax"),
                "ay": pitch.get("ay"),
                "az": pitch.get("az"),
                "stance": pitch.get("stance")
            }
            all_pitches.append(pitch_info)
            
    # 4. 판다스 데이터프레임으로 생성
    df_pts = pd.DataFrame(all_pitches)
    print(f"✅ 수집 완료: 총 {len(df_pts)}개의 투구 데이터 확보")
    return df_pts

# 실행 테스트
if __name__ == "__main__":
    df = crawl_naver_pts_data("20260516HTSS02026")
    if df is not None and not df.empty:
        print(df.head())
        # CSV 파일로 보관 (엑셀 한글 깨짐 방지 utf-8-sig)
        df.to_csv("kbo_pts_tracking_data.csv", index=False, encoding="utf-8-sig")