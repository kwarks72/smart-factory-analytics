"""
1단계: 시뮬레이션 공장 데이터 만들기

실제 공장 데이터를 구할 수 없어서, MES(생산관리시스템)에 쌓일 법한 데이터를
컴퓨터로 만들어 DB(기본: SQLite 파일, 선택: PostgreSQL)에 저장합니다.

  - 3개 라인 / 6대 설비 / 30일 / 1시간 단위 기록
  - 작업지시(48시간 단위), 비가동 사유, 불량 유형까지 포함
  - 일부러 넣어 둔 "사건"
      * M04 설비: 10/18 낮부터 온도·진동이 서서히 올라가고, 불량이 늘어남(주로 용접 비드 불량) -> 10/21 오전 정비
      * M02 설비: 센서가 잠깐 튄 가짜 경보(진짜 고장이 아님)
      * 센서 오류값(-999), 빈 값(NaN), 중복 기록 -> 분석 단계에서 "데이터 청소"로 처리

주의: 이 데이터는 시뮬레이션입니다. 실제 공장의 성능을 의미하지 않습니다.
"""

from pathlib import Path

import numpy as np
import pandas as pd

import db

SEED = 42  # 같은 숫자를 쓰면 실행할 때마다 똑같은 데이터가 나옵니다

START = pd.Timestamp("2026-10-01 00:00")
DAYS = 30
WO_HOURS = 48  # 작업지시 1건이 이어지는 시간

# (설비ID, 라인ID, 설비 이름, 시간당 계획 생산량)
EQUIPMENT = [
    ("M01", "L1", "프레스 1호", 120),
    ("M02", "L1", "프레스 2호", 120),
    ("M03", "L2", "용접 1호", 90),
    ("M04", "L2", "용접 2호", 90),
    ("M05", "L3", "조립 1호", 100),
    ("M06", "L3", "조립 2호", 100),
]

PRODUCTS = {"L1": ["BRKT-A", "BRKT-B"], "L2": ["FRAME-X", "FRAME-Y"], "L3": ["ASSY-1", "ASSY-2"]}

DEFECT_TYPES = {
    "L1": ["치수 불량", "버(Burr) 발생", "외관 스크래치"],
    "L2": ["용접 비드 불량", "기공(Porosity)", "치수 불량"],
    "L3": ["체결 불량", "부품 누락", "외관 스크래치"],
}

DOWNTIME_REASONS = ["자재 대기", "금형·치공구 교체", "설비 고장", "품질 점검"]
DOWNTIME_PROBS = [0.40, 0.20, 0.15, 0.25]

# M04 열화(점점 나빠짐) 사건 시각
DEGRADE_START = pd.Timestamp("2026-10-18 12:00")
MAINTENANCE_START = pd.Timestamp("2026-10-21 08:00")
MAINTENANCE_END = pd.Timestamp("2026-10-21 14:00")  # 이 시각까지 6시간 정비(가동 중지)


