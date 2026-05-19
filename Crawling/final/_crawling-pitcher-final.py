import time
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# 설정 값
CRAWL_SEASONS = [2021, 2022, 2023, 2024]
CRAWL_ID = ['51516']  # 수집할 투수의 ID
FILE_PREFIX = "data/kbo_pitcher_daily"

def stable_kbo_pitcher_crawler(player_id, years):
    options = webdriver.ChromeOptions()
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    # options.add_argument('--headless') # 창을 띄우지 않으려면 주석 해제
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    total_data = []
    # 투수 상세 페이지 주소 (PitcherDetail/Daily.aspx)
    base_url = f"https://www.koreabaseball.com/Record/Player/PitcherDetail/Daily.aspx?playerId={player_id}"
    
    try:
        driver.get(base_url)
        wait = WebDriverWait(driver, 15)

        for year in years:
            try:
                print(f"\n>>> {year} 시즌 투수 데이터 시도 중...")
                
                # 1. 연도 드롭다운 대기 및 선택
                dropdown_selector = "select[id*='ddlYear']" 
                dropdown_element = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, dropdown_selector))
                )
                
                select = Select(dropdown_element)
                select.select_by_value(str(year))
                
                # 2. 페이지 갱신 대기 (PostBack 처리 시간)
                time.sleep(3) 
                
                # 3. BeautifulSoup으로 파싱
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                # 투수 테이블 선택
                daily_tables = soup.select('.tbl-type02')
                
                current_year_count = 0
                for table in daily_tables:
                    # tbody가 없는 경우를 대비해 예외 처리
                    tbody = table.find('tbody')
                    if not tbody: continue
                    
                    rows = tbody.find_all('tr')
                    for row in rows:
                        cells = row.find_all('td')
                        # 투수 데이터는 제공해주신 HTML 기준 15개의 컬럼을 가짐
                        if len(cells) == 15:
                            entry = [cell.text.strip().replace('-', '0') for cell in cells]
                            # 시즌(Year) 정보를 첫 컬럼에 추가
                            total_data.append([year] + entry)
                            current_year_count += 1
                
                print(f"   성공: {year}시즌 {current_year_count}개의 투구 기록 수집됨")

            except Exception as e:
                print(f"   에러: {year} 시즌 처리 중 문제 발생 - {str(e)[:100]}")
                continue

    finally:
        driver.quit()

    # 데이터프레임 컬럼 설정 (제공해주신 HTML 구조 기준)
    columns = [
        'Season', 'Date', 'Opponent', 'Appearance', 'Result', 
        'ERA1', 'TBF', 'IP', 'H', 'HR', 'BB', 'HBP', 'SO', 'R', 'ER', 'ERA2'
    ]
    
    return pd.DataFrame(total_data, columns=columns)

if __name__ == "__main__":
    for i in CRAWL_ID:
        df = stable_kbo_pitcher_crawler(i, CRAWL_SEASONS)
        
        if not df.empty:
            print("\n[최종 수집 결과]")
            print(df.groupby('Season').size())
            
            # CSV 파일로 저장
            filename = f"{FILE_PREFIX}_{i}.csv"
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"\n파일 저장 완료: {filename}")
        else:
            print("\n수집된 데이터가 없습니다. 선수 ID나 네트워크 상태를 확인하세요.")