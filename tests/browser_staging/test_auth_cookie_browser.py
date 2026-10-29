"""The refresh cookie in a real browser (Phase 45, item 5).

Chromium (Playwright) on a page of http://localhost:5173 against a staging
API at http://localhost:<port> whose AUTH_COOKIE_ORIGINS is
http://localhost:5173. Over http the cookie is bc_refresh, Secure: the
browser keeps a Secure cookie from http://localhost (a secure context) but
refuses a __Host- one there (InvalidPrefix); production is https and
__Host-bc_refresh. Then: login -> reload (the access token is gone)
-> refresh by the cookie -> /auth/me -> logout -> refresh is 401. A page of
http://localhost:5174 (CORS yes, AUTH_COOKIE_ORIGINS no) is 403
CSRF_REJECTED although the browser sends it the cookie (same site).

Opt-in, never against production or the permanent staging:

    BROWSER_API_URL=http://localhost:8200 BROWSER_SA_USERNAME=e2e_sa \\
    BROWSER_SA_PASSWORD_FILE=~/p45-staging/sa_password \\
    python -m pytest --noconftest -m browser_staging tests/browser_staging
"""
from __future__ import annotations

import functools
import os
import threading
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser_staging

COOKIE = "bc_refresh"  # the API over http://localhost
PAGES = {5173: "allowed", 5174: "cors only"}


@pytest.fixture(scope="module")
def api() -> str:
    url = os.environ.get("BROWSER_API_URL", "")
    parts = urlsplit(url)
    if parts.hostname != "localhost" or parts.port in (None, 8000, 8100):
        pytest.exit(f"BROWSER_API_URL must be http://localhost:<staging port> (never 8000/8100): {url!r}", 2)
    return url


@dataclass(frozen=True)
class Login:
    username: str
    password: str = field(repr=False)  # never in a traceback

    def args(self) -> list[str]:
        return [self.username, self.password]


@pytest.fixture(scope="module")
def admin() -> Login:
    path = Path(os.environ["BROWSER_SA_PASSWORD_FILE"]).expanduser()
    return Login(os.environ["BROWSER_SA_USERNAME"], path.read_text(encoding="utf-8").strip())


@pytest.fixture(scope="module")
def pages():
    handler = functools.partial(_Quiet, directory=str(Path(__file__).parent))
    servers = [ThreadingHTTPServer(("127.0.0.1", port), handler) for port in PAGES]
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


def _login(page, admin: Login) -> dict:
    r = page.evaluate("([u, p]) => bc.login(u, p)", admin.args())
    if r["status"] == 200:
        r["body"]["data"]["access_token"] = "(masked)"
    return r


def _cookie(context) -> dict | None:
    return next((c for c in context.cookies() if c["name"] == COOKIE), None)


def test_login_reload_refresh_logout(browser, api, admin):
    context = browser.new_context()
    page = _open(context, api, 5173)

    r = _login(page, admin)
    assert r["status"] == 200, r
    assert "refresh_token" not in r["body"]["data"]
    cookie = _cookie(context)
    assert cookie is not None, context.cookies()
    assert (cookie["httpOnly"], cookie["secure"], cookie["sameSite"], cookie["path"]) == (True, True, "Strict", "/")
    assert cookie["domain"] == "localhost"  # host-only: no Domain attribute
    assert COOKIE not in page.evaluate("document.cookie")  # HttpOnly: the script cannot read it

    page.reload()
    assert page.evaluate("bc.hasAccess()") is False  # the access token was in memory only
    r = page.evaluate("bc.refresh()")
    assert r["status"] == 200, r
    assert "refresh_token" not in r["body"]["data"]
    rotated = _cookie(context)
    assert rotated is not None and rotated["value"] != cookie["value"]
    r = page.evaluate("bc.me()")
    assert (r["status"], r["body"]["data"]["username"]) == (200, admin.username), r

    r = page.evaluate("bc.logout()")
    assert r["status"] == 204, r
    assert _cookie(context) is None
    r = page.evaluate("bc.refresh()")
    assert (r["status"], r["body"]["code"]) == (401, "REFRESH_TOKEN_MISSING"), r
    context.close()


def test_another_origin_of_the_site_is_csrf_rejected(browser, api, admin):
    context = browser.new_context()
    allowed = _open(context, api, 5173)
    assert _login(allowed, admin)["status"] == 200
    before = _cookie(context)["value"]

    other = _open(context, api, 5174)  # same site (localhost), so the browser sends the cookie
    r = other.evaluate("bc.refresh()")
    assert (r["status"], r["body"]["code"]) == (403, "CSRF_REJECTED"), r
    assert _cookie(context)["value"] == before

    # the allowed page goes on with its cookie
    assert allowed.evaluate("bc.refresh()")["status"] == 200
    assert allowed.evaluate("bc.logout()")["status"] == 204
    context.close()
