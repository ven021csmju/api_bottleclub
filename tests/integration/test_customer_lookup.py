"""POST /customers/lookup (Phase 49 item 1): a service key finds ONE customer
of its organization by an exact LINE sub, email or phone, never a list; the
list GET /customers/ refuses every key (staff only)."""
import logging

import pytest

import pytest
from sqlalchemy import func, select

from app.db.models import Customer, CustomerAccount, CustomerIdentity, Organization, ServiceKey
from app.shared.security import create_access_token
from scripts import service_keys as cli

pytestmark = pytest.mark.integration

LOOKUP = "/api/v1/customers/lookup"
SCOPES = ["customers.lookup", "customers.create", "loyalty.read"]
SUB = "U" + "a1" * 16
FIELDS = {"id", "display_name", "loyalty_points_balance"}


def _h(raw):
    return {"X-Service-Key": raw}


@pytest.fixture()
def key(session, seed_org):
    return cli.create(session, "storefront", seed_org, SCOPES)[1]


@pytest.fixture()
def somchai(session, seed_org):
    customer = Customer(organization_id=seed_org, first_name="สมชาย", last_name="ทดสอบ",
                        phone="081-234-5678", email="Somchai@Example.TEST", loyalty_points_balance=120)
    session.add(customer)
    session.flush()
    account = CustomerAccount(organization_id=seed_org, customer_id=customer.id)
    session.add(account)
    session.flush()
    session.add(CustomerIdentity(customer_account_id=account.id, provider="line", provider_subject=SUB))
    session.flush()
    return customer.id


@pytest.mark.parametrize("body", [
    {"line_sub": SUB},
    {"email": "somchai@example.test"},
    {"email": "SOMCHAI@example.TEST"},
    {"phone": "0812345678"},
    {"phone": "+66 81 234 5678"},
    {"phone": "(081) 234-5678"},
    {"line_sub": SUB, "email": "somchai@example.test", "phone": "0812345678"},
])
def test_one_customer_by_an_exact_identifier(client, key, somchai, body):
    resp = client.post(LOOKUP, json=body, headers=_h(key))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert set(data) == FIELDS  # never the phone, email or birth date
    assert data == {"id": somchai, "display_name": "สมชาย ทดสอบ", "loyalty_points_balance": 120}


@pytest.mark.parametrize("body", [
    {"line_sub": "U" + "0" * 32},
    {"email": "nobody@example.test"},
    {"phone": "0899999999"},
    {"line_sub": SUB, "phone": "0899999999"},  # every identifier must name it
])
def test_not_found_is_404(client, key, somchai, body):
    resp = client.post(LOOKUP, json=body, headers=_h(key))
    assert resp.status_code == 404
    assert {k: resp.json()[k] for k in ("detail", "code")} == {"detail": "Customer not found", "code": "NOT_FOUND"}


def test_more_than_one_is_409_never_a_list(client, session, seed_org, key, somchai):
    # Phone is unique per organization; email is not.
    session.add(Customer(organization_id=seed_org, first_name="Twin", email="somchai@example.test"))
    session.flush()
    resp = client.post(LOOKUP, json={"email": "somchai@example.test"}, headers=_h(key))
    assert resp.status_code == 409 and resp.json()["code"] == "CUSTOMER_AMBIGUOUS"
    assert "data" not in resp.json()
    # Narrowed to one by another identifier: found.
    resp = client.post(LOOKUP, json={"email": "somchai@example.test", "phone": "0812345678"}, headers=_h(key))
    assert resp.status_code == 200 and resp.json()["data"]["id"] == somchai


@pytest.mark.parametrize("body", [
    {},
    {"line_sub": None, "email": None, "phone": None},
    {"email": "%@example.test"},
    {"email": "*"},
    {"email": "somchai@*"},
    {"email": "somchai"},
    {"phone": "081234"},          # a part of the number
    {"phone": "081-234-%"},
    {"phone": "08123456789012"},  # longer than a number
    {"line_sub": "U*"},
    {"line_sub": SUB[:-2]},
    {"first_name": "สมชาย"},       # not an identifier
])
def test_no_identifier_or_a_pattern_is_422(client, key, somchai, body):
    resp = client.post(LOOKUP, json=body, headers=_h(key))
    assert resp.status_code == 422, (body, resp.text)


