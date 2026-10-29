"""The refresh cookie in a real browser (Phase 45, item 5; one per web, 45b).

Chromium (Playwright) on pages of http://localhost:5173 and :5174 (both in
AUTH_COOKIE_ORIGINS) and :5175 (CORS_ORIGINS only) against a staging API at
http://localhost:<port>. Over http the cookie is bc_refresh_<id>, Secure: the
browser keeps a Secure cookie from http://localhost (a secure context) but
refuses a __Host- one there (InvalidPrefix); production is https and
__Host-bc_refresh_<id>. ``id``: the first 8 hex of sha256(the web's origin).

- one web: login -> reload (the access token is gone) -> refresh by the
  cookie -> /auth/me -> logout -> refresh is 401;
- two webs in one browser, two accounts: each refreshes as its own account;
  a logout in one leaves the other;
- a web of CORS_ORIGINS only is 403 CSRF_REJECTED although the browser sends
  it the cookies (same site).

Opt-in, never against production or the permanent staging:

    BROWSER_API_URL=http://localhost:8200 BROWSER_SA_USERNAME=e2e_sa \\
    BROWSER_SA_PASSWORD_FILE=~/p45-staging/sa_password \\
    python -m pytest --noconftest -m browser_staging tests/browser_staging
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import secrets
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser_staging

POS, ADMIN, CORS_ONLY = 5173, 5174, 5175


def _cookie_of(port: int) -> str:
    """The cookie of the web on that port (the API over http://localhost)."""
    return "bc_refresh_" + hashlib.sha256(f"http://localhost:{port}".encode()).hexdigest()[:8]


@dataclass(frozen=True)
class Login:
    username: str
    password: str = field(repr=False)  # never in a traceback

    def args(self) -> list[str]:
        return [self.username, self.password]


@pytest.fixture(scope="module")
def api() -> str:
    url = os.environ.get("BROWSER_API_URL", "")
    parts = urlsplit(url)
    if parts.hostname != "localhost" or parts.port in (None, 8000, 8100):
        pytest.exit(f"BROWSER_API_URL must be http://localhost:<staging port> (never 8000/8100): {url!r}", 2)
    return url


@pytest.fixture(scope="module")
def admin() -> Login:
    path = Path(os.environ["BROWSER_SA_PASSWORD_FILE"]).expanduser()
    return Login(os.environ["BROWSER_SA_USERNAME"], path.read_text(encoding="utf-8").strip())


def _post(api: str, path: str, body: dict, token: str | None = None) -> dict:
    """A script's call (body mode, no Origin)."""
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    request = urllib.request.Request(f"{api}/api/v1{path}", json.dumps(body).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return json.loads(resp.read())["data"]
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"{path}: {exc.code} {json.loads(exc.read()).get('code')}") from None


@pytest.fixture(scope="module")
def manager(api: str, admin: Login) -> Login:
    """A second account, made by the Superadmin; its first password changed."""
    sa = _post(api, "/auth/login", {"username": admin.username, "password": admin.password})["access_token"]
    name = f"p45b_mgr_{secrets.token_hex(3)}"
    temporary = _post(api, "/users/", {"username": name, "email": f"{name}@e2e.example.com",
                                       "display_name": "P45b Manager", "roles": []}, sa)["temporary_password"]
    first = _post(api, "/auth/login", {"username": name, "password": temporary})["access_token"]
    password = secrets.token_urlsafe(18)
    _post(api, "/auth/change-password", {"current_password": temporary, "new_password": password}, first)
    return Login(name, password)


@pytest.fixture(scope="module")
def pages():
    handler = functools.partial(_Quiet, directory=str(Path(__file__).parent))
    servers = [ThreadingHTTPServer(("127.0.0.1", port), handler) for port in (POS, ADMIN, CORS_ONLY)]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield
    for server in servers:
        server.shutdown()
        server.server_close()


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


@pytest.fixture()
def browser(pages):
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open(context, api: str, port: int):
    page = context.new_page()
    page.goto(f"http://localhost:{port}/page.html?api={api}")
    return page


def _login(page, who: Login) -> dict:
    r = page.evaluate("([u, p]) => bc.login(u, p)", who.args())
    if r["status"] == 200:
        r["body"]["data"]["access_token"] = "(masked)"
    return r


def _cookie(context, port: int) -> dict | None:
    return next((c for c in context.cookies() if c["name"] == _cookie_of(port)), None)


def _me(page) -> str:
    r = page.evaluate("bc.refresh()")
    assert r["status"] == 200, r
    r = page.evaluate("bc.me()")
    assert r["status"] == 200, r
    return r["body"]["data"]["username"]


def test_login_reload_refresh_logout(browser, api, admin):
    context = browser.new_context()
    page = _open(context, api, POS)

    r = _login(page, admin)
    assert r["status"] == 200, r
    assert "refresh_token" not in r["body"]["data"]
    cookie = _cookie(context, POS)
    assert cookie is not None, [c["name"] for c in context.cookies()]
    assert (cookie["httpOnly"], cookie["secure"], cookie["sameSite"], cookie["path"]) == (True, True, "Strict", "/")
    assert cookie["domain"] == "localhost"  # host-only: no Domain attribute
    assert "bc_refresh" not in page.evaluate("document.cookie")  # HttpOnly: the script cannot read it

    page.reload()
    assert page.evaluate("bc.hasAccess()") is False  # the access token was in memory only
    assert _me(page) == admin.username
    rotated = _cookie(context, POS)
    assert rotated is not None and rotated["value"] != cookie["value"]

    r = page.evaluate("bc.logout()")
    assert r["status"] == 204, r
    assert _cookie(context, POS) is None
    r = page.evaluate("bc.refresh()")
    assert (r["status"], r["body"]["code"]) == (401, "REFRESH_TOKEN_MISSING"), r
    context.close()


def test_two_webs_two_accounts_in_one_browser(browser, api, admin, manager):
    context = browser.new_context()  # one browser: one cookie jar
    pos, office = _open(context, api, POS), _open(context, api, ADMIN)
    assert _login(pos, admin)["status"] == 200
    assert _login(office, manager)["status"] == 200
    assert _cookie(context, POS) and _cookie(context, ADMIN)

    pos.reload()
    office.reload()
    assert _me(pos) == admin.username      # v0.1.20: the manager's session (one shared cookie)
    assert _me(office) == manager.username
    assert _me(pos) == admin.username

    assert pos.evaluate("bc.logout()")["status"] == 204
    assert _cookie(context, POS) is None and _cookie(context, ADMIN) is not None
    r = pos.evaluate("bc.refresh()")
    assert (r["status"], r["body"]["code"]) == (401, "REFRESH_TOKEN_MISSING"), r
    assert _me(office) == manager.username
    assert office.evaluate("bc.logout()")["status"] == 204
    context.close()


def test_a_web_of_cors_only_is_csrf_rejected(browser, api, admin):
    context = browser.new_context()
    allowed = _open(context, api, POS)
    assert _login(allowed, admin)["status"] == 200
    before = _cookie(context, POS)["value"]

    other = _open(context, api, CORS_ONLY)  # same site (localhost): the browser sends it the cookies
    r = other.evaluate("bc.refresh()")
    assert (r["status"], r["body"]["code"]) == (403, "CSRF_REJECTED"), r
    r = _login(other, admin)
    assert (r["status"], r["body"]["code"]) == (403, "CSRF_REJECTED"), r
    assert _cookie(context, POS)["value"] == before and _cookie(context, CORS_ONLY) is None

    assert allowed.evaluate("bc.refresh()")["status"] == 200  # the allowed web goes on with its cookie
    assert allowed.evaluate("bc.logout()")["status"] == 204
    context.close()
