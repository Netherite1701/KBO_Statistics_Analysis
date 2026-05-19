import json
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# 1. 모든 PTS 투구 리스트를 완벽하게 통합하는 파싱 함수
def load_pts_data():
    file_path = "Simulation/pts_page.txt"
    if os.path.exists(file_path):
        print(f"'{file_path}' 파일을 추출합니다...")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        result_data = data.get('result', {})
        all_pitches = []

        # 루트 레벨(result -> ptsOptions)에 한꺼번에 묶여 있는 리스트 확인
        if 'ptsOptions' in result_data:
            all_pitches = result_data['ptsOptions']
            print("구조 타입 A: 최상위 result에서 ptsOptions 리스트를 발견했습니다.")
        
        # textRelayData 직속에 묶여 있는 리스트 확인
        elif 'textRelayData' in result_data and 'ptsOptions' in result_data['textRelayData']:
            all_pitches = result_data['textRelayData']['ptsOptions']
            print("구조 타입 B: textRelayData 내부에서 ptsOptions 리스트를 발견했습니다.")
            
        # 중계 스트리밍 문자 마다 파편화되어 있는 경우 취합 (백업 로직)
        else:
            print("구조 타입 C: textRelays 문자 스트리밍에서 투구 데이터를 수집합니다.")
            text_relays = result_data.get('textRelayData', {}).get('textRelays', [])
            for relay in text_relays:
                pts_list = relay.get('ptsOptions', [])
                for pitch in pts_list:
                    all_pitches.append(pitch)

        if all_pitches:
            df = pd.DataFrame(all_pitches)
            # 중복 데이터가 쌓여있을 경우 제거 (pitchId 기준)
            if 'pitchId' in df.columns:
                df = df.drop_duplicates(subset=['pitchId']).reset_index(drop=True)
            print(f"총 {len(df)}개의 유니크한 투구 궤적 데이터를 확보했습니다!")
            return df
        else:
            print("⚠️ 모든 경로에서 투구 데이터를 찾지 못했습니다. 샘플로 전환합니다.")
            
    # 파일이 없거나 파싱 실패 시 예시용 안전 데이터
    sample_data = {
        "pitchId": "sample_fast", "crossPlateX": 0.56, "topSz": 3.48, "bottomSz": 1.69,
        "x0": 1.82, "y0": 50.0, "z0": 5.58, "vx0": -6.73, "vy0": -130.0, "vz0": -7.14,
        "ax": 17.93, "ay": 21.22, "az": -12.06, "stuff": "직구"
    }
    return pd.DataFrame([sample_data])

# 2. 물리 공식을 이용한 3D 궤적 계산 함수
def calculate_trajectory(row, num_points=100):
    x0, y0, z0 = float(row['x0']), float(row['y0']), float(row['z0'])
    vx0, vy0, vz0 = float(row['vx0']), float(row['vy0']), float(row['vz0'])
    ax, ay, az = float(row['ax']), float(row['ay']), float(row['az'])
    
    # 등가속도 공식을 이용하여 y=0(홈플레이트) 도달 시간 계산
    a_quad = 0.5 * ay
    b_quad = vy0
    c_quad = y0
    
    t_final = (-b_quad - np.sqrt(b_quad**2 - 4*a_quad*c_quad)) / (2*a_quad)
    t = np.linspace(0, t_final, num_points)
    
    x_coords = x0 + vx0 * t + 0.5 * ax * t**2
    y_coords = y0 + vy0 * t + 0.5 * ay * t**2
    z_coords = z0 + vz0 * t + 0.5 * az * t**2
    
    return x_coords, y_coords, z_coords

# 3. 3D 공간 시각화 함수
def plot_3d_trajectory(df):
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection='3d')
    
    ax.set_xlim(-4, 4)
    ax.set_ylim(-2, 55)
    ax.set_zlim(0, 7)
    
    # 여러 구의 색상이 겹치지 않도록 컬러맵 적용
    cmap = plt.get_cmap('Set1')
    
    for idx, row in df.iterrows():
        try:
            x, y, z = calculate_trajectory(row)
            color = cmap(idx % 9)
            
            stuff_type = row.get('stuff', 'Unknown')
            speed_val = row.get('speed', '??')
            
            # 궤적 곡선 그리기
            ax.plot(x, y, z, color=color, linewidth=2, alpha=0.8,
                    label=f"[{idx+1}구] {stuff_type} ({speed_val}km)")
            
            # 투수 릴리스 포인트 & 홈플레이트 도달점 표시
            ax.scatter(x[0], y[0], z[0], color='black', s=15)
            ax.scatter(x[-1], y[-1], z[-1], color=color, s=50, edgecolors='black', zorder=15)
            ax.text(x[-1], y[-1] - 1.2, z[-1] + 0.15, str(idx+1), color='black', weight='bold')
        except Exception as e:
            continue

    # --- 홈플레이트 및 스트라이크 존 그리드 고정 ---
    hp_x = [-0.708, 0.708, 0.708, 0, -0.708]
    hp_y = [0, 0, -0.708, -1.416, -0.708]
    hp_z = [0, 0, 0, 0, 0]
    ax.plot(hp_x, hp_y, hp_z, color='dimgray', linewidth=2)
    
    try:
        sz_top = float(df.iloc[0]['topSz'])
        sz_bot = float(df.iloc[0]['bottomSz'])
    except:
        sz_top, sz_bot = 3.3, 1.6
        
    sz_x = [-0.708, 0.708, 0.708, -0.708, -0.708]
    sz_y = [0, 0, 0, 0, 0]
    sz_z = [sz_bot, sz_bot, sz_top, sz_top, sz_bot]
    ax.plot(sz_x, sz_y, sz_z, color='black', linestyle='--', linewidth=2, label='Strike Zone')

    # 그래프 텍스트 서식
    ax.set_title("KBO PTS Complete 3D Pitch Simulator", fontsize=15, pad=15, weight='bold')
    ax.set_xlabel("Horizontal (X - Left/Right)")
    ax.set_ylabel("Distance (Y - Mound to Home)")
    ax.set_zlabel("Height (Z)")
    
    ax.view_init(elev=18, azim=-125) 
    ax.legend(loc='upper left', fontsize=9)
    
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    pts_df = load_pts_data()
    plot_3d_trajectory(pts_df)