def test_another_organizations_customer_is_not_found(client, session, key, somchai):
    other = Organization(name="Other", slug="other-org")
    session.add(other)
    session.flush()
    session.add(Customer(organization_id=other.id, first_name="Theirs", phone="0866666666", email="t@other.test"))
    session.flush()
    theirs = cli.create(session, "theirs", other.id, SCOPES)[1]
    for body in ({"phone": "0866666666"}, {"email": "t@other.test"}):
        assert client.post(LOOKUP, json=body, headers=_h(key)).status_code == 404
    # And our customer (with our LINE identity) is not theirs.
    for body in ({"phone": "0812345678"}, {"line_sub": SUB}):
        assert client.post(LOOKUP, json=body, headers=_h(theirs)).status_code == 404


def test_a_deleted_customer_is_not_found(client, session, key, somchai):
    from datetime import datetime, timezone

    session.get(Customer, somchai).deleted_at = datetime.now(timezone.utc)
    session.flush()
    assert client.post(LOOKUP, json={"phone": "0812345678"}, headers=_h(key)).status_code == 404


def test_a_key_without_the_scope_is_403(client, session, seed_org, somchai):
    raw = cli.create(session, "create-only", seed_org, ["customers.create"])[1]
    resp = client.post(LOOKUP, json={"phone": "0812345678"}, headers=_h(raw))
    assert resp.status_code == 403 and resp.json()["code"] == "SERVICE_KEY_SCOPE"


def test_only_a_key(client, seed_user, staff_headers, somchai):
    assert client.post(LOOKUP, json={"phone": "0812345678"}).status_code == 401
    assert client.post(LOOKUP, json={}).status_code == 401  # no key and a bad body: 401
    resp = client.post(LOOKUP, json={"phone": "0812345678"}, headers=staff_headers)
    assert resp.status_code == 401 and resp.json()["code"] == "UNAUTHORIZED" and resp.json()["detail"] == "Service key required"
    assert client.post(LOOKUP, json={"phone": "0812345678"}, headers=_h("bcsk_wrong")).status_code == 401


def test_the_list_refuses_every_key(client, session, seed_org, key, somchai, staff_headers, seed_user):
    from tests.integration.conftest import grant

    resp = client.get("/api/v1/customers/", headers=_h(key))
    assert resp.status_code == 403 and resp.json()["code"] == "SERVICE_KEY_SCOPE"
    assert resp.json()["detail"] == "Service keys may not use this route"
    grant(session, seed_user["user_id"], seed_user["org_id"], ["customers.read"], seed_user["branch_id"])
    token = create_access_token(seed_user["user_id"], seed_user["org_id"], [], [seed_user["branch_id"]])
    staff = {"Authorization": f"Bearer {token}", "X-Branch-Id": str(seed_user["branch_id"])}
    assert client.get("/api/v1/customers/", headers=staff).status_code == 200  # staff as before


def test_an_old_customers_read_key_is_refused(client, session, seed_org, somchai):
    """A key given customers.read before 025 (the CLI refuses it now)."""
    with pytest.raises(SystemExit):
        cli.create(session, "old", seed_org, ["customers.read"])
    raw = cli.new_key()
    from app.shared.security import hash_token

    session.add(ServiceKey(organization_id=seed_org, name="old", key_prefix=raw[:12], key_hash=hash_token(raw),
                           scopes=["customers.read", "customers.create"]))
    session.flush()
    for resp in (client.get("/api/v1/customers/", headers=_h(raw)),
                 client.post("/api/v1/customers/", json={"first_name": "X"}, headers=_h(raw)),
                 client.post(LOOKUP, json={"phone": "0812345678"}, headers=_h(raw))):
        assert resp.status_code == 401 and resp.json()["code"] == "SERVICE_KEY_RETIRED", resp.text