def make_data():
    rng = np.random.default_rng(SEED)  # 센서·생산량용 난수
    rng2 = np.random.default_rng(SEED + 1)  # 비가동 사유·불량 유형용 난수 (위 결과가 바뀌지 않도록 따로 둠)
    hours = pd.date_range(START, periods=DAYS * 24, freq="h")
    n = len(hours)

    production_parts, sensor_parts, downtime_rows, defect_rows, wo_rows = [], [], [], [], []

    for i, (equip_id, line_id, _name, planned) in enumerate(EQUIPMENT):
        hour_of_day = hours.hour.to_numpy()

        # --- 센서값: 기본값 + 하루 주기 + 잡음 ---
        temp = 58 + 3 * i + 2.0 * np.sin(2 * np.pi * hour_of_day / 24) + rng.normal(0, 1.0, n)
        vib = 2.0 + 0.2 * i + 0.15 * np.sin(2 * np.pi * hour_of_day / 24) + rng.normal(0, 0.1, n)
        cur = 12 + i + rng.normal(0, 0.4, n)

        # --- 사건 1: M04 열화 (온도·진동이 서서히 상승) ---
        excess_temp = np.zeros(n)  # 정상보다 몇 도 높은지
        if equip_id == "M04":
            hours_since = (hours - DEGRADE_START) / pd.Timedelta(hours=1)
            ramp = np.clip(hours_since.to_numpy(), 0, None) * 0.25  # 시간당 0.25도씩 상승
            ramp = np.minimum(ramp, 14)  # 최대 14도까지
            ramp[hours >= MAINTENANCE_END] = 0  # 정비 후 정상 복귀
            excess_temp = ramp
            temp = temp + excess_temp
            vib = vib + excess_temp * 0.08
            cur = cur + excess_temp * 0.1

        # --- 사건 2: M02 센서가 잠깐 튄 가짜 경보 (2시간만 +6도) ---
        if equip_id == "M02":
            glitch = (hours >= pd.Timestamp("2026-10-09 03:00")) & (hours < pd.Timestamp("2026-10-09 05:00"))
            temp = temp + np.where(glitch, 6.0, 0.0)

        # --- 가동 시간(분): 대부분 60분, 가끔 잠깐 정지 ---
        run_minutes = np.full(n, 60.0)
        stop = rng.random(n) < 0.02
        run_minutes[stop] = rng.integers(10, 50, stop.sum())
        maint = np.zeros(n, dtype=bool)
        if equip_id == "M04":
            maint = (hours >= MAINTENANCE_START) & (hours < MAINTENANCE_END)
            run_minutes[maint] = 0  # 계획 정비

        # --- 생산량/불량 ---
        performance = np.clip(rng.normal(0.96, 0.03, n), 0.8, 1.0)
        total = np.round(planned * run_minutes / 60 * performance).astype(int)

        # 불량률: 기본 2% + 정상보다 6도 넘게 뜨거워지면 올라감
        defect_rate = 0.02 + 0.012 * np.clip(excess_temp - 6, 0, None)
        defect_rate = np.clip(defect_rate, 0, 0.35)
        defect = rng.binomial(total, defect_rate)
        good = total - defect

        # --- 작업지시: 설비마다 48시간 단위로 1건 ---
        wo_index = np.arange(n) // WO_HOURS + 1
        wo_ids = np.array([f"WO-{equip_id}-{k:03d}" for k in wo_index])
        for b in range(n // WO_HOURS):
            wo_rows.append(
                (
                    f"WO-{equip_id}-{b + 1:03d}",
                    equip_id,
                    PRODUCTS[line_id][b % 2],
                    planned * WO_HOURS,
                    hours[b * WO_HOURS],
                    hours[(b + 1) * WO_HOURS - 1],
                    "완료",
                )
            )

        production_parts.append(
            pd.DataFrame(
                {
                    "equip_id": equip_id,
                    "wo_id": wo_ids,
                    "ts": hours,
                    "planned_qty": planned,
                    "good_qty": good,
                    "defect_qty": defect,
                    "run_minutes": run_minutes,
                }
            )
        )
        sensor_parts.append(
            pd.DataFrame(
                {"equip_id": equip_id, "ts": hours, "temperature": temp, "vibration": vib, "current_a": cur}
            )
        )

        # --- 비가동 사유: 멈춘 시간마다 사유를 붙임 ---
        for k in np.where(run_minutes < 60)[0]:
            if maint[k]:
                reason, planned_flag = "계획 정비", True
            else:
                reason, planned_flag = rng2.choice(DOWNTIME_REASONS, p=DOWNTIME_PROBS), False
            downtime_rows.append((equip_id, hours[k], 60.0 - run_minutes[k], str(reason), planned_flag))

        # --- 불량 유형: 불량이 난 시간마다 유형별로 나눔 ---
        types = DEFECT_TYPES[line_id]
        for k in np.where(defect > 0)[0]:
            weights = [0.4, 0.3, 0.3]
            if equip_id == "M04" and excess_temp[k] > 6:
                weights = [0.75, 0.20, 0.05]  # 과열되면 용접 비드 불량이 대부분
            counts = rng2.multinomial(int(defect[k]), weights)
            for t, c in zip(types, counts):
                if c > 0:
                    defect_rows.append((equip_id, hours[k], t, int(c)))

    production = pd.concat(production_parts, ignore_index=True)
    sensor = pd.concat(sensor_parts, ignore_index=True)

    # --- 현실처럼 지저분하게 만들기 (데이터 청소 연습용) ---
    err = rng.random(len(sensor)) < 0.004
    sensor.loc[err, "temperature"] = -999  # 센서 오류 코드
    nan = rng.random(len(sensor)) < 0.003
    sensor.loc[nan, "vibration"] = np.nan  # 값이 비어 있음
    dup = production.sample(5, random_state=SEED)
    production = pd.concat([production, dup], ignore_index=True)  # 중복 기록 5건

    return {
        "equipment": pd.DataFrame(EQUIPMENT, columns=["equip_id", "line_id", "name", "planned_qty_per_hour"]),
        "work_order": pd.DataFrame(
            wo_rows, columns=["wo_id", "equip_id", "product", "planned_qty", "start_ts", "end_ts", "status"]
        ),
        "production": production,
        "sensor": sensor,
        "downtime": pd.DataFrame(downtime_rows, columns=["equip_id", "ts", "minutes", "reason", "is_planned"]),
        "defect_detail": pd.DataFrame(defect_rows, columns=["equip_id", "ts", "defect_type", "qty"]),
    }


def save_to_db(tables, engine=None):
    """테이블을 새로 만들고(기존 것은 삭제) 데이터를 넣습니다."""
    engine = engine or db.get_engine()
    if engine.dialect.name == "sqlite":
        Path("data").mkdir(exist_ok=True)

    db.metadata.drop_all(engine)  # 다시 실행하면 새로 만듭니다
    db.metadata.create_all(engine)

    # 외래키(FK) 순서: 부모 테이블(equipment, work_order)을 먼저 넣습니다
    for name in ["equipment", "work_order", "production", "sensor", "downtime", "defect_detail"]:
        tables[name].to_sql(name, engine, if_exists="append", index=False, chunksize=1000)


if __name__ == "__main__":
    data = make_data()
    engine = db.get_engine()
    save_to_db(data, engine)
    print(f"저장 완료: {engine.url.render_as_string(hide_password=True)}")
    print(
        f"  설비 {len(data['equipment'])}대 / 작업지시 {len(data['work_order'])}건 / "
        f"생산 기록 {len(data['production'])}건 / 센서 기록 {len(data['sensor'])}건 / "
        f"비가동 {len(data['downtime'])}건 / 불량 상세 {len(data['defect_detail'])}건"
    )
