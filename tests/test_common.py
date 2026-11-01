"""
계산 함수 테스트: 손으로 계산한 정답과 프로그램 결과가 같은지 확인합니다.
"""

import numpy as np
import pandas as pd
import pytest

from common import add_rule_flag, calc_daily, calc_oee, clean_data, pareto, work_order_summary


def ts(hours):
    return pd.Timestamp("2026-10-01 00:00") + pd.to_timedelta(hours, unit="h")


def test_clean_data_removes_duplicates_and_sensor_errors():
    production = pd.DataFrame(
        {
            "equip_id": ["M01", "M01", "M01"],
            "ts": [ts(0), ts(1), ts(1)],  # ts(1)이 두 번 기록됨
            "good_qty": [10, 10, 10],
        }
    )
    sensor = pd.DataFrame(
        {
            "equip_id": ["M01"] * 3,
            "ts": [ts(0), ts(1), ts(2)],
            "temperature": [60.0, -999, 64.0],  # 가운데는 오류 코드
            "vibration": [2.0, 2.0, np.nan],  # 마지막은 빈 값
            "current_a": [12.0, 12.0, 12.0],
        }
    )
    prod_clean, sensor_clean, info = clean_data(production, sensor)

    assert len(prod_clean) == 2
    assert info["중복 생산 기록 제거"] == 1
    assert info["센서 오류값(-999) 처리"] == 1
    assert sensor_clean["temperature"].tolist() == [60.0, 62.0, 64.0]  # 앞뒤 평균으로 채워짐
    assert sensor_clean["vibration"].isna().sum() == 0


def test_calc_oee_matches_hand_calculation():
    # 계획 100개/시간. 1시간은 60분 가동, 다음 1시간은 30분만 가동.
    production = pd.DataFrame(
        {
            "equip_id": ["M01", "M01"],
            "ts": [ts(0), ts(1)],
            "planned_qty": [100, 100],
            "good_qty": [90, 45],
            "defect_qty": [10, 5],
            "run_minutes": [60.0, 30.0],
        }
    )
    equipment = pd.DataFrame({"equip_id": ["M01"], "name": ["프레스"], "line_id": ["L1"]})
    r = calc_oee(production, equipment).loc["M01"]

    assert r["availability"] == pytest.approx(90 / 120)  # 120분 중 90분 가동
    assert r["performance"] == pytest.approx(1.0)  # 가동 시간 동안 계획만큼 생산 (150 / 150)
    assert r["quality"] == pytest.approx(135 / 150)
    assert r["oee"] == pytest.approx(0.75 * 1.0 * 0.9 * 100)


def test_calc_daily_defect_rate():
    production = pd.DataFrame(
        {
            "equip_id": ["M01", "M01"],
            "ts": [ts(1), ts(30)],  # 10/1, 10/2
            "good_qty": [95, 98],
            "defect_qty": [5, 2],
        }
    )
    daily = calc_daily(production)
    assert daily["defect_rate"].round(1).tolist() == [5.0, 2.0]


def test_pareto_is_sorted_and_cumulates_to_100():
    df = pd.DataFrame({"reason": ["a", "b", "a", "c"], "minutes": [10, 50, 20, 20]})
    p = pareto(df, "reason", "minutes")
    assert p.index.tolist() == ["b", "a", "c"]  # b=50, a=30, c=20
    assert p["share"].tolist() == pytest.approx([50, 30, 20])
    assert p["cum_share"].iloc[-1] == pytest.approx(100)


def test_work_order_summary_achievement():
    work_order = pd.DataFrame({"wo_id": ["W1"], "equip_id": ["M01"], "product": ["A"], "planned_qty": [200]})
    production = pd.DataFrame({"wo_id": ["W1", "W1"], "good_qty": [80, 90], "defect_qty": [10, 20]})
    s = work_order_summary(work_order, production).iloc[0]
    assert s["achievement"] == pytest.approx(85.0)  # 양품 170 / 계획 200
    assert s["defect_rate"] == pytest.approx(30 / 200 * 100)


def make_sensor(extra):
    """10일치 일정한 온도(60도)에 사건(extra)만 얹은 센서 표"""
    hours = pd.date_range("2026-10-01", periods=240, freq="h")
    temp = np.full(240, 60.0)
    for start, length, delta in extra:
        temp[start : start + length] += delta
    return pd.DataFrame({"equip_id": "M01", "ts": hours, "temperature": temp})


def test_rule_flag_catches_sustained_rise():
    sensor = add_rule_flag(make_sensor([(200, 20, 10.0)]))  # 20시간 동안 +10도
    assert sensor["rule_flag"].any()


def test_rule_flag_ignores_short_glitch():
    sensor = add_rule_flag(make_sensor([(200, 2, 6.0)]))  # 2시간만 +6도 튐
    assert not sensor["rule_flag"].any()
