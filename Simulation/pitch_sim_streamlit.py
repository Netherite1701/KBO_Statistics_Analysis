"""SQLite-backed KBO PTS viewer.

Run:
    streamlit run Simulation/pitch_sim_streamlit.py
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from data_loader import list_games, load_game


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "kbo.sqlite"

st.set_page_config(page_title="KBO PTS Viewer", layout="wide")
st.title("KBO PTS 투구 궤적")
st.caption("SQLite의 원본 타석 ID와 실제 릴리스 좌표(z0)를 사용합니다.")

database = Path(st.sidebar.text_input("SQLite 경로", str(DEFAULT_DATABASE)))
if not database.exists():
    st.info("먼저 `python -m kbo_crawler sync`로 데이터를 수집하세요.")
    st.stop()

games = list_games(database)
if games.empty:
    st.warning("투구가 적재된 경기가 없습니다.")
    st.stop()

labels = {
    row.game_id: (
        f"{row.game_date} {row.away_team_id} {row.away_score}"
        f" : {row.home_score} {row.home_team_id}"
    )
    for row in games.itertuples()
}
game_id = st.sidebar.selectbox(
    "경기",
    games["game_id"].tolist(),
    format_func=labels.get,
)
data = load_game(database, game_id)

inning = st.sidebar.selectbox("이닝", sorted(data["inning"].dropna().unique()))
halves = data.loc[data["inning"] == inning, "half"].dropna().unique().tolist()
half = st.sidebar.selectbox("초/말", halves)
subset = data[(data["inning"] == inning) & (data["half"] == half)]

pa_labels = {
    row.plate_appearance_id: (
        f"{row.relay_no}: {row.batter_name or row.batter_id}"
        f" — {row.result_text or '진행 기록'}"
    )
    for row in subset.drop_duplicates("plate_appearance_id").itertuples()
}
plate_appearance_id = st.sidebar.selectbox(
    "타석",
    list(pa_labels),
    format_func=pa_labels.get,
)
active = subset[subset["plate_appearance_id"] == plate_appearance_id]


def trajectory(row, points: int = 80):
    values = (row.y0, row.z0, row.vy0, row.vz0, row.ay, row.az, row.cross_plate_y)
    if any(value is None or not math.isfinite(float(value)) for value in values):
        return None
    y0, z0, vy0, vz0, ay, az, plate_y = map(float, values)
    discriminant = vy0 * vy0 - 2 * ay * (y0 - plate_y)
    if discriminant < 0:
        return None
    roots = (
        ((-vy0 - math.sqrt(discriminant)) / ay, (-vy0 + math.sqrt(discriminant)) / ay)
        if abs(ay) > 1e-12
        else (-(y0 - plate_y) / vy0,)
    )
    times = [value for value in roots if value >= 0 and math.isfinite(value)]
    if not times:
        return None
    time = min(times)
    t = np.linspace(0, time, points)
    x = float(row.x0) + float(row.vx0) * t + 0.5 * float(row.ax) * t**2
    y = y0 + vy0 * t + 0.5 * ay * t**2
    z = z0 + vz0 * t + 0.5 * az * t**2
    return x, y, z


figure = go.Figure()
for row in active.itertuples():
    path = trajectory(row)
    if path is None:
        continue
    x, y, z = path
    label = f"{row.pitch_num}구 {row.pitch_type or '미분류'} {row.speed_kph or '-'} km/h"
    figure.add_trace(
        go.Scatter3d(
            x=x,
            y=y,
            z=z,
            mode="lines",
            name=label,
            hovertemplate=f"{label}<br>X %{{x:.2f}}<br>Y %{{y:.2f}}<br>Z %{{z:.2f}}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter3d(
            x=[x[-1]],
            y=[y[-1]],
            z=[z[-1]],
            mode="markers",
            marker={"size": 5},
            showlegend=False,
        )
    )

figure.update_layout(
    height=720,
    scene={
        "xaxis_title": "좌우 (ft)",
        "yaxis_title": "홈플레이트 방향 (ft)",
        "zaxis_title": "높이 (ft)",
        "aspectmode": "data",
    },
)
st.plotly_chart(figure, use_container_width=True)
st.dataframe(
    active[
        [
            "pitch_num",
            "pitch_type",
            "speed_kph",
            "pitch_result",
            "plate_height",
            "strike_zone_bottom",
            "strike_zone_top",
        ]
    ],
    hide_index=True,
    use_container_width=True,
)
