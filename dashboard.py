"""
6단계: 웹 대시보드 (Streamlit)

코드 몇십 줄로 "웹 화면"을 만들어 주는 도구입니다.
왼쪽에서 기간·설비를 고르면, 오른쪽의 숫자와 그래프가 그에 맞게 바뀝니다.

실행:  streamlit run dashboard.py
확인:  브라우저가 자동으로 열립니다 (http://localhost:8501)
"""

import altair as alt
import pandas as pd
import streamlit as st

from common import (
    add_rule_flag,
    calc_daily,
    calc_oee,
    load_clean,
    load_extra,
    pareto,
    work_order_summary,
)

BLUE = "#2a78d6"  # 기본 색
ORANGE = "#eb6834"  # 강조 색 (문제가 있는 곳)

st.set_page_config(page_title="스마트팩토리 대시보드", page_icon="🏭", layout="wide")


@st.cache_data  # 한 번 읽은 데이터는 기억해 둬서, 화면을 바꿀 때마다 DB를 다시 읽지 않습니다
def load_all():
    equipment, production, sensor, cleaning = load_clean()
    work_order, downtime, defect_detail = load_extra()
    sensor = add_rule_flag(sensor)
    return equipment, production, sensor, cleaning, work_order, downtime, defect_detail


equipment, production, sensor, cleaning, work_order, downtime, defect_detail = load_all()

# ============================================================
# 왼쪽 필터
# ============================================================
st.sidebar.header("필터")
min_d, max_d = production["ts"].dt.date.min(), production["ts"].dt.date.max()
picked = st.sidebar.date_input("기간", value=(min_d, max_d), min_value=min_d, max_value=max_d)
start_d, end_d = (picked[0], picked[1]) if len(picked) == 2 else (min_d, max_d)  # 날짜를 하나만 골랐을 땐 전체 기간

equip_names = {r.equip_id: f"{r.equip_id} {r.name}" for r in equipment.itertuples()}
chosen = st.sidebar.multiselect(
    "설비", options=list(equip_names), default=list(equip_names), format_func=lambda e: equip_names[e]
)
st.sidebar.caption("⚠️ 시뮬레이션 데이터입니다. 실제 공장 데이터가 아닙니다.")
if not chosen:
    st.warning("왼쪽에서 설비를 하나 이상 선택하세요.")
    st.stop()


def in_range(df, col="ts"):
    d = df[col].dt.date
    return df[(d >= start_d) & (d <= end_d) & (df["equip_id"].isin(chosen))]


prod_f = in_range(production)
sensor_f = in_range(sensor)
down_f = in_range(downtime)
defect_f = in_range(defect_detail)
if prod_f.empty:
    st.warning("선택한 조건에 맞는 데이터가 없습니다.")
    st.stop()

# ============================================================
# 상단 KPI 카드
# ============================================================
daily = calc_daily(prod_f)
oee = calc_oee(prod_f, equipment)
flagged_ids = sorted(sensor_f.loc[sensor_f["rule_flag"], "equip_id"].unique())

st.title("🏭 스마트팩토리 생산·설비 대시보드")
c1, c2, c3, c4 = st.columns(4)
c1.metric("총 생산", f"{int(daily['total'].sum()):,} 개")
c2.metric("불량률", f"{daily['defect'].sum() / daily['total'].sum() * 100:.2f} %")
c3.metric("평균 OEE", f"{oee['oee'].mean():.1f} %")
c4.metric("이상 탐지 설비", ", ".join(flagged_ids) if flagged_ids else "없음")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["개요", "설비·비가동", "품질", "이상 탐지", "작업지시"])


def pareto_chart(table, title, unit):
    """가로 막대 파레토: 가장 큰 항목만 주황색으로 강조"""
    t = table.reset_index()
    t.columns = ["label", "value", "share", "cum_share"]
    t["top"] = t.index == 0
    return (
        alt.Chart(t)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("value:Q", title=unit),
            y=alt.Y("label:N", sort="-x", title=None),
            color=alt.condition("datum.top", alt.value(ORANGE), alt.value(BLUE)),
            tooltip=[
                alt.Tooltip("label:N", title="항목"),
                alt.Tooltip("value:Q", title=unit, format=",.0f"),
                alt.Tooltip("share:Q", title="비중(%)", format=".1f"),
                alt.Tooltip("cum_share:Q", title="누적(%)", format=".1f"),
            ],
        )
        .properties(title=title, height=alt.Step(38))
    )


