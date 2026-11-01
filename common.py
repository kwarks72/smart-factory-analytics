"""
여러 파일이 같이 쓰는 공통 코드

  - load_clean():   DB에서 읽고 "청소"해서 돌려줍니다.
  - load_extra():   작업지시·비가동·불량 상세 표를 읽습니다.
  - clean_data():   청소 규칙 (DB 없이도 시험할 수 있게 따로 분리)
  - calc_*, pareto(), work_order_summary(): KPI 계산
  - add_rule_flag(): 센서 온도가 평소보다 높은 구간을 표시합니다 (규칙 기반 이상 탐지)
"""

import numpy as np
import pandas as pd

import db

SENSOR_COLS = ["temperature", "vibration", "current_a"]

# 평소 온도보다 몇 도 이상 높으면 "이상"으로 볼지 (정상일 때 흔들림은 ±1도 안팎)
TEMP_THRESHOLD = 3.0


# ============================================================
# 데이터 읽기 / 청소
# ============================================================
def clean_data(production, sensor):
    """
    생산·센서 표를 청소합니다. (표를 받아서 표를 돌려주는 순수한 함수 -> 테스트하기 쉬움)
      1) 같은 설비·같은 시각 중복 기록 제거
      2) 센서 오류 코드(-999)를 '값 없음'으로 바꾸기
      3) 빈 값은 같은 설비의 앞뒤 시간 값으로 채우기
    """
    cleaning = {}
    production = production.copy()
    sensor = sensor.copy()

    cleaning["중복 생산 기록 제거"] = int(production.duplicated(["equip_id", "ts"]).sum())
    production = production.drop_duplicates(["equip_id", "ts"])

    error_mask = sensor["temperature"] == -999
    cleaning["센서 오류값(-999) 처리"] = int(error_mask.sum())
    sensor.loc[error_mask, "temperature"] = np.nan

    cleaning["빈 센서값 보정"] = int(sensor[SENSOR_COLS].isna().sum().sum())
    sensor = sensor.sort_values(["equip_id", "ts"]).reset_index(drop=True)
    for col in SENSOR_COLS:
        sensor[col] = sensor.groupby("equip_id")[col].transform(lambda s: s.interpolate(limit_direction="both"))

    production = production.sort_values(["equip_id", "ts"]).reset_index(drop=True)
    return production, sensor, cleaning


def load_clean(engine=None):
    """DB에서 읽어 청소한 표 3개(설비, 생산, 센서)와 청소 내역을 돌려줍니다."""
    engine = engine or db.get_engine()
    equipment = pd.read_sql("SELECT * FROM equipment", engine)
    production = pd.read_sql("SELECT * FROM production", engine, parse_dates=["ts"])
    sensor = pd.read_sql("SELECT * FROM sensor", engine, parse_dates=["ts"])
    production, sensor, cleaning = clean_data(production, sensor)
    return equipment, production, sensor, cleaning


def load_extra(engine=None):
    """작업지시, 비가동, 불량 상세 표를 읽습니다."""
    engine = engine or db.get_engine()
    work_order = pd.read_sql("SELECT * FROM work_order", engine, parse_dates=["start_ts", "end_ts"])
    downtime = pd.read_sql("SELECT * FROM downtime", engine, parse_dates=["ts"])
    defect_detail = pd.read_sql("SELECT * FROM defect_detail", engine, parse_dates=["ts"])
    downtime["is_planned"] = downtime["is_planned"].astype(bool)  # SQLite는 참/거짓을 1/0으로 돌려주므로 맞춰 줍니다
    return work_order, downtime, defect_detail


# ============================================================
# KPI 계산
# ============================================================
def calc_daily(production):
    """하루 단위 양품·불량·불량률(%)."""
    p = production.assign(date=production["ts"].dt.date)
    daily = p.groupby("date").agg(good=("good_qty", "sum"), defect=("defect_qty", "sum"))
    daily["total"] = daily["good"] + daily["defect"]
    daily["defect_rate"] = daily["defect"] / daily["total"] * 100
    return daily


def calc_oee(production, equipment):
    """설비별 OEE(설비종합효율) = 가동률 x 성능률 x 양품률."""
    p = production.assign(
        total_qty=production["good_qty"] + production["defect_qty"],
        planned_run=production["planned_qty"] * production["run_minutes"] / 60,
    )
    g = p.groupby("equip_id").agg(
        run_minutes=("run_minutes", "sum"),
        hours=("ts", "count"),
        planned_run=("planned_run", "sum"),
        good=("good_qty", "sum"),
        defect=("defect_qty", "sum"),
        total=("total_qty", "sum"),
    )
    g["availability"] = g["run_minutes"] / (g["hours"] * 60)  # 가동률: 켜져 있던 시간 비율
    g["performance"] = g["total"] / g["planned_run"]  # 성능률: 계획 대비 얼마나 만들었나
    g["quality"] = g["good"] / g["total"]  # 양품률: 만든 것 중 멀쩡한 비율
    g["oee"] = g["availability"] * g["performance"] * g["quality"] * 100
    return g.join(equipment.set_index("equip_id")[["name", "line_id"]])


def pareto(df, label_col, value_col):
    """
    파레토 표: 큰 순서로 정렬하고 비중(%)과 누적 비중(%)을 붙입니다.
    "문제의 80%는 소수의 원인에서 나온다"를 확인할 때 씁니다.
    """
    out = df.groupby(label_col)[value_col].sum().sort_values(ascending=False).to_frame("value")
    out["share"] = out["value"] / out["value"].sum() * 100
    out["cum_share"] = out["share"].cumsum()
    return out


def work_order_summary(work_order, production):
    """작업지시별 계획 대비 실적(달성률)과 불량률."""
    actual = production.groupby("wo_id").agg(good=("good_qty", "sum"), defect=("defect_qty", "sum"))
    out = work_order.set_index("wo_id").join(actual)
    out["produced"] = out["good"] + out["defect"]
    out["achievement"] = out["good"] / out["planned_qty"] * 100  # 양품 기준 달성률
    out["defect_rate"] = out["defect"] / out["produced"] * 100
    return out.reset_index()


# ============================================================
# 이상 탐지 (규칙 기반)
# ============================================================
def add_rule_flag(sensor):
    """
    '같은 시각대 평소 온도'와 비교해서 6시간 평균이 3도 넘게 높으면 이상으로 표시합니다.

    왜 시각대별로 비교할까? 온도는 하루 주기로 오르내리기 때문에,
    낮에 높은 건 정상입니다. 같은 시각의 평소 값과 비교해야 공평합니다.
    왜 6시간 평균을 쓸까? 센서가 잠깐 튄 것(가짜 경보)에 놀라지 않기 위해서입니다.
    """
    sensor = sensor.copy()
    sensor["hour"] = sensor["ts"].dt.hour
    usual = sensor.groupby(["equip_id", "hour"])["temperature"].transform("median")
    sensor["temp_gap"] = sensor["temperature"] - usual  # 평소보다 몇 도 높은지
    sensor["temp_gap_6h"] = sensor.groupby("equip_id")["temp_gap"].transform(lambda s: s.rolling(6).mean())
    sensor["rule_flag"] = sensor["temp_gap_6h"] > TEMP_THRESHOLD
    return sensor
