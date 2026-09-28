"""Tests for the MongoDB log service module.

These do NOT require the PostgreSQL test database.

Connection-dependent tests (insert/query/pagination/TTL) auto-skip when
MongoDB is unreachable (no tunnel open). Fail-silence tests always run and
must pass whether MongoDB is up or down.
"""

import asyncio
import time
from datetime import timedelta, timezone

import pytest

from app.db.mongodb import (
    close_connection,
    get_database,
    get_mongodb_health,
    log_search,
    log_system_event,
    log_user_activity,
)
from app.db.mongodb import repositories
from app.db.mongodb.client import get_client

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_mongo(monkeypatch):
    """Force every test to start from a clean client state."""
    close_connection()
    import app.db.mongodb.client as mc

    mc._next_retry_at = 0.0
    yield
    close_connection()


@pytest.fixture()
def mongo_up() -> bool:
    """True when MongoDB is reachable through the tunnel right now."""
    return get_mongodb_health()["status"] == "connected"


async def test_health_endpoint_shape():
    health = get_mongodb_health()
    assert set(health) >= {"status", "database", "uri"}
    assert health["status"] in {"connected", "disconnected"}
    assert health["database"] == "system_logs"


async def test_fail_silent_when_unreachable():
    """Logging must never raise, whether MongoDB is up or down."""
    results = await asyncio.gather(
        log_user_activity("u1", "login", ip_address="1.2.3.4"),
        log_search("u1", "wine"),
        log_system_event("EVENT", "pos", "info", "msg"),
    )
    assert all(r is None or isinstance(r, str) for r in results)


async def test_insert_and_query_user_log(mongo_up):
    if not mongo_up:
        pytest.skip("MongoDB unreachable (SSH tunnel not open)")
    uid = f"unit-{int(time.time() * 1000)}"
    inserted = await log_user_activity(
        uid, "login", ip_address="127.0.0.1", request_id=f"req-{uid}"
    )
    assert inserted is not None
    rows = repositories.query_user_logs(user_id=uid, limit=5, offset=0)
    assert len(rows) == 1
    assert rows[0]["action"] == "login"


async def test_insert_and_query_search_log(mongo_up):
    if not mongo_up:
        pytest.skip("MongoDB unreachable (SSH tunnel not open)")
    uid = f"unit-{int(time.time() * 1000)}"
    inserted = await log_search(uid, "red wine", filters={"category": "wine"}, result_count=20)
    assert inserted is not None
    rows = repositories.query_search_logs(user_id=uid, limit=5, offset=0)
    assert len(rows) == 1
    assert rows[0]["query"] == "red wine"
    assert rows[0]["result_count"] == 20


async def test_insert_and_query_system_event(mongo_up):
    if not mongo_up:
        pytest.skip("MongoDB unreachable (SSH tunnel not open)")
    inserted = await log_system_event(
        "UNIT_EVENT", "test", "info", "unit test event", metadata={"k": "v"}
    )
    assert inserted is not None
    rows = repositories.query_system_events(event_type="UNIT_EVENT", limit=5, offset=0)
    assert len(rows) >= 1
    assert rows[0]["severity"] == "info"


async def test_pagination(mongo_up):
    if not mongo_up:
        pytest.skip("MongoDB unreachable (SSH tunnel not open)")
    uid = f"pager-{int(time.time() * 1000)}"
    for i in range(3):
        await log_user_activity(uid, f"a{i}", request_id=f"r-{i}")
    total = repositories.query_user_logs(user_id=uid, limit=100, offset=0)
    assert len(total) == 3
    page1 = repositories.query_user_logs(user_id=uid, limit=2, offset=0)
    page2 = repositories.query_user_logs(user_id=uid, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1
    assert {r["action"] for r in page1 + page2} == {"a0", "a1", "a2"}


async def test_ttl_indexes_exist(mongo_up):
    if not mongo_up:
        pytest.skip("MongoDB unreachable (SSH tunnel not open)")
    db = get_database()
    assert db is not None
    expected = {
        "user_logs": ("user_logs_ttl", 90 * 86400),
        "search_logs": ("search_logs_ttl", 90 * 86400),
        "system_events": ("system_events_ttl", 180 * 86400),
    }
    for collection, (idx_name, seconds) in expected.items():
        info = db[collection].index_information()
        assert idx_name in info, f"{collection} missing {idx_name}"
        assert info[idx_name]["expireAfterSeconds"] == seconds


async def test_created_at_recorded():
    """Documents must carry a UTC created_at for the TTL index to work."""
    doc = repositories.insert_user_log("ttl-check", "login")
    if doc is None:
        pytest.skip("MongoDB unreachable (SSH tunnel not open)")
    row = repositories.query_user_logs(user_id="ttl-check", limit=1, offset=0)[0]
    assert row["created_at"].tzinfo is not None
    age = round((__import__("datetime").datetime.now(timezone.utc) - row["created_at"]).total_seconds())
    assert 0 <= age < 60