# ---------------- 개요 ----------------
with tab1:
    d = daily.reset_index()
    d["date"] = pd.to_datetime(d["date"])
    left, right = st.columns(2)
    left.altair_chart(
        alt.Chart(d)
        .mark_bar(color=BLUE, cornerRadiusEnd=3)
        .encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(format="%m/%d")),
            y=alt.Y("good:Q", title="양품 (개)"),
            tooltip=[alt.Tooltip("date:T", title="날짜"), alt.Tooltip("good:Q", title="양품", format=",")],
        )
        .properties(title="일별 양품 생산량", height=280),
        width="stretch",
    )
    right.altair_chart(
        alt.Chart(d)
        .mark_line(color=ORANGE, strokeWidth=2, point=alt.OverlayMarkDef(color=ORANGE))
        .encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(format="%m/%d")),
            y=alt.Y("defect_rate:Q", title="불량률 (%)", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("date:T", title="날짜"), alt.Tooltip("defect_rate:Q", title="불량률(%)", format=".2f")],
        )
        .properties(title="일별 불량률", height=280),
        width="stretch",
    )
    with st.expander("데이터 청소 내역 (원본 데이터의 문제를 어떻게 처리했는지)"):
        st.table(pd.DataFrame({"처리 건수": cleaning}))

# ---------------- 설비·비가동 ----------------
with tab2:
    left, right = st.columns(2)
    o = oee.reset_index()
    o["label"] = o["equip_id"] + " " + o["name"]
    o["lowest"] = o["oee"] == o["oee"].min()
    left.altair_chart(
        alt.Chart(o)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("oee:Q", title="OEE (%)", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("label:N", sort="-x", title=None),
            color=alt.condition("datum.lowest", alt.value(ORANGE), alt.value(BLUE)),
            tooltip=[
                alt.Tooltip("label:N", title="설비"),
                alt.Tooltip("availability:Q", title="가동률", format=".1%"),
                alt.Tooltip("performance:Q", title="성능률", format=".1%"),
                alt.Tooltip("quality:Q", title="양품률", format=".1%"),
                alt.Tooltip("oee:Q", title="OEE(%)", format=".1f"),
            ],
        )
        .properties(title="설비별 OEE (가장 낮은 설비 강조)", height=alt.Step(38)),
        width="stretch",
    )
    unplanned = down_f[~down_f["is_planned"]]
    if unplanned.empty:
        right.info("선택한 조건에서 계획 외 비가동이 없습니다.")
    else:
        right.altair_chart(pareto_chart(pareto(unplanned, "reason", "minutes"), "계획 외 비가동 사유 (분)", "분"), width="stretch")
    st.caption("OEE = 가동률 × 성능률 × 양품률. 계획 정비는 '계획된' 정지라서 비가동 사유 그래프에서 뺐습니다.")
    show = oee[["name", "availability", "performance", "quality", "oee"]].copy()
    show.columns = ["설비명", "가동률", "성능률", "양품률", "OEE(%)"]
    for col in ["가동률", "성능률", "양품률"]:
        show[col] = show[col] * 100
    st.dataframe(
        show,
        width="stretch",
        column_config={c: st.column_config.NumberColumn(c, format="%.1f") for c in ["가동률", "성능률", "양품률", "OEE(%)"]},
    )

