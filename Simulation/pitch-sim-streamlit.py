import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

# 캐시 초기화 및 페이지 설정
st.cache_data.clear()
st.set_page_config(page_title="KBO PTS Simulator V2", layout="wide")

st.title("⚾ KBO PTS Simulator V2 (Pure Physics Engine)")
st.markdown("모든 물리 공식과 3D 렌더링을 밑바닥부터 재설계한 클린 버전입니다.")

# ==========================================
# 1. 파일 로드 및 데이터 전처리
# ==========================================
file_path = st.text_input("CSV 파일 경로를 입력하세요:", value=r"C:\dev\Python_Projects\KBO_Stat_Analysis\data\game-data\KBO_GameData_20260506HHHT02026.csv")

if not os.path.exists(file_path):
    st.error(f"❌ 파일을 찾을 수 없습니다: {file_path}")
    st.stop()

try:
    df = pd.read_csv(file_path, encoding='utf-8')
except:
    df = pd.read_csv(file_path, encoding='cp949')

# 타석 단위 그룹핑 로직 (구수 리셋 기준)
at_bat_ids = []
current_ab = 0
prev_seq = 999
for _, row in df.iterrows():
    seq = row.get('상대타석내구수', 999)
    if seq <= prev_seq:
        current_ab += 1
    at_bat_ids.append(current_ab)
    prev_seq = seq
df['AtBat_ID'] = at_bat_ids

# ==========================================
# 2. 순수 트랙맨 물리 엔진 (Kinematic Engine)
# ==========================================
def calculate_true_trajectory(row, num_points=70):
    try:
        # 1. 초기 속도 및 가속도 (단위: 피트/초, 피트/초^2)
        vx0 = float(row.get('초속X(vx0)', 0))
        vy0 = float(row.get('초속Y(vy0)', 0))
        vz0 = float(row.get('초속Z(vz0)', 0))
        
        ax = float(row.get('가속도X(ax)', 0))
        ay = float(row.get('가속도Y(ay)', 0))
        az = float(row.get('가속도Z(az)', 0))
        
        # 2. 타겟 위치 (Y는 깊이, X는 좌우)
        y_target = float(row.get('상하위치(crossPlateY)', 0.7083)) 
        x_target = float(row.get('좌우위치(crossPlateX)', 0))
        
        # 3. 초기 투구 위치 (y0는 기본 50피트)
        y0 = 50.0 
        
        # CSV에 초기 높이(z0)가 누락되어 있어 임의값(5.8피트) 적용. 
        # (이 값이 원본 데이터와 다르면 궤적이 전체적으로 위/아래로 이동해 보입니다)
        z0 = 5.8 

        # 4. 플레이트 도달 체공 시간(t) 정밀 계산 (2차 방정식 근의 공식)
        a_coef = 0.5 * ay
        b_coef = vy0
        c_coef = y0 - y_target
        
        det = b_coef**2 - 4 * a_coef * c_coef
        if det < 0: return None, None, None, None
        t_flight = (-b_coef - np.sqrt(det)) / (2 * a_coef)
        
        # 5. 초기 X축 릴리스 포인트 수학적 역산
        x0 = x_target - (vx0 * t_flight + 0.5 * ax * t_flight**2)
        
        # 6. 시간에 따른 X, Y, Z 공간 배열 생성
        t_arr = np.linspace(0, t_flight, num_points)
        x_path = x0 + vx0 * t_arr + 0.5 * ax * t_arr**2
        y_path = y0 + vy0 * t_arr + 0.5 * ay * t_arr**2
        z_path = z0 + vz0 * t_arr + 0.5 * az * t_arr**2
        
        final_z_height = z_path[-1] # 플레이트를 통과하는 순간의 정확한 높이(Z)
        
        return x_path, y_path, z_path, final_z_height
    except Exception as e:
        return None, None, None, None

# ==========================================
# 3. 사이드바 필터 컨트롤
# ==========================================
st.sidebar.header("🔍 타석 선택기")
innings = sorted(df['이닝'].dropna().unique())
sel_inn = st.sidebar.selectbox("1. 이닝", innings)

df_inn = df[df['이닝'] == sel_inn]
sel_half = st.sidebar.selectbox("2. 초/말", sorted(df_inn['공격팀구분'].dropna().unique()))

df_half = df_inn[df_inn['공격팀구분'] == sel_half]
if df_half.empty:
    st.warning("데이터가 없습니다.")
    st.stop()

