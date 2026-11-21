"""LINE Login for customers on the test database; LINE itself is faked at the
HTTP layer (httpx), so the status/claim checks of app/domains/auth/line.py run.

A customer is found by LINE's ``sub`` only, the callback hands the frontend a
one-time code (never a token in a URL), POST /auth/exchange trades it once
for a customer token, and customer and staff tokens never cross.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import func, select

from app.config.settings import settings
from app.db.models import AuthExchangeCode, Customer, CustomerAccount, CustomerIdentity
from app.domains.auth import line
from app.shared.security import create_access_token, create_customer_access_token, hash_token

FRONTEND = "http://localhost:3000/auth/line/done"
OTHER_FRONTEND = "https://shop.example.test/auth/line/done"
CLIENT_ID = "1650000000"
STATE, NONCE = "state-value", "nonce-value"


@pytest.fixture()
def line_env(monkeypatch, seed_org):
    monkeypatch.setattr(settings, "LINE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "LINE_CLIENT_SECRET", "line-secret-for-tests")
    monkeypatch.setattr(settings, "LINE_REDIRECT_URI", "http://testserver/api/v1/auth/line/callback")
    monkeypatch.setattr(settings, "LINE_DEFAULT_ORGANIZATION_ID", seed_org)
    monkeypatch.setattr(settings, "FRONTEND_URLS", f"{FRONTEND},{OTHER_FRONTEND}")
    monkeypatch.setattr(settings, "CUSTOMER_JWT_SECRET_KEY", "c" * 40)
    return seed_org


class FakeLine:
    """LINE's token and verify endpoints; tests change the answers."""

    def __init__(self):
        self.claims = {"iss": line.LINE_ISSUER, "aud": CLIENT_ID, "sub": "U" + "1" * 32,
                       "nonce": NONCE, "name": "คุณทดสอบ", "email": "Line.User@Example.test"}
        self.token_status = 200
        self.verify_status = 200
        self.token_body: object = {"access_token": "at", "id_token": "id-token", "token_type": "Bearer"}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == line.TOKEN_URL:
            return httpx.Response(self.token_status, json=self.token_body)
        if str(request.url) == line.VERIFY_URL:
            return httpx.Response(self.verify_status, json=self.claims)
        return httpx.Response(404)


@pytest.fixture()
def fake_line(monkeypatch, line_env):
    fake = FakeLine()
    real_client = httpx.Client

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(line.httpx, "Client", client)
    return fake


def _callback(client, query=f"code=auth-code&state={STATE}", return_to=FRONTEND):
    path = "/api/v1/auth/line"
    for name, value in (("line_oauth_state", STATE), ("line_oauth_nonce", NONCE), ("line_oauth_return", return_to)):
        client.cookies.set(name, value, path=path)
    try:
        return client.get(f"{path}/callback?{query}", follow_redirects=False)
    finally:
        client.cookies.clear()


def _redirect(resp):
    assert resp.status_code == 302, resp.text
    loc = urlsplit(resp.headers["location"])
    return f"{loc.scheme}://{loc.netloc}{loc.path}", {k: v[0] for k, v in parse_qs(loc.query).items()}


def _login(client, fake_line):
    target, params = _redirect(_callback(client))
    assert target == FRONTEND and set(params) == {"code"}
    return params["code"]


class TestStart:
    def test_not_configured_is_400(self, client, monkeypatch):
        monkeypatch.setattr(settings, "LINE_CLIENT_ID", None)
        resp = client.get("/api/v1/auth/line", follow_redirects=False)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "LINE Login is not configured"

    def test_redirects_to_line_with_state_and_cookies(self, client, line_env):
        resp = client.get("/api/v1/auth/line", follow_redirects=False)

        assert resp.status_code == 302
        loc = urlsplit(resp.headers["location"])
        assert f"{loc.scheme}://{loc.netloc}{loc.path}" == line.AUTHORIZE_URL
        q = {k: v[0] for k, v in parse_qs(loc.query).items()}
        assert q["scope"] == "profile openid email"
        assert q["client_id"] == CLIENT_ID and q["response_type"] == "code"
        assert q["redirect_uri"] == settings.LINE_REDIRECT_URI
        assert len(q["state"]) >= 32 and len(q["nonce"]) >= 32
        cookies = resp.headers.get_list("set-cookie")
        assert any(c.startswith(f"line_oauth_state={q['state']};") for c in cookies)
        assert any(c.startswith(f'line_oauth_return="{FRONTEND}";') for c in cookies)  # quoted: has ":" and "/"
        assert all("HttpOnly" in c and "Path=/api/v1/auth/line" in c for c in cookies)
        assert "line-secret-for-tests" not in resp.headers["location"]

    def test_return_to_must_be_one_of_frontend_urls(self, client, line_env):
        ok = client.get(f"/api/v1/auth/line?return_to={OTHER_FRONTEND}", follow_redirects=False)
        assert ok.status_code == 302
        assert any(OTHER_FRONTEND in c for c in ok.headers.get_list("set-cookie"))
        for bad in ("https://evil.example.test/auth/line/done", FRONTEND + "/../x", FRONTEND + "?a=1"):
            resp = client.get("/api/v1/auth/line", params={"return_to": bad}, follow_redirects=False)
            assert resp.status_code == 400, bad
            assert resp.json()["code"] == "RETURN_TO_NOT_ALLOWED"


