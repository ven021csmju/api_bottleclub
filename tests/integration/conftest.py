"""Database-backed fixtures for integration tests.

Every test runs inside an outer transaction on a dedicated, disposable
PostgreSQL database. The Session joins it with
``join_transaction_mode="create_savepoint"``, so services that call
``commit()`` / ``rollback()`` themselves only release / roll back a SAVEPOINT
and nothing outlives the test.

The schema is (re)created once per pytest session and dropped at the end,
but only after ``_validated_test_database_url`` has confirmed the target is a
local, explicitly opted-in ``*_test`` database. Any failed check aborts the
whole run via ``pytest.exit`` before a single statement is executed.
"""
from __future__ import annotations

import os
from typing import Generator, NoReturn

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import Session

from app.shared.security import create_access_token, hash_password

_ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
_FORBIDDEN_ENVIRONMENTS = {"production", "staging"}


# ---------------------------------------------------------------------------
# Destructive-operation guard
# ---------------------------------------------------------------------------
def _abort(reason: str) -> NoReturn:
    pytest.exit(f"Refusing to use the test database: {reason}", returncode=3)


def _parse_url(raw: str, label: str) -> URL:
    try:
        return make_url(raw)
    except Exception:
        # Never echo the raw value: it may contain a password.
        _abort(f"{label} is not a valid SQLAlchemy URL")


def _same_database(a: URL, b: URL) -> bool:
    return (
        (a.host or "").lower() == (b.host or "").lower()
        and (a.port or 5432) == (b.port or 5432)
        and a.database == b.database
    )


def _validated_test_database_url() -> URL:
    from app.config.settings import settings

    raw = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not raw:
        _abort("TEST_DATABASE_URL must be set explicitly in the environment (no fallback)")

    url = _parse_url(raw, "TEST_DATABASE_URL")
    safe = url.render_as_string(hide_password=True)

    if url.get_backend_name() != "postgresql":
        _abort(f"dialect must be postgresql ({safe})")
    if (url.host or "").lower() not in _ALLOWED_HOSTS:
        _abort(f"host must be one of {sorted(_ALLOWED_HOSTS)} ({safe})")
    if not (url.database or "").endswith("_test"):
        _abort(f"database name must end with '_test' ({safe})")

    for label, candidate in (
        ("settings.DATABASE_URL", settings.DATABASE_URL),
        ("DATABASE_URL", os.environ.get("DATABASE_URL", "")),
    ):
        if candidate and _same_database(url, _parse_url(candidate, label)):
            _abort(f"TEST_DATABASE_URL points at the application database ({safe})")

    environments = {settings.ENVIRONMENT, os.environ.get("ENVIRONMENT", "")}
    if {env.strip().lower() for env in environments} & _FORBIDDEN_ENVIRONMENTS:
        _abort("ENVIRONMENT must not be production or staging")

    if os.environ.get("ALLOW_DESTRUCTIVE_TEST_DB") != "1":
        _abort("set ALLOW_DESTRUCTIVE_TEST_DB=1 to allow create_all()/drop_all()")

    return url


# ---------------------------------------------------------------------------
# Engine / session / client
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def db_engine() -> Generator[Engine, None, None]:
    from app.db.models import Base

    url = _validated_test_database_url()
    engine = create_engine(url, pool_pre_ping=True)
    # Start from a clean schema in case a previous run crashed before teardown.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def session(db_engine: Engine) -> Generator[Session, None, None]:
    connection = db_engine.connect()
    transaction = connection.begin()
    db_session = Session(
        bind=connection,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield db_session
    finally:
        db_session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(session: Session, rate_limit_disabled: None) -> Generator[TestClient, None, None]:
    """TestClient whose ``get_db`` dependency yields the per-test session."""
    from app.db.session import get_db
    from app.main import create_app

    def _override_get_db():
        yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Seed data helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def seed_org(session: Session) -> int:
    from app.db.models import Organization

    org = Organization(name="Test Org", slug="test-org")
    session.add(org)
    session.flush()
    return org.id


@pytest.fixture()
def seed_branch(session: Session, seed_org: int) -> int:
    from app.db.models import Branch

    branch = Branch(
        organization_id=seed_org,
        name="Main Branch",
        code="MBR",
    )
    session.add(branch)
    session.flush()
    return branch.id


@pytest.fixture()
def seed_role_and_permission(session: Session, seed_org: int) -> dict:
    from app.db.models import Permission, Role, RolePermission

    role = Role(organization_id=seed_org, name="Admin", is_system=True)
    session.add(role)
    session.flush()

    perm_codes = [
        "orders.create",
        "orders.read",
        "orders.cancel",
        "orders.complete",
    ]
    perm_map: dict[str, int] = {}
    for code in perm_codes:
        perm = Permission(code=code, module="orders")
        session.add(perm)
        session.flush()
        perm_map[code] = perm.id
        session.add(RolePermission(role_id=role.id, permission_id=perm.id))

    session.flush()
    return {"role_id": role.id, "permissions": perm_map}


@pytest.fixture()
def seed_user(
    session: Session,
    seed_org: int,
    seed_branch: int,
    seed_role_and_permission: dict,
) -> dict:
    from app.db.models import User, UserRole

    user = User(
        organization_id=seed_org,
        username="testcashier",
        email="cashier@test.com",
        password_hash=hash_password("Test1234!"),
        display_name="Test Cashier",
        status="active",
    )
    session.add(user)
    session.flush()

    user_role = UserRole(
        user_id=user.id,
        role_id=seed_role_and_permission["role_id"],
        branch_id=seed_branch,
    )
    session.add(user_role)
    session.flush()

    return {
        "user_id": user.id,
        "org_id": seed_org,
        "branch_id": seed_branch,
        "username": "testcashier",
        "password": "Test1234!",
    }


@pytest.fixture()
def auth_headers(seed_user: dict) -> dict[str, str]:
    token = create_access_token(
        user_id=seed_user["user_id"],
        org_id=seed_user["org_id"],
        permissions=[
            "orders.create",
            "orders.read",
            "orders.cancel",
            "orders.complete",
        ],
        branches=[seed_user["branch_id"]],
    )
    return {"Authorization": f"Bearer {token}", "X-Branch-Id": str(seed_user["branch_id"])}


@pytest.fixture()
def staff_headers(seed_user: dict) -> dict[str, str]:
    token = create_access_token(
        user_id=seed_user["user_id"],
        org_id=seed_user["org_id"],
        permissions=[
            "orders.create",
            "orders.read",
            "orders.cancel",
            "orders.complete",
            "orders.update",
        ],
        branches=[seed_user["branch_id"]],
    )
    return {"Authorization": f"Bearer {token}", "X-Branch-Id": str(seed_user["branch_id"])}