# 타석 선택
ab_list = df_half.groupby('AtBat_ID').first().reset_index()
ab_options = {r['AtBat_ID']: f"타자: {r.get('타자명', '알수없음')}" for _, r in ab_list.iterrows()}
sel_ab_id = st.sidebar.selectbox("3. 타석 선택", options=list(ab_options.keys()), format_func=lambda x: ab_options[x])

df_active = df_half[df_half['AtBat_ID'] == sel_ab_id].reset_index(drop=True)

# ==========================================
# 4. 무결점 3D Plotly 렌더링
# ==========================================
fig = go.Figure()
colors = ['#FF4B4B', '#0068C9', '#29B09D', '#FFD166', '#781C1C', '#06D6A0', '#118AB2']
result_logs = []

for idx, row in df_active.iterrows():
    seq = row.get('상대타석내구수', idx+1)
    stuff = row.get('구종(stuff)', 'Unknown')
    speed = row.get('구속(speed)', 0)
    
    x, y, z, final_z = calculate_true_trajectory(row)
    
    if x is not None:
        c = colors[idx % len(colors)]
        label = f"{int(seq)}구: {stuff} ({speed}km/h)"
        
        # 궤적 선
        fig.add_trace(go.Scatter3d(
            x=x, y=y, z=z, mode='lines',
            line=dict(color=c, width=5), name=label,
            hovertemplate=f"{label}<br>Y(거리): %{{y:.2f}}ft<br>Z(높이): %{{z:.2f}}ft<extra></extra>"
        ))
        
        # 종착점 마커
        fig.add_trace(go.Scatter3d(
            x=[x[-1]], y=[y[-1]], z=[z[-1]], mode='markers',
            marker=dict(size=8, color=c, line=dict(color='black', width=1)),
            showlegend=False, hoverinfo='skip'
        ))
        
        # 로그 저장
        result_logs.append({
            "구수": seq, "구종": stuff, "구속(km/h)": speed,
            "결과 좌우(X)": round(x[-1], 2),
            "결과 높이(Z)": round(final_z, 2),
            "S존 상단": row.get('S존상단(topSz)', 3.45),
            "S존 하단": row.get('S존하단(bottomSz)', 1.65)
        })

# --- 기하학적 기준점 (유리창 스트라이크 존 & 홈플레이트) ---
try:
    sz_top = float(df_active.iloc[0]['S존상단(topSz)'])
    sz_bot = float(df_active.iloc[0]['S존하단(bottomSz)'])
    y_target = float(df_active.iloc[0]['상하위치(crossPlateY)'])
except:
    sz_top, sz_bot, y_target = 3.45, 1.65, 0.7083
    
half_w = 0.7083 # 17인치 홈플레이트 절반

# 1. 착시를 막는 '반투명 3D 유리창' 스트라이크 존
fig.add_trace(go.Scatter3d(
    x=[-half_w, half_w, half_w, -half_w, -half_w],
    y=[y_target, y_target, y_target, y_target, y_target],
    z=[sz_bot, sz_bot, sz_top, sz_top, sz_bot],
    mode='lines', line=dict(color='blue', width=4),
    surfaceaxis=1, # 폴리곤 내부를 채움 (착시 완전 제거)
    surfacecolor='rgba(0, 150, 255, 0.15)',
    name='스트라이크 존 (유리창)'
))

# 2. 홈플레이트 바닥 채우기
fig.add_trace(go.Scatter3d(
    x=[-half_w, half_w, half_w, 0, -half_w, -half_w],
    y=[1.417, 1.417, 0.7083, 0.0, 0.7083, 1.417],
    z=[0, 0, 0, 0, 0, 0],
    mode='lines', line=dict(color='black', width=2),
    surfaceaxis=2, surfacecolor='white',
    name='홈플레이트'
))

# 3D 레이아웃 세팅
fig.update_layout(
    height=800,
    scene=dict(
        xaxis=dict(title='좌우 (X)', range=[-3, 3]),
        yaxis=dict(title='거리 (Y)', range=[-2, 55]),
        zaxis=dict(title='높이 (Z)', range=[0, 6.5]),
        aspectratio=dict(x=1, y=2.5, z=1),
        camera=dict(eye=dict(x=0, y=-2.2, z=0.4))
    ),
    legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
)

st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 5. 물리 엔진 검증용 데이터 테이블
# ==========================================
st.subheader("📊 물리 엔진 렌더링 결과 검증표")
st.markdown("아래 표의 **'결과 높이(Z)'**가 S존의 상/하단 사이에 있다면 정상적으로 계산 및 시각화된 것입니다.")
st.dataframe(pd.DataFrame(result_logs), use_container_width=True)
