import os
import re
import json
import requests

def download_naver_relay_data(input_url, target_folder="pitch-data"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    print("=" * 60)
    print("📡 네이버 스포츠 원본 데이터 다운로더 시작")
    print("=" * 60)
    
    # 1. URL에서 Game ID 추출 (예: 20260516HTSS02026)
    game_id_match = re.search(r'([0-9]{8}[A-Z]{4,8}[0-9]{1,2})', input_url)
    if not game_id_match:
        print("❌ 에러: URL에서 경기 Game ID를 찾을 수 없습니다. 주소를 확인해주세요.")
        return
    
    game_id = game_id_match.group(1)
    print(f"🎯 분석된 경기 ID: {game_id}")
    
    # 2. 데이터를 저장할 'pitch-data' 폴더가 없으면 자동으로 생성
    if not os.path.exists(target_folder):
        os.makedirs(target_folder)
        print(f"📂 [{target_folder}] 폴더가 없어서 새로 생성했습니다.")
        
    # 3. 파일 저장 경로 정의 (예: pitch-data/20260516HTSS02026.json)
    # 네이버 스포츠 API 결과는 순수 HTML이 아니라 JSON이므로 .json으로 저장하는 것이 분석에 훨씬 유리합니다!
    output_filepath = os.path.join(target_folder, f"{game_id}.json")
    
    # 4. 네이버 웹사이트(API)에 자동 접속 및 요청
    print(f"🌐 네이버 서버 접속 중... ({input_url})")
    try:
        response = requests.get(input_url, headers=headers, timeout=10)
        print(f"🤖 서버 응답 상태 코드: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ 에러: 서버 접속 실패 (상태 코드: {response.status_code})")
            return
            
        # 5. 응답받은 데이터를 파일로 저장
        # JSON 포맷팅을 이쁘게 해서 사람이 눈으로 읽기 편하게 저장합니다.
        raw_json_data = response.json()
        
        with open(output_filepath, "w", encoding="utf-8") as f:
            json.dump(raw_json_data, f, indent=4, ensure_ascii=False)
            
        print("=" * 60)
        print(f"✅ 다운로드 성공!")
        print(f"💾 저장된 원본 파일 경로: {output_filepath}")
        print("=" * 60)
        print("💡 이제 이 폴더에 쌓인 파일들을 가지고 안전하게 투구 데이터를 추출하면 됩니다!")

    except Exception as e:
        print(f"🚨 다운로드 중 예상치 못한 오류 발생: {e}")

if __name__ == "__main__":
    # 요청하신 네이버 하이라이트/일반 문자중계 주소
    naver_url = "https://api-gw.sports.naver.com/schedule/games/20260516HTSS02026/relay/highLight"
    
    # 실행
    download_naver_relay_data(naver_url)