from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from backend import database

# 테스트용 PostgreSQL 주소. 테스트마다 빈 스키마를 새로 만들어 쓰고 끝나면 지운다 (DB 의 다른 데이터는 건드리지 않음).
#   $env:HELLOPUPPY_TEST_DATABASE_URL = "postgresql://postgres:비밀번호@127.0.0.1:5432/postgres"
TEST_DATABASE_URL = os.getenv("HELLOPUPPY_TEST_DATABASE_URL", "")


@pytest.fixture(autouse=True)
def isolated_media_dir(tmp_path, monkeypatch):
    """Photos saved during a test go to a temporary folder, never to backend/data/media."""
    monkeypatch.setenv("HELLOPUPPY_MEDIA_DIR", str(tmp_path / "media"))


@pytest.fixture
def postgres(monkeypatch):
    """Point the app at a fresh, empty PostgreSQL schema for this test."""
    if not TEST_DATABASE_URL:
        message = "HELLOPUPPY_TEST_DATABASE_URL 이 없어 PostgreSQL 이 필요한 테스트를 건너뜁니다."
        if os.getenv("CI"):
            pytest.fail(message)  # CI 에서는 건너뛰지 않고 실패로 알린다
        pytest.skip(message)
    schema = f"test_{uuid.uuid4().hex[:16]}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    monkeypatch.setenv("HELLOPUPPY_DATABASE_URL", make_conninfo(TEST_DATABASE_URL, options=f"-c search_path={schema}"))
    try:
        yield schema
    finally:
        database.close_pool()
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
