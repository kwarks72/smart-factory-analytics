"""
DB 연결과 테이블 설계(스키마)

- 환경변수 DATABASE_URL이 있으면 그 DB(예: PostgreSQL)를, 없으면 SQLite 파일을 씁니다.
    SQLite     : sqlite:///data/factory.db            (기본값, 설치 필요 없음)
    PostgreSQL : postgresql+psycopg2://사용자:비밀번호@주소:5432/DB이름
- 테이블 정의는 SQLAlchemy로 한 번만 써 두면 SQLite·PostgreSQL 양쪽에서 똑같이 만들어집니다.

테이블 관계 (MES에서 흔한 구조를 단순화):

  equipment 1 ──< work_order      작업지시: 어떤 설비가 어떤 제품을 몇 개 만들라고 지시받았나
  equipment 1 ──< production      생산실적: 시간대별 양품/불량/가동시간 (work_order에 연결)
  equipment 1 ──< sensor          센서: 온도·진동·전류
  equipment 1 ──< downtime        비가동: 멈춘 시간과 사유
  equipment 1 ──< defect_detail   불량 상세: 불량 유형별 수량
"""

import os

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
)

DEFAULT_URL = "sqlite:///data/factory.db"

metadata = MetaData()

equipment = Table(
    "equipment",
    metadata,
    Column("equip_id", String(10), primary_key=True),
    Column("line_id", String(10), nullable=False),
    Column("name", String(50), nullable=False),
    Column("planned_qty_per_hour", Integer, nullable=False),
)

work_order = Table(
    "work_order",
    metadata,
    Column("wo_id", String(30), primary_key=True),
    Column("equip_id", String(10), ForeignKey("equipment.equip_id"), nullable=False),
    Column("product", String(30), nullable=False),
    Column("planned_qty", Integer, nullable=False),
    Column("start_ts", DateTime, nullable=False),
    Column("end_ts", DateTime, nullable=False),
    Column("status", String(10), nullable=False),
)

production = Table(
    "production",
    metadata,
    Column("record_id", Integer, primary_key=True, autoincrement=True),
    Column("equip_id", String(10), ForeignKey("equipment.equip_id"), nullable=False),
    Column("wo_id", String(30), ForeignKey("work_order.wo_id"), nullable=False),
    Column("ts", DateTime, nullable=False),
    Column("planned_qty", Integer, nullable=False),
    Column("good_qty", Integer, nullable=False),
    Column("defect_qty", Integer, nullable=False),
    Column("run_minutes", Float, nullable=False),
)

sensor = Table(
    "sensor",
    metadata,
    Column("equip_id", String(10), ForeignKey("equipment.equip_id"), nullable=False),
    Column("ts", DateTime, nullable=False),
    Column("temperature", Float),  # 오류·빈 값이 올 수 있어 NULL 허용
    Column("vibration", Float),
    Column("current_a", Float),
)

downtime = Table(
    "downtime",
    metadata,
    Column("downtime_id", Integer, primary_key=True, autoincrement=True),
    Column("equip_id", String(10), ForeignKey("equipment.equip_id"), nullable=False),
    Column("ts", DateTime, nullable=False),
    Column("minutes", Float, nullable=False),
    Column("reason", String(30), nullable=False),
    Column("is_planned", Boolean, nullable=False),
)

defect_detail = Table(
    "defect_detail",
    metadata,
    Column("defect_id", Integer, primary_key=True, autoincrement=True),
    Column("equip_id", String(10), ForeignKey("equipment.equip_id"), nullable=False),
    Column("ts", DateTime, nullable=False),
    Column("defect_type", String(30), nullable=False),
    Column("qty", Integer, nullable=False),
)


def get_engine():
    """DB 연결 통로(engine)를 만듭니다."""
    return create_engine(os.getenv("DATABASE_URL", DEFAULT_URL))
