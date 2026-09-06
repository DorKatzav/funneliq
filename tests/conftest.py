"""Shared test fixtures: a FastAPI test client with auth + database dependencies overridden.

Tests never talk to Supabase. `authed_client` replaces the JWT check with a fixed
test user and the Supabase client with a small in-memory fake.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user
from app.db import get_user_client
from app.main import create_app

TEST_USER = UserContext(user_id="00000000-0000-0000-0000-000000000001", email="test@example.com", token="x")


class _Result:
    def __init__(self, data, count):
        self.data, self.count = data, count


class FakeQuery:
    """Mimics the chainable postgrest query builder for the calls our routers make."""

    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._start, self._end = 0, len(rows) - 1

    def select(self, *_, **__):
        return self

    def order(self, *_, **__):
        return self

    def range(self, start: int, end: int):
        self._start, self._end = start, end
        return self

    def limit(self, n: int):
        self._end = self._start + n - 1
        return self

    def execute(self):
        return _Result(self._rows[self._start : self._end + 1], len(self._rows))


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self.tables.get(name, []))


@pytest.fixture
def fake_rows() -> list[dict]:
    return [{"id": i, "ad_budget": 500 * (i + 1), "referred": i % 2 == 0} for i in range(7)]


@pytest.fixture
def client() -> TestClient:
    """Plain client: no overrides, so protected routes behave as in production (401 without a token)."""
    return TestClient(create_app())


@pytest.fixture
def authed_client(fake_rows) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    app.dependency_overrides[get_user_client] = lambda: FakeSupabase({"funnel_records": fake_rows})
    return TestClient(app)
