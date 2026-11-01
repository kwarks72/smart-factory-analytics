"""
4단계: 분석 결과를 API(웹 주소)로 제공하기

API란? 프로그램끼리 데이터를 주고받는 "창구"입니다.
식당에 비유하면 손님(다른 프로그램)이 주문(주소 요청)을 하면, 주방(이 서버)이
계산한 결과를 접시(JSON)에 담아 내주는 것과 같습니다.

실행:  uvicorn api:app --reload
확인:  브라우저에서 http://127.0.0.1:8000/docs  (자동으로 만들어진 시험 화면)
"""

from fastapi import FastAPI, HTTPException, Query

from common import (
    add_rule_flag,
    calc_daily,
    calc_oee,
    load_clean,
    load_extra,
    pareto,
    work_order_summary,
)

app = FastAPI(title="스마트팩토리 분석 API", description="시뮬레이션 공장 데이터의 KPI, 파레토, 작업지시, 이상 탐지 결과")

# 서버가 켜질 때 한 번만 데이터를 읽어 둡니다
equipment, production, sensor, _ = load_clean()
work_order, downtime, defect_detail = load_extra()
sensor = add_rule_flag(sensor)
EQUIP_IDS = set(equipment["equip_id"])


def check_equip(equip_id):
    """없는 설비 번호가 오면 404(찾을 수 없음)로 답합니다."""
    if equip_id is not None and equip_id not in EQUIP_IDS:
        raise HTTPException(status_code=404, detail=f"없는 설비입니다: {equip_id}")


@app.get("/")
def home():
    """서버가 살아 있는지 확인"""
    return {"message": "스마트팩토리 분석 API 동작 중", "docs": "/docs"}


@app.get("/kpi/daily")
def kpi_daily():
    """일별 양품·불량·불량률"""
    daily = calc_daily(production).round(2).reset_index()
    daily["date"] = daily["date"].astype(str)
    return daily.to_dict(orient="records")


@app.get("/equipment/oee")
def equipment_oee():
    """설비별 가동률·성능률·양품률·OEE"""
    oee = calc_oee(production, equipment)[["name", "line_id", "availability", "performance", "quality", "oee"]]
    return oee.round(4).reset_index().to_dict(orient="records")


@app.get("/downtime/pareto")
def downtime_pareto(equip_id: str | None = None):
    """계획 외 비가동 사유별 시간(분)과 비중. equip_id로 설비를 고를 수 있습니다."""
    check_equip(equip_id)
    d = downtime[~downtime["is_planned"]]
    if equip_id:
        d = d[d["equip_id"] == equip_id]
    return pareto(d, "reason", "minutes").round(2).reset_index().rename(columns={"reason": "label"}).to_dict(orient="records")


@app.get("/defects/pareto")
def defects_pareto(equip_id: str | None = None):
    """불량 유형별 수량과 비중."""
    check_equip(equip_id)
    d = defect_detail if not equip_id else defect_detail[defect_detail["equip_id"] == equip_id]
    return pareto(d, "defect_type", "qty").round(2).reset_index().rename(columns={"defect_type": "label"}).to_dict(orient="records")


@app.get("/workorders")
def workorders(equip_id: str | None = None, limit: int = Query(10, ge=1, le=100)):
    """작업지시별 계획 대비 달성률. 달성률이 낮은 순서로 보여 줍니다."""
    check_equip(equip_id)
    s = work_order_summary(work_order, production)
    if equip_id:
        s = s[s["equip_id"] == equip_id]
    s = s.sort_values("achievement").head(limit)
    s = s[["wo_id", "equip_id", "product", "planned_qty", "good", "defect", "achievement", "defect_rate"]].round(2)
    return s.to_dict(orient="records")


@app.get("/anomalies")
def anomalies(equip_id: str | None = None):
    """이상으로 표시된 시간 수와 처음/마지막 시각. equip_id를 주면 그 설비만 보여줍니다."""
    check_equip(equip_id)
    flagged = sensor[sensor["rule_flag"]]
    if equip_id:
        flagged = flagged[flagged["equip_id"] == equip_id]
    result = []
    for eid, g in flagged.groupby("equip_id"):
        result.append(
            {
                "equip_id": eid,
                "flagged_hours": int(len(g)),
                "first_flag": g["ts"].min().strftime("%Y-%m-%d %H:%M"),
                "last_flag": g["ts"].max().strftime("%Y-%m-%d %H:%M"),
            }
        )
    return result
