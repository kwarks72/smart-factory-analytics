"""
테스트 공통 준비

테스트는 "진짜 DB"를 건드리지 않도록, 임시 폴더에 SQLite 파일을 새로 만들어서 씁니다.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def test_db(tmp_path_factory):
    """테스트 시작 전에 임시 DB를 만들고 시뮬레이션 데이터를 채웁니다."""
    path = tmp_path_factory.mktemp("db") / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"

    import generate_data

    generate_data.save_to_db(generate_data.make_data())
    return path


@pytest.fixture(scope="session")
def client(test_db):
    """API를 서버 없이 바로 호출해 볼 수 있는 가짜 손님"""
    from fastapi.testclient import TestClient

    import api

    return TestClient(api.app)
