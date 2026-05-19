import time
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

CRAWL_SEASONS = [2021, 2022, 2023, 2024]
CRAWL_ID = ['67893']  # 예시 선수 ID
FILE_PREFIX = "data/kbo_hitter_daily"

def stable_kbo_crawler(player_id, years):
    options = webdriver.ChromeOptions()
    # 로그 노이즈 제거
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    total_data = []
    # 페이지 주소 확인 (HitterDetail/Daily.aspx)
    base_url = f"https://www.koreabaseball.com/Record/Player/HitterDetail/Daily.aspx?playerId={player_id}"
    
    try:
        driver.get(base_url)
        wait = WebDriverWait(driver, 15) # 대기 시간을 15초로 늘림

        for year in years:
            try:
                print(f"\n>>> {year} 시즌 데이터 시도 중...")
                
                # 1. 연도 드롭다운이 나타날 때까지 대기
                # ID가 'cphContents_cphContents_cphContents_ddlYear' 형태일 수 있음
                # 따라서 ID 끝자리만 매칭되는 CSS Selector 사용
                dropdown_selector = "select[id*='ddlYear']" 
                dropdown_element = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, dropdown_selector))
                )
                
                # 2. 연도 선택
                select = Select(dropdown_element)
                select.select_by_value(str(year))
                
                # 3. 페이지 갱신(PostBack) 대기 [파일: 크롤링 코드 작성 가이드]
                # 데이터가 바뀔 때 나타나는 로딩 인디케이터나 테이블 변화 대기
                time.sleep(3) 
                
                # 4. BeautifulSoup으로 파싱
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                daily_tables = soup.select('.tbl-type02')
                
                current_year_count = 0
                for table in daily_tables:
                    rows = table.find('tbody').find_all('tr')
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) == 18:
                            entry = [cell.text.strip().replace('-', '0') for cell in cells]
                            # 연도 정보를 첫 컬럼에 추가하여 분석 용이성 확보
                            total_data.append([year] + entry)
                            current_year_count += 1
                
                print(f"   성공: {year}시즌 {current_year_count}개의 행 수집됨")

            except Exception as e:
                print(f"   에러: {year} 시즌 처리 중 문제 발생 - {str(e)[:100]}")
                continue

    finally:
        driver.quit()

    # 데이터프레임 구성
    columns = ['Season', 'Date', 'Opponent', 'AVG1', 'PA', 'AB', 'R', 'H', '2B', '3B', 'HR', 'RBI', 'SB', 'CS', 'BB', 'HBP', 'SO', 'GDP', 'AVG2']
    return pd.DataFrame(total_data, columns=columns)

if __name__ == "__main__":
    for i in CRAWL_ID:
        df = stable_kbo_crawler(i, CRAWL_SEASONS)
        if not df.empty:
            print("\n[최종 수집 결과]")
            print(df.groupby('Season').size())
            
            # CSV 파일로 저장
            filename = f"{FILE_PREFIX}_{i}.csv"
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"\n파일 저장 완료: {filename}")
        else:
            print("\n수집된 데이터가 없습니다. 선수 ID나 네트워크 상태를 확인하세요.")