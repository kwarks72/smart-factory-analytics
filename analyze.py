"""
2단계: 데이터 분석 + 그래프 + 리포트

실행하면 output/ 폴더에 그래프 4장(PNG)과 report.md가 만들어집니다.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

from common import add_rule_flag, calc_daily, calc_oee, load_clean, load_extra, pareto, work_order_summary

OUT = Path("output")
OUT.mkdir(exist_ok=True)

# --- 그래프 모양 설정 (한글 폰트: Windows는 맑은 고딕) ---
available = {f.name for f in font_manager.fontManager.ttflist}
for name in ["Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"]:
    if name in available:
        plt.rcParams["font.family"] = name
        break
plt.rcParams["axes.unicode_minus"] = False

BLUE = "#2a78d6"  # 기본 색
ORANGE = "#eb6834"  # 강조 색 (문제가 있는 곳)
INK = "#0b0b0b"
INK2 = "#52514e"
SURFACE = "#fcfcfb"


def style(ax, title):
    """그래프를 깔끔하게: 위·오른쪽 테두리 제거, 연한 격자."""
    ax.set_title(title, loc="left", fontsize=12, color=INK, fontweight="bold")
    ax.set_facecolor(SURFACE)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color("#c3c2b7")
    ax.grid(axis="y", color="#e5e4df", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK2)


def save(fig, filename):
    fig.patch.set_facecolor(SURFACE)
    fig.tight_layout()
    fig.savefig(OUT / filename, dpi=150)
    plt.close(fig)


# ============================================================
# 1. 데이터 불러오기 + 청소
# ============================================================
equipment, production, sensor, cleaning = load_clean()
work_order, downtime, defect_detail = load_extra()
sensor = add_rule_flag(sensor)

production["total_qty"] = production["good_qty"] + production["defect_qty"]
production["date"] = production["ts"].dt.date

# ============================================================
# 2. 숫자 계산 (KPI)
# ============================================================
# 하루 단위 생산량과 불량률 / 설비별 OEE (계산식은 common.py에 있습니다)
daily = calc_daily(production)
by_eq = calc_oee(production, equipment)

# 온도가 평소보다 높을수록 불량이 늘어나는지 보기
merged = production.merge(sensor[["equip_id", "ts", "temp_gap"]], on=["equip_id", "ts"])
merged = merged[merged["total_qty"] > 0]
bins = [-100, 1, 3, 6, 9, 100]
labels = ["~+1도", "+1~3도", "+3~6도", "+6~9도", "+9도 이상"]
merged["gap_bin"] = pd.cut(merged["temp_gap"], bins=bins, labels=labels)
by_gap = merged.groupby("gap_bin", observed=True).agg(defect=("defect_qty", "sum"), total=("total_qty", "sum"))
by_gap["defect_rate"] = by_gap["defect"] / by_gap["total"] * 100

# M04 설비: 이상 탐지가 불량 증가보다 얼마나 먼저였는지
m04_sensor = sensor[sensor["equip_id"] == "M04"].copy()
m04_prod = production[production["equip_id"] == "M04"].set_index("ts")
m04_prod["defect_rate_6h"] = (
    m04_prod["defect_qty"].rolling(6).sum() / m04_prod["total_qty"].rolling(6).sum() * 100
)
first_flag = m04_sensor.loc[m04_sensor["rule_flag"], "ts"].min()
first_bad = m04_prod.loc[m04_prod["defect_rate_6h"] > 5, :].index.min()
lead_hours = (first_bad - first_flag) / pd.Timedelta(hours=1)

# 규칙이 잡아낸 설비 목록 (M02의 가짜 경보를 걸러냈는지 확인)
flagged_equipment = sorted(sensor.loc[sensor["rule_flag"], "equip_id"].unique())

# 비가동 파레토 (계획 정비는 "계획된" 정지라서 제외) / 불량 유형 파레토
downtime_pareto = pareto(downtime[~downtime["is_planned"]], "reason", "minutes")
defect_pareto = pareto(defect_detail, "defect_type", "qty")
m04_defect_pareto = pareto(defect_detail[defect_detail["equip_id"] == "M04"], "defect_type", "qty")

# 작업지시별 계획 대비 달성률 (가장 낮은 3건)
wo_summary = work_order_summary(work_order, production)
worst_orders = wo_summary.sort_values("achievement").head(3)

# ============================================================
# 3. 그래프
# ============================================================
# 그래프 1: 일별 생산량 / 불량률 (축이 다른 두 값은 위아래 두 칸으로 나눠 그립니다)
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
x = pd.to_datetime(daily.index)
ax1.bar(x, daily["good"], color=BLUE, width=0.7)
style(ax1, "일별 양품 생산량 (개)")
ax2.plot(x, daily["defect_rate"], color=ORANGE, linewidth=2)
style(ax2, "일별 불량률 (%)")
peak = daily["defect_rate"].idxmax()
ax2.annotate(
    f"최고 {daily['defect_rate'].max():.1f}%",
    (pd.to_datetime(peak), daily["defect_rate"].max()),
    textcoords="offset points", xytext=(8, -4), color=INK, fontsize=9,
)
fig.autofmt_xdate()
save(fig, "1_daily_production.png")

# 그래프 2: 설비별 OEE (가장 낮은 설비만 주황색)
fig, ax = plt.subplots(figsize=(8, 4))
order = by_eq.sort_values("oee")
colors = [ORANGE if e == order.index[0] else BLUE for e in order.index]
labels_y = [f"{e} {order.loc[e, 'name']}" for e in order.index]
ax.barh(labels_y, order["oee"], color=colors, height=0.6)
for i, v in enumerate(order["oee"]):
    ax.text(v + 0.5, i, f"{v:.1f}%", va="center", color=INK, fontsize=9)
style(ax, "설비별 OEE (설비종합효율, %)")
ax.grid(axis="y", visible=False)
ax.set_xlim(0, 100)
save(fig, "2_oee_by_equipment.png")

# 그래프 3: 평소보다 온도가 높을수록 불량률이 올라가는가
fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(by_gap.index.astype(str), by_gap["defect_rate"], color=BLUE, width=0.6)
for i, v in enumerate(by_gap["defect_rate"]):
    ax.text(i, v + 0.3, f"{v:.1f}%", ha="center", color=INK, fontsize=9)
style(ax, "평소보다 온도가 높을수록 불량률이 올라간다 (%)")
save(fig, "3_temperature_vs_defect.png")

# 그래프 4: M04 설비 이상 징후 타임라인
window = (m04_sensor["ts"] >= "2026-10-17") & (m04_sensor["ts"] < "2026-10-23")
view = m04_sensor[window]
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
ax1.plot(view["ts"], view["temperature"], color=BLUE, linewidth=1.5)
flagged = view[view["rule_flag"]]
ax1.scatter(flagged["ts"], flagged["temperature"], color=ORANGE, s=14, zorder=3)
style(ax1, "M04 용접 2호 - 온도 (°C), 주황 점 = 이상 탐지")
ax1.axvline(first_flag, color=INK2, linestyle="--", linewidth=1)
ax1.text(first_flag, ax1.get_ylim()[1], " 첫 이상 탐지", color=INK, fontsize=9, va="top")
dr = m04_prod.loc[view["ts"].min():view["ts"].max(), "defect_rate_6h"]
ax2.plot(dr.index, dr.values, color=ORANGE, linewidth=2)
style(ax2, "M04 불량률 (최근 6시간 기준, %)")
ax2.axvline(first_bad, color=INK2, linestyle="--", linewidth=1)
ax2.text(first_bad, ax2.get_ylim()[1], " 불량률 5% 돌파", color=INK, fontsize=9, va="top")
fig.autofmt_xdate()
save(fig, "4_m04_anomaly_timeline.png")

# 그래프 5, 6: 파레토 (큰 원인부터 정렬해서 "무엇부터 고칠지" 보여 줍니다)
def pareto_chart(table, title, unit, filename):
    fig, ax = plt.subplots(figsize=(8, 4))
    t = table.iloc[::-1]  # 가장 큰 항목이 위로 오게 뒤집기
    colors = [BLUE] * (len(t) - 1) + [ORANGE]  # 1위만 강조
    ax.barh(t.index, t["value"], color=colors, height=0.6)
    for i, (v, s, c) in enumerate(zip(t["value"], t["share"], t["cum_share"])):
        ax.text(v + t["value"].max() * 0.01, i, f"{v:,.0f}{unit} · {s:.0f}% (누적 {c:.0f}%)", va="center", color=INK, fontsize=9)
    style(ax, title)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, t["value"].max() * 1.5)
    save(fig, filename)


pareto_chart(downtime_pareto, "비가동 사유 파레토 (계획 외 정지, 분)", "분", "5_downtime_pareto.png")
pareto_chart(defect_pareto, "불량 유형 파레토 (개)", "개", "6_defect_pareto.png")

# ============================================================
# 4. 리포트 (마크다운 문서) 자동 작성
# ============================================================
lines = []
lines.append("# 스마트팩토리 생산·설비 분석 리포트 (시뮬레이션 데이터)\n")
lines.append(f"- 기간: {daily.index.min()} ~ {daily.index.max()} ({len(daily)}일), 설비 {len(equipment)}대")
lines.append(f"- 총 생산: {int(daily['total'].sum()):,}개 / 양품 {int(daily['good'].sum()):,}개 / 불량률 {daily['defect'].sum() / daily['total'].sum() * 100:.2f}%\n")
lines.append("## 데이터 청소 내역")
for k, v in cleaning.items():
    lines.append(f"- {k}: {v}건")
lines.append("\n## 설비별 OEE")
lines.append("| 설비 | 이름 | 가동률 | 성능률 | 양품률 | OEE |")
lines.append("|---|---|---|---|---|---|")
for e, r in by_eq.iterrows():
    lines.append(f"| {e} | {r['name']} | {r['availability']*100:.1f}% | {r['performance']*100:.1f}% | {r['quality']*100:.1f}% | {r['oee']:.1f}% |")
lines.append("\n## 온도와 불량률")
for g, r in by_gap.iterrows():
    lines.append(f"- 평소보다 {g}: 불량률 {r['defect_rate']:.1f}%")
lines.append("\n## 비가동 사유 (계획 외 정지)")
for r, row in downtime_pareto.iterrows():
    lines.append(f"- {r}: {row['value']:,.0f}분 ({row['share']:.0f}%)")
lines.append("\n## 불량 유형")
for r, row in defect_pareto.iterrows():
    lines.append(f"- {r}: {row['value']:,.0f}개 ({row['share']:.0f}%)")
top_m04 = m04_defect_pareto.index[0]
lines.append(f"- M04 설비는 '{top_m04}'이 {m04_defect_pareto.iloc[0]['share']:.0f}%로 가장 많음")
lines.append("\n## 작업지시 달성률 하위 3건 (양품 기준)")
for _, r in worst_orders.iterrows():
    lines.append(f"- {r['wo_id']} ({r['product']}): 달성률 {r['achievement']:.1f}%, 불량률 {r['defect_rate']:.1f}%")
lines.append("\n## 이상 탐지 결과 (규칙 기반)")
lines.append(f"- 이상으로 표시된 설비: {', '.join(flagged_equipment)}")
lines.append(f"- M04 첫 이상 탐지: {first_flag}")
lines.append(f"- M04 불량률(6시간 기준) 5% 돌파: {first_bad}")
lines.append(f"- 이상 탐지가 불량 급증보다 약 {lead_hours:.0f}시간 빨랐음 (시뮬레이션 기준)")
(OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

print("\n".join(lines))
print("\n그래프 6장과 report.md를 output/ 폴더에 저장했습니다.")
