import json
import requests
import pandas as pd

def extract_and_save_pts(url, output_filename="kbo_pts_data.csv"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    print(f"🔄 데이터 수집을 시작합니다... \nURL: {url}")
    
    try:
        # 1. 네이버 API 데이터 호출
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ 데이터 가져오기 실패 (상태 코드: {response.status_code})")
            return
        
        data = response.json()
        
        # 2. 중첩 구조 내부의 ptsOptions 경로 검증 및 접근
        if 'result' not in data or 'ptsOptions' not in data['result']:
            print("⚠️ 구조 분석 실패: 데이터 내부에 'ptsOptions' 배열이 존재하지 않습니다.")
            return
            
        pts_list = data['result']['ptsOptions']
        
        if not pts_list:
            print("⚠️ 'ptsOptions' 내부에 투구 데이터가 텅 비어 있습니다.")
            return
            
        # 3. Pandas를 이용해 중첩된 JSON 리스트를 평탄화(Flatten)하여 데이터프레임 변환
        df = pd.json_normalize(pts_list)
        
        # 4. 분석에 필요한 핵심 컬럼만 순서대로 정렬 (누락 대비 방어 코드 포함)
        target_columns = [
            'pitchId', 'inn', 'ballcount', 'crossPlateX', 'crossPlateY', 
            'topSz', 'bottomSz', 'stance', 'vx0', 'vy0', 'vz0', 'ax', 'ay', 'az'
        ]
        available_columns = [col for col in target_columns if col in df.columns]
        df = df[available_columns]
        
        # 5. 한글 깨짐 방지(utf-8-sig)를 적용하여 CSV 파일로 저장
        df.to_csv(output_filename, index=False, encoding='utf-8-sig')
        
        print("-" * 50)
        print(f"✅ 추출 성공! 총 {len(df)}개의 투구 데이터가 정상 수집되었습니다.")
        print(f"💾 파일 저장 완료: {output_filename}")
        print("-" * 50)
        
        # 샘플 출력
        print("\n[추출된 데이터 상위 3개 미리보기]")
        print(df.head(3).to_string())

    except Exception as e:
        print(f"🚨 프로그램 실행 중 에러 발생: {e}")

# --- 실행부 ---
if __name__ == "__main__":
    # 요청하신 정확한 네이버 API 주소 타겟팅
    target_url = "https://api-gw.sports.naver.com/schedule/games/20260516HTSS02026/relay/highLight"
    
    # 저장될 CSV 파일명 설정
    output_file = "KBO_PTS_20260516.csv"
    
    extract_and_save_pts(target_url, output_file)