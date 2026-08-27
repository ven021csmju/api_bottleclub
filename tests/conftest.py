from __future__ import annotations

import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import settings
from app.db.session import get_db
from app.main import create_app
from app.db.models import Base
from app.shared.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Use a dedicated test database.  The env var TEST_DATABASE_URL can be set
# in CI or locally; fall back to a PostgreSQL URL that points at the docker
# postgres instance with a separate database name.
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/bottle_club_test",
)

engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Session fixture – creates tables, yields a session, drops everything after.
# ---------------------------------------------------------------------------
@pytest.fixture()
def session() -> Generator[Session, None, None]:
    Base.metadata.create_all(bind=engine)
    connection = engine.connect()
    transaction = connection.begin()
    db_session = TestSessionLocal(bind=connection)

    yield db_session

    db_session.close()
    transaction.rollback()
    connection.close()
    Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Client fixture – FastAPI TestClient wired to the test session.
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db():
        try:
            yield session
        finally:
            pass

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