class TestRoundTrip:
    def test_start_then_callback_with_the_cookies_the_api_set(self, client, session, fake_line):
        start = client.get(f"/api/v1/auth/line?return_to={OTHER_FRONTEND}", follow_redirects=False)
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        fake_line.claims["nonce"] = parse_qs(urlsplit(start.headers["location"]).query)["nonce"][0]

        resp = client.get(f"/api/v1/auth/line/callback?code=auth-code&state={state}", follow_redirects=False)
        client.cookies.clear()

        target, params = _redirect(resp)
        assert target == OTHER_FRONTEND and set(params) == {"code"}
        assert client.post("/api/v1/auth/exchange", json={"code": params["code"]}).status_code == 200


class TestCallback:
    def test_first_login_creates_a_customer_by_sub_with_the_line_email(self, client, session, fake_line):
        code = _login(client, fake_line)

        identity = session.scalar(select(CustomerIdentity))
        assert (identity.provider, identity.provider_subject) == ("line", fake_line.claims["sub"])
        account = session.get(CustomerAccount, identity.customer_account_id)
        customer = session.get(Customer, account.customer_id)
        assert customer.first_name == "คุณทดสอบ" and customer.email == "line.user@example.test"
        # The account's login email stays empty: LINE's address never becomes one.
        assert account.email is None and account.password_hash is None
        assert identity.email_at_link == "line.user@example.test"
        stored = session.scalar(select(AuthExchangeCode))
        assert stored.code_hash == hash_token(code) and stored.customer_account_id == account.id
        assert code not in str(stored.code_hash)

    def test_no_email_is_kept_as_null_never_made_up(self, client, session, fake_line):
        del fake_line.claims["email"]
        _login(client, fake_line)

        customer = session.scalar(select(Customer))
        assert customer.email is None
        assert session.scalar(select(CustomerIdentity.email_at_link)) is None

    def test_second_login_same_sub_is_the_same_customer(self, client, session, fake_line):
        _login(client, fake_line)
        fake_line.claims["email"] = "changed@example.test"
        fake_line.claims["name"] = "ชื่อใหม่"
        _login(client, fake_line)

        assert session.scalar(select(func.count()).select_from(CustomerAccount)) == 1
        assert session.scalar(select(func.count()).select_from(Customer)) == 1

    def test_same_email_other_sub_is_another_customer(self, client, session, fake_line, seed_org):
        # A walk-in customer with the address LINE gives: never linked by email.
        session.add(Customer(organization_id=seed_org, first_name="Walk-in", email="line.user@example.test"))
        session.flush()
        _login(client, fake_line)

        assert session.scalar(select(func.count()).select_from(Customer)) == 2
        account = session.scalar(select(CustomerAccount))
        assert session.get(Customer, account.customer_id).first_name == "คุณทดสอบ"

    def test_state_mismatch_returns_an_error_and_no_code(self, client, session, fake_line):
        target, params = _redirect(_callback(client, query="code=auth-code&state=other"))

        assert target == FRONTEND and params == {"error": "line_state_invalid"}
        assert fake_line.requests == []  # LINE never called
        assert session.scalar(select(func.count()).select_from(CustomerAccount)) == 0

    def test_cancelled_at_line(self, client, fake_line):
        _, params = _redirect(_callback(client, query=f"error=access_denied&state={STATE}"))
        assert params == {"error": "line_login_cancelled"}

    def test_no_return_cookie_is_401(self, client, fake_line):
        client.cookies.set("line_oauth_state", STATE, path="/api/v1/auth/line")
        resp = client.get(f"/api/v1/auth/line/callback?code=c&state={STATE}", follow_redirects=False)
        assert resp.status_code == 401

    def test_a_forged_return_cookie_is_401(self, client, fake_line):
        resp = _callback(client, return_to="https://evil.example.test/")
        assert resp.status_code == 401
        assert fake_line.requests == []

    @pytest.mark.parametrize("change", [
        {"token_status": 400},
        {"token_status": 500},
        {"token_body": {"access_token": "at"}},           # no id_token
        {"token_body": ["not", "an", "object"]},
        {"verify_status": 400},
        {"claims": {"aud": "someone-else"}},
        {"claims": {"iss": "https://evil.example.test"}},
        {"claims": {"nonce": "other-nonce"}},
        {"claims": {"sub": ""}},
    ])
    def test_any_bad_answer_from_line_is_an_error_redirect(self, client, session, fake_line, change):
        for name, value in change.items():
            if name == "claims":
                fake_line.claims.update(value)
            else:
                setattr(fake_line, name, value)

        _, params = _redirect(_callback(client))

        assert params == {"error": "line_login_failed"}
        assert session.scalar(select(func.count()).select_from(CustomerAccount)) == 0
        assert session.scalar(select(func.count()).select_from(AuthExchangeCode)) == 0

    def test_verify_is_sent_the_nonce_and_client_id(self, client, fake_line):
        _login(client, fake_line)
        verify = next(r for r in fake_line.requests if str(r.url) == line.VERIFY_URL)
        form = parse_qs(verify.content.decode())
        assert form["client_id"] == [CLIENT_ID] and form["nonce"] == [NONCE] and form["id_token"] == ["id-token"]

    def test_cookies_are_cleared_and_not_cached(self, client, fake_line):
        resp = _callback(client)
        assert resp.headers["cache-control"] == "no-store"
        cleared = [c for c in resp.headers.get_list("set-cookie") if "Max-Age=0" in c]
        assert len(cleared) == 3


