import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import sys

def get_kbo_daily_record_verbose(player_id, year='2024'):
    url = f"https://www.koreabaseball.com/Record/Player/HitterDetail/Daily.aspx?playerId={player_id}"
    # https://www.koreabaseball.com/Record/Player/HitterDetail/Daily.aspx?playerId=67893
    # KBO 페이지는 연도 선택 시 POST 또는 별도 처리가 필요할 수 있으나, 
    # 기본 페이지는 현재 시즌 정보를 담고 있습니다.
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        print(f"[INFO] 데이터 수집 시작: Player ID {player_id} (URL: {url})")
        response = requests.get(url, headers=headers, timeout=10)
        
        # 1. HTTP 상태 코드 확인
        response.raise_for_status() 
        
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] HTTP 에러 발생: {e.response.status_code} - 페이지를 찾을 수 없거나 접근이 거부되었습니다.")
        return None
    except requests.exceptions.ConnectionError:
        print(f"[ERROR] 연결 에러: 인터넷 연결을 확인하거나 KBO 서버 상태를 점검하세요.")
        return None
    except requests.exceptions.Timeout:
        print(f"[ERROR] 타임아웃: 서버 응답이 너무 느립니다.")
        return None
    except Exception as e:
        print(f"[ERROR] 알 수 없는 연결 오류: {e}")
        return None
    
    print(response.text[:500])  # 응답의 처음 500자 출력하여 HTML 구조 확인

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 2. 데이터 테이블 존재 여부 확인
        # KBO 공식 홈페이지의 일별기록 테이블 클래스는 'tEx'를 주로 사용합니다.
        table = soup.select_one('table.tEx.confirm') 
        
        if not table:
            print(f"[WARNING] 데이터를 찾을 수 없습니다. 선수의 일별 기록이 없거나 Player ID({player_id})가 유효하지 않을 수 있습니다.")
            return None

        rows = table.find_all('tr')
        data = []
        
        # 3. 행 데이터 추출 및 검증
        for i, row in enumerate(rows[1:], start=1):
            cols = row.find_all('td')
            if not cols:
                continue
            
            row_data = [ele.text.strip() for ele in cols]
            
            # 예상되는 컬럼 수(18개)와 일치하는지 확인
            if len(row_data) != 18:
                print(f"[DEBUG] {i}행에서 비정상적인 데이터 구조 발견: {row_data}")
                continue
                
            data.append(row_data)

        if not data:
            print("[ERROR] 테이블 내에 유효한 행 데이터가 존재하지 않습니다.")
            return None

        # 4. DataFrame 생성 및 후속 처리
        columns = ['Date', 'Opponent', 'Result', 'AVG1', 'AB', 'R', 'H', '2B', '3B', 'HR', 'RBI', 'SB', 'CS', 'BB', 'HBP', 'SO', 'GDP', 'AVG2']
        df = pd.DataFrame(data, columns=columns)
        
        print(f"[SUCCESS] {len(df)}개의 경기 기록을 성공적으로 가져왔습니다.")
        return df

    except Exception as e:
        print(f"[CRITICAL] 파싱 중 치명적 오류 발생: {e}")
        # 상세 에러 위치 추적을 위해 traceback 사용 가능
        import traceback
        traceback.print_exc()
        return None

# 실행 예시
player_df = get_kbo_daily_record_verbose('67893') # 이정후 선수 예시