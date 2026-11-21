"""X-Service-Key: a server's key reaches only the routes of its scopes, in its
organization; staff logins on the same routes work as before."""
import pytest
from sqlalchemy import select

from app.db.models import Customer, Organization, ServiceKey
from app.shared.security import create_access_token
from scripts import service_keys as cli

ALL = ["customers.read", "customers.create", "loyalty.read"]


@pytest.fixture()
def key(session, seed_org):
    _, raw = cli.create(session, "storefront", seed_org, ALL)
    return raw


def _h(raw):
    return {"X-Service-Key": raw}


def test_the_key_is_stored_as_a_hash_only(session, key):
    row = session.scalar(select(ServiceKey))
    assert key.startswith("bcsk_") and len(key) > 40
    assert row.key_hash != key and key not in row.key_hash
    assert row.key_prefix == key[:12] and row.scopes == sorted(ALL)


def test_list_create_and_balance_with_the_key(client, session, key, seed_org):
    created = client.post("/api/v1/customers/", json={"first_name": "Shop", "phone": "0811111111"}, headers=_h(key))
    assert created.status_code == 201, created.text
    customer_id = created.json()["data"]["id"]
    assert session.get(Customer, customer_id).organization_id == seed_org

    listed = client.get("/api/v1/customers/", headers=_h(key))
    assert listed.status_code == 200 and [c["id"] for c in listed.json()["data"]["customers"]] == [customer_id]

    balance = client.get(f"/api/v1/loyalty/balance/{customer_id}", headers=_h(key))
    assert balance.status_code == 200, balance.text


def test_a_scope_is_needed_per_route(client, session, seed_org):
    _, raw = cli.create(session, "read-only", seed_org, ["customers.read"])
    assert client.get("/api/v1/customers/", headers=_h(raw)).status_code == 200
    resp = client.post("/api/v1/customers/", json={"first_name": "X"}, headers=_h(raw))
    assert resp.status_code == 403 and resp.json()["code"] == "SERVICE_KEY_SCOPE"
    assert client.get("/api/v1/loyalty/balance/1", headers=_h(raw)).status_code == 403


@pytest.mark.parametrize("path", [
    "/api/v1/customers/1",                 # not one of its routes, even with customers.read
    "/api/v1/loyalty/transactions/1",
    "/api/v1/orders/",
    "/api/v1/users/",
    "/api/v1/auth/me",
])
def test_no_other_route_takes_a_key(client, key, path):
    assert client.get(path, headers=_h(key)).status_code == 401


def test_a_revoked_or_wrong_key_is_401(client, session, key):
    assert client.get("/api/v1/customers/", headers=_h(key + "x")).status_code == 401
    cli.revoke(session, session.scalar(select(ServiceKey.id)))
    resp = client.get("/api/v1/customers/", headers=_h(key))
    assert resp.status_code == 401 and resp.json()["code"] == "INVALID_SERVICE_KEY"


def test_another_organizations_customers_are_not_seen(client, session, key):
    other = Organization(name="Other", slug="other-org")
    session.add(other)
    session.flush()
    session.add(Customer(organization_id=other.id, first_name="Theirs"))
    session.flush()
    theirs = session.scalar(select(Customer.id).where(Customer.organization_id == other.id))

    assert client.get("/api/v1/customers/", headers=_h(key)).json()["data"]["customers"] == []
    assert client.get(f"/api/v1/loyalty/balance/{theirs}", headers=_h(key)).status_code == 404


def test_staff_still_use_these_routes(client, session, seed_user, key):
    from tests.integration.conftest import grant

    grant(session, seed_user["user_id"], seed_user["org_id"], ["customers.read"], seed_user["branch_id"])
    token = create_access_token(seed_user["user_id"], seed_user["org_id"], [], [seed_user["branch_id"]])
    headers = {"Authorization": f"Bearer {token}", "X-Branch-Id": str(seed_user["branch_id"])}
    assert client.get("/api/v1/customers/", headers=headers).status_code == 200
    assert client.post("/api/v1/customers/", json={"first_name": "X"}, headers=headers).status_code == 403
    assert client.get("/api/v1/customers/").status_code == 401
    # No token and a bad body: still 401 first (Phase 40).
    assert client.post("/api/v1/customers/", json={}).status_code == 401
    # A valid key and a bad body: the body's 422; a wrong key: 401 first.
    assert client.post("/api/v1/customers/", json={}, headers=_h(key)).status_code == 422
    assert client.post("/api/v1/customers/", json={}, headers=_h("bcsk_x")).status_code == 401


def test_last_used_is_recorded(client, session, key):
    client.get("/api/v1/customers/", headers=_h(key))
    assert session.scalar(select(ServiceKey.last_used_at)) is not None


def test_cli_refuses_unknown_scopes(session, seed_org):
    with pytest.raises(SystemExit):
        cli.create(session, "x", seed_org, ["users.read"])
    with pytest.raises(SystemExit):
        cli.create(session, "x", seed_org, [])


def test_cli_listing_never_shows_the_key(session, key):
    text = "\n".join(cli.listing(session))
    assert key not in text and key[:12] in text and "active" in text


def test_cli_writes_the_key_once_to_a_600_file(tmp_path):
    out = tmp_path / "key.txt"
    cli._write_once(out, "bcsk_test")
    assert out.read_text() == "bcsk_test\n" and (out.stat().st_mode & 0o777) == 0o600
    with pytest.raises(FileExistsError):
        cli._write_once(out, "bcsk_other")