def test_create_answers_the_lookup_fields_to_a_key(client, key, staff_headers, session, seed_user):
    from tests.integration.conftest import grant

    resp = client.post("/api/v1/customers/", json={"first_name": "Shop", "phone": "0811111111",
                                                    "email": "shop@example.test"}, headers=_h(key))
    assert resp.status_code == 201 and set(resp.json()["data"]) == FIELDS
    grant(session, seed_user["user_id"], seed_user["org_id"], ["customers.create"], seed_user["branch_id"])
    token = create_access_token(seed_user["user_id"], seed_user["org_id"], [], [seed_user["branch_id"]])
    staff = {"Authorization": f"Bearer {token}", "X-Branch-Id": str(seed_user["branch_id"])}
    resp = client.post("/api/v1/customers/", json={"first_name": "Desk", "phone": "0822222222"}, headers=staff)
    assert resp.status_code == 201 and resp.json()["data"]["phone"] == "0822222222"  # staff: full record


def test_every_lookup_is_logged_without_the_values(client, session, key, somchai, caplog):
    key_id = session.scalar(select(ServiceKey.id))
    with caplog.at_level(logging.INFO, logger="app.domains.customers.service"):
        client.post(LOOKUP, json={"phone": "0812345678"}, headers=_h(key))
        client.post(LOOKUP, json={"email": "nobody@example.test"}, headers=_h(key))
    lines = [r.getMessage() for r in caplog.records if r.name == "app.domains.customers.service"]
    assert lines == [f"customer lookup service_key={key_id} org={session.get(Customer, somchai).organization_id}"
                     f" by=phone result=found",
                     f"customer lookup service_key={key_id} org={session.get(Customer, somchai).organization_id}"
                     f" by=email result=not_found"]
    text = "\n".join(caplog.text.splitlines())
    assert "0812345678" not in text and "nobody@example.test" not in text and "081-234-5678" not in text


def test_rate_limited_per_key(client, session, seed_org, key, somchai):
    from app.config.settings import settings
    from app.middleware.rate_limit import limiter

    other = cli.create(session, "other", seed_org, SCOPES)[1]
    limit = int(settings.RATE_LIMIT_CUSTOMER_LOOKUP.split("/")[0])
    limiter.reset()
    limiter.enabled = True
    try:
        answers = [client.post(LOOKUP, json={"phone": "0812345678"}, headers=_h(key)).status_code
                   for _ in range(limit + 1)]
        theirs = client.post(LOOKUP, json={"phone": "0812345678"}, headers=_h(other)).status_code
    finally:
        limiter.enabled = False
        limiter.reset()
    assert answers[:limit] == [200] * limit and answers[limit] == 429
    assert theirs == 200  # same IP, its own bucket


# POST /customers/ with a key: the storefront's lookup → 404 → create never
# makes a second customer (else every later lookup would be 409).
def _create(client, key, **body):
    return client.post("/api/v1/customers/", json={"first_name": "Shop", **body}, headers=_h(key))


EXISTING = {"id", "display_name", "loyalty_points_balance"}


@pytest.mark.parametrize("body", [
    {"email": "SOMCHAI@example.test"},
    {"email": " somchai@EXAMPLE.test "},
    {"phone": "0812345678"},          # 081-234-5678 as stored
    {"phone": "+66 81 234 5678"},
    {"email": "new@example.test", "phone": "(081) 234-5678"},  # any identifier
])
def test_a_key_creates_no_duplicate(client, session, key, somchai, body):
    before = session.scalar(select(func.count()).select_from(Customer))
    resp = _create(client, key, **body)
    assert resp.status_code == 409 and resp.json()["code"] == "CUSTOMER_EXISTS", resp.text
    assert resp.json()["customer"] == {"id": somchai, "display_name": "สมชาย ทดสอบ", "loyalty_points_balance": 120}
    assert set(resp.json()["customer"]) == EXISTING
    assert session.scalar(select(func.count()).select_from(Customer)) == before