class TestExchange:
    def test_a_code_works_once_for_a_customer_token(self, client, fake_line):
        code = _login(client, fake_line)

        first = client.post("/api/v1/auth/exchange", json={"code": code})
        again = client.post("/api/v1/auth/exchange", json={"code": code})

        assert first.status_code == 200, first.text
        body = first.json()["data"]
        assert body["token_type"] == "bearer" and body["audience"] == "customer"
        assert body["expires_in"] == settings.CUSTOMER_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        assert again.status_code == 401 and again.json()["code"] == "INVALID_EXCHANGE_CODE"

        me = client.get("/api/v1/customer/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200, me.text
        assert me.json()["data"]["first_name"] == "คุณทดสอบ" and me.json()["data"]["providers"] == ["line"]

    def test_an_expired_code_is_refused(self, client, session, fake_line):
        code = _login(client, fake_line)
        row = session.scalar(select(AuthExchangeCode))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.flush()

        resp = client.post("/api/v1/auth/exchange", json={"code": code})
        assert resp.status_code == 401 and resp.json()["detail"] == "Invalid or expired code"

    def test_the_code_lives_the_configured_seconds(self, client, session, fake_line):
        before = datetime.now(timezone.utc)
        _login(client, fake_line)
        row = session.scalar(select(AuthExchangeCode))
        assert timedelta(0) < row.expires_at - before <= timedelta(seconds=settings.AUTH_EXCHANGE_CODE_TTL_SECONDS + 5)

    def test_an_unknown_code_is_refused(self, client, line_env):
        resp = client.post("/api/v1/auth/exchange", json={"code": "not-a-code"})
        assert resp.status_code == 401 and resp.json()["code"] == "INVALID_EXCHANGE_CODE"


class TestTokensNeverCross:
    def test_a_customer_token_is_not_a_staff_token(self, client, session, fake_line, seed_user):
        code = _login(client, fake_line)
        token = client.post("/api/v1/auth/exchange", json={"code": code}).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}", "X-Branch-Id": str(seed_user["branch_id"])}

        for path in ("/api/v1/auth/me", "/api/v1/orders/", "/api/v1/customers/"):
            assert client.get(path, headers=headers).status_code == 401, path

    def test_a_staff_token_is_not_a_customer_token(self, client, line_env, seed_user):
        staff = create_access_token(seed_user["user_id"], seed_user["org_id"], [], [])
        resp = client.get("/api/v1/customer/me", headers={"Authorization": f"Bearer {staff}"})
        assert resp.status_code == 401

    def test_a_customer_token_of_a_locked_account_is_refused(self, client, session, fake_line):
        code = _login(client, fake_line)
        token = client.post("/api/v1/auth/exchange", json={"code": code}).json()["data"]["access_token"]
        session.scalar(select(CustomerAccount)).status = "locked"
        session.flush()

        assert client.get("/api/v1/customer/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401

    def test_a_locked_account_cannot_sign_in(self, client, session, fake_line):
        _login(client, fake_line)
        session.scalar(select(CustomerAccount)).status = "locked"
        session.flush()

        _, params = _redirect(_callback(client))
        assert params == {"error": "line_login_failed"}

    def test_no_token_is_401(self, client, line_env):
        assert client.get("/api/v1/customer/me").status_code == 401

    def test_customer_token_helpers_need_the_key(self, monkeypatch):
        monkeypatch.setattr(settings, "CUSTOMER_JWT_SECRET_KEY", None)
        with pytest.raises(RuntimeError):
            create_customer_access_token(1, 1)