# ---------------- 품질 ----------------
with tab3:
    left, right = st.columns(2)
    if defect_f.empty:
        left.info("불량 기록이 없습니다.")
    else:
        left.altair_chart(pareto_chart(pareto(defect_f, "defect_type", "qty"), "불량 유형 (개)", "개"), width="stretch")

    m = prod_f.merge(sensor_f[["equip_id", "ts", "temp_gap"]], on=["equip_id", "ts"])
    m["total_qty"] = m["good_qty"] + m["defect_qty"]
    m = m[m["total_qty"] > 0]
    m["gap_bin"] = pd.cut(
        m["temp_gap"], bins=[-100, 1, 3, 6, 9, 100], labels=["~+1도", "+1~3도", "+3~6도", "+6~9도", "+9도 이상"]
    )
    g = m.groupby("gap_bin", observed=True).agg(defect=("defect_qty", "sum"), total=("total_qty", "sum")).reset_index()
    g["defect_rate"] = g["defect"] / g["total"] * 100
    g["gap_bin"] = g["gap_bin"].astype(str)
    right.altair_chart(
        alt.Chart(g)
        .mark_bar(color=BLUE, cornerRadiusEnd=3)
        .encode(
            x=alt.X("gap_bin:N", sort=None, title="평소보다 높은 온도", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("defect_rate:Q", title="불량률 (%)"),
            tooltip=[alt.Tooltip("gap_bin:N", title="구간"), alt.Tooltip("defect_rate:Q", title="불량률(%)", format=".1f")],
        )
        .properties(title="평소보다 온도가 높을수록 불량률이 올라간다", height=280),
        width="stretch",
    )

# ---------------- 이상 탐지 ----------------
with tab4:
    default_ix = chosen.index("M04") if "M04" in chosen else 0
    target = st.selectbox("설비 선택", chosen, index=default_ix, format_func=lambda e: equip_names[e])
    s = sensor_f[sensor_f["equip_id"] == target]
    p = prod_f[prod_f["equip_id"] == target].set_index("ts")
    p = p.assign(total=p["good_qty"] + p["defect_qty"])
    p["defect_rate_6h"] = p["defect_qty"].rolling(6).sum() / p["total"].rolling(6).sum() * 100
    flagged = s[s["rule_flag"]]

    if flagged.empty:
        st.success(f"{equip_names[target]}: 선택한 기간에 이상 징후가 없습니다.")
    else:
        st.error(
            f"{equip_names[target]}: 이상 징후 {len(flagged)}시간 — 첫 탐지 {flagged['ts'].min():%Y-%m-%d %H:%M}, "
            f"마지막 {flagged['ts'].max():%Y-%m-%d %H:%M}"
        )

    temp_line = (
        alt.Chart(s)
        .mark_line(color=BLUE, strokeWidth=1.5)
        .encode(x=alt.X("ts:T", title=None), y=alt.Y("temperature:Q", title="온도 (°C)", scale=alt.Scale(zero=False)))
    )
    temp_pts = (
        alt.Chart(flagged)
        .mark_circle(color=ORANGE, size=45)
        .encode(
            x="ts:T",
            y="temperature:Q",
            tooltip=[
                alt.Tooltip("ts:T", title="시각"),
                alt.Tooltip("temperature:Q", title="온도", format=".1f"),
                alt.Tooltip("temp_gap_6h:Q", title="평소 대비(6시간 평균)", format=".1f"),
            ],
        )
    )
    st.altair_chart((temp_line + temp_pts).properties(title="온도 (주황 점 = 이상 탐지)", height=260), width="stretch")
    st.altair_chart(
        alt.Chart(p.reset_index().dropna(subset=["defect_rate_6h"]))
        .mark_line(color=ORANGE, strokeWidth=2)
        .encode(
            x=alt.X("ts:T", title=None),
            y=alt.Y("defect_rate_6h:Q", title="불량률 (%)"),
            tooltip=[alt.Tooltip("ts:T", title="시각"), alt.Tooltip("defect_rate_6h:Q", title="불량률(6시간)", format=".1f")],
        )
        .properties(title="불량률 (최근 6시간 기준)", height=220),
        width="stretch",
    )
    st.caption("이상 탐지 규칙: 같은 시각대 평소 온도보다 최근 6시간 평균이 3°C 넘게 높으면 표시 (센서가 잠깐 튄 경우는 걸러집니다).")

# ---------------- 작업지시 ----------------
with tab5:
    ws = work_order_summary(work_order, production)
    ws = ws[(ws["start_ts"].dt.date <= end_d) & (ws["end_ts"].dt.date >= start_d) & ws["equip_id"].isin(chosen)]
    ws = ws.sort_values("achievement")
    show = ws[["wo_id", "equip_id", "product", "planned_qty", "good", "defect", "achievement", "defect_rate"]].copy()
    show.columns = ["작업지시", "설비", "제품", "계획 수량", "양품", "불량", "달성률(%)", "불량률(%)"]
    st.caption("달성률이 낮은 작업지시부터 보여 줍니다. (달성률 = 양품 ÷ 계획 수량)")
    st.dataframe(
        show,
        width="stretch",
        hide_index=True,
        column_config={
            "달성률(%)": st.column_config.ProgressColumn("달성률(%)", min_value=0, max_value=100, format="%.1f"),
            "불량률(%)": st.column_config.NumberColumn("불량률(%)", format="%.1f"),
        },
    )