def test_twice_in_a_row_is_one_customer(client, session, key, seed_org):
    first = _create(client, key, email="once@example.test", phone="0855555555")
    again = _create(client, key, email="ONCE@example.test")
    assert first.status_code == 201 and again.status_code == 409
    assert again.json()["customer"]["id"] == first.json()["data"]["id"]
    found = client.post(LOOKUP, json={"email": "once@example.test"}, headers=_h(key))
    assert found.status_code == 200 and found.json()["data"]["id"] == first.json()["data"]["id"]


def test_deleted_or_another_organizations_customer_is_no_duplicate(client, session, key, seed_org, somchai):
    from datetime import datetime, timezone

    other = Organization(name="Other", slug="other-org")
    session.add(other)
    session.flush()
    session.add(Customer(organization_id=other.id, first_name="Theirs", email="theirs@example.test"))
    session.get(Customer, somchai).deleted_at = datetime.now(timezone.utc)
    session.flush()
    assert _create(client, key, email="theirs@example.test").status_code == 201
    assert _create(client, key, email="somchai@example.test").status_code == 201


def test_a_key_must_send_a_whole_phone(client, key, seed_org):
    assert _create(client, key, phone="0812").status_code == 422
    assert _create(client, key, phone="a@b.test").status_code == 422


def test_staff_creates_as_before(client, session, somchai, seed_user):
    """Staff: the duplicate check is the stored phone only, as before Phase 49."""
    from tests.integration.conftest import grant

    grant(session, seed_user["user_id"], seed_user["org_id"], ["customers.create"], seed_user["branch_id"])
    token = create_access_token(seed_user["user_id"], seed_user["org_id"], [], [seed_user["branch_id"]])
    staff = {"Authorization": f"Bearer {token}", "X-Branch-Id": str(seed_user["branch_id"])}
    resp = client.post("/api/v1/customers/", json={"first_name": "Desk", "email": "somchai@example.test"},
                       headers=staff)
    assert resp.status_code == 201 and resp.json()["data"]["email"] == "somchai@example.test"


@pytest.mark.parametrize("second", [{"email": "Twice@Example.test"}, {"phone": "+66 87 777 7777"}])
def test_two_requests_at_once_make_one_customer(db_engine, monkeypatch, second):
    """Two committed sessions at once (a double click): the second waits for the
    first's lock and commit, then answers it. The add is slowed so that,
    without the lock, both would have checked before either inserted."""
    import threading
    import time
    from sqlalchemy.orm import Session as OrmSession

    from app.db.repositories.customers import CustomerRepository
    from app.domains.customers.service import CustomerService
    from app.shared.exceptions import AppException

    with OrmSession(db_engine) as setup:
        org = Organization(name="Race", slug="race-org")
        setup.add(org)
        setup.commit()
        org_id = org.id
    add = CustomerRepository.add_customer

    def slow_add(db, customer):
        time.sleep(0.5)
        add(db, customer)

    monkeypatch.setattr(CustomerRepository, "add_customer", staticmethod(slow_add))
    barrier = threading.Barrier(2)
    results = []

    def create(body):
        with OrmSession(db_engine) as db:
            barrier.wait()
            try:
                results.append(("created", CustomerService.create_for_service_key(
                    db, org_id, 1, first_name="Race", **body).id))
            except AppException as exc:
                results.append((exc.code, exc.extra["customer"]["id"]))

    threads = [threading.Thread(target=create, args=(body,))
               for body in ({"email": "twice@example.test", "phone": "0877777777"}, second)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        with OrmSession(db_engine) as check:
            ids = check.scalars(select(Customer.id).where(Customer.organization_id == org_id)).all()
        assert len(ids) == 1, results
        assert sorted(r[0] for r in results) == ["CUSTOMER_EXISTS", "created"]
        assert {r[1] for r in results} == set(ids)
    finally:
        with OrmSession(db_engine) as cleanup:
            cleanup.execute(Customer.__table__.delete().where(Customer.organization_id == org_id))
            cleanup.execute(Organization.__table__.delete().where(Organization.id == org_id))
            cleanup.commit()
