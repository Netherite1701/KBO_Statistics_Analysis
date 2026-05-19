from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import time

def get_kbo_data_with_browser(player_id):
    # 크롬 드라이버 설정 (창이 뜨게 설정)
    options = webdriver.ChromeOptions()
    # options.add_argument('--headless') # 이 줄을 주석 처리하면 창이 보입니다!
    
    driver = webdriver.Chrome(options=options)
    url = f"https://www.koreabaseball.com/Record/Player/HitterDetail/Daily.aspx?playerId={player_id}"
    
    try:
        print(f"[STEP 1] 브라우저 오픈 및 페이지 접속 시도: {url}")
        driver.get(url)
        
        # 테이블이 로딩될 때까지 최대 10초 대기 (Verbose 에러 처리)
        print("[STEP 2] 데이터 테이블 로딩 대기 중...")
        wait = WebDriverWait(driver, 10)
        table_present = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "tEx")))
        
        print("[SUCCESS] 테이블 발견! 데이터 추출을 시작합니다.")
        
        # 테이블 행들 가져오기
        rows = driver.find_elements(By.CSS_SELECTOR, "table.tEx.confirm tbody tr")
        
        data = []
        for i, row in enumerate(rows):
            # 월별 구분 행(예: 04월)은 td가 1개뿐이므로 제외
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) > 1:
                data.append([col.text for col in cols])
            else:
                print(f"[INFO] {row.text} 행은 요약 데이터이므로 건너뜁니다.")

        columns = ['Date', 'Opponent', 'Result', 'AVG1', 'AB', 'R', 'H', '2B', '3B', 'HR', 'RBI', 'SB', 'CS', 'BB', 'HBP', 'SO', 'GDP', 'AVG2']
        df = pd.DataFrame(data, columns=columns)
        return df

    except Exception as e:
        print(f"[CRITICAL ERROR] 작업 중단!")
        print(f"상세 원인: {e}")
        # 현재 브라우저의 상태를 찍어서 보여줄 수도 있음
        return None
        
    finally:
        print("[FINISH] 5초 후 브라우저를 닫습니다.")
        time.sleep(5)
        driver.quit()

# 실행
df = get_kbo_data_with_browser('67893')