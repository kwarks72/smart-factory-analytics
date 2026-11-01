"""
API와 전체 흐름 테스트
"""

import pandas as pd
from streamlit.testing.v1 import AppTest

import generate_data
from tests.conftest import ROOT


def test_simulation_is_reproducible_and_has_planted_problems():
    a = generate_data.make_data()
    b = generate_data.make_data()
    pd.testing.assert_frame_equal(a["production"], b["production"])  # 같은 seed -> 같은 데이터
    assert (a["sensor"]["temperature"] == -999).sum() > 0  # 센서 오류값이 들어 있다
    assert a["production"].duplicated(["equip_id", "ts"]).sum() == 5  # 중복 기록 5건


def test_home(client):
    assert client.get("/").status_code == 200


def test_kpi_daily_has_30_days(client):
    rows = client.get("/kpi/daily").json()
    assert len(rows) == 30
    assert all(0 < r["defect_rate"] < 10 for r in rows)


def test_oee_has_six_machines_and_m04_is_lowest(client):
    rows = client.get("/equipment/oee").json()
    assert len(rows) == 6
    assert min(rows, key=lambda r: r["oee"])["equip_id"] == "M04"


def test_anomalies_flags_only_m04(client):
    rows = client.get("/anomalies").json()
    assert [r["equip_id"] for r in rows] == ["M04"]  # M02의 가짜 경보는 걸러져야 함
    assert rows[0]["first_flag"].startswith("2026-10-19")


def test_unknown_equipment_returns_404(client):
    assert client.get("/anomalies?equip_id=X9").status_code == 404
    assert client.get("/workorders?equip_id=X9").status_code == 404


def test_workorders_limit_is_validated(client):
    assert client.get("/workorders?limit=0").status_code == 422
    rows = client.get("/workorders?limit=3").json()
    assert len(rows) == 3
    assert rows == sorted(rows, key=lambda r: r["achievement"])  # 낮은 순서


def test_pareto_endpoints(client):
    for url in ["/downtime/pareto", "/defects/pareto", "/defects/pareto?equip_id=M04"]:
        rows = client.get(url).json()
        assert rows[0]["share"] >= rows[-1]["share"]
        assert abs(rows[-1]["cum_share"] - 100) < 0.5
    assert client.get("/defects/pareto?equip_id=M04").json()[0]["label"] == "용접 비드 불량"


def test_dashboard_runs_without_error(test_db):
    at = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=120).run()
    assert not at.exception
    assert len(at.tabs) == 5
