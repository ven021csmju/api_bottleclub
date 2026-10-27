"""End-to-end flow against a running **staging** API (Phase 37).

Opt-in only: every test here is marked ``e2e_staging`` (pytest.ini excludes
the marker by default) and the run is refused unless ``E2E_BASE_URL`` names
a loopback staging server. Production (``:8000`` or the public domain) is
refused before any request is sent.

    E2E_BASE_URL=http://127.0.0.1:8100 \\
    E2E_SA_USERNAME=e2e_sa E2E_SA_PASSWORD_FILE=~/p38a-staging/sa_password \\
    E2E_RESULTS=~/p38a-staging/results.jsonl \\
    python -m pytest -p no:cacheprovider -m e2e_staging tests/e2e_staging

Each check is recorded (step, PASS/FAIL/NOTE, HTTP status, expected, actual)
in ``E2E_RESULTS`` as JSON lines; a test fails when any of its checks failed,
and later steps that need its result are skipped.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

PROD_HOSTS = ("wayneven.uk",)
PROD_PORTS = (8000,)
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    here = Path(__file__).resolve().parent
    for item in items:
        if here in Path(str(item.path)).resolve().parents:
            item.add_marker(pytest.mark.e2e_staging)


def staging_base_url() -> str:
    """``E2E_BASE_URL``, refused unless it is a loopback, non-production port."""
    raw = os.environ.get("E2E_BASE_URL", "").strip().rstrip("/")
    if not raw:
        pytest.exit("E2E_BASE_URL is not set (e.g. http://127.0.0.1:8100)", returncode=2)
    parts = urllib.parse.urlsplit(raw)
    host = (parts.hostname or "").lower()
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if any(host == h or host.endswith("." + h) for h in PROD_HOSTS):
        pytest.exit(f"REFUSED: {host} is production", returncode=2)
    if port in PROD_PORTS:
        pytest.exit(f"REFUSED: port {port} is production", returncode=2)
    if host not in LOOPBACK:
        pytest.exit(f"REFUSED: staging must be on loopback, got {host}", returncode=2)
    return raw


@dataclass
class Recorder:
    path: Path | None
    rows: list[dict] = field(default_factory=list)

    def _add(self, step: str, name: str, status: str, http: Any, expected: Any, actual: Any) -> None:
        row = {"step": step, "check": name, "status": status, "http": http,
               "expected": expected, "actual": actual}
        self.rows.append(row)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def check(self, step: str, name: str, ok: bool, expected: Any, actual: Any, http: Any = None) -> bool:
        self._add(step, name, "PASS" if ok else "FAIL", http, expected, actual)
        return ok

    def eq(self, step: str, name: str, expected: Any, actual: Any, http: Any = None) -> bool:
        return self.check(step, name, expected == actual, expected, actual, http)

    def note(self, step: str, name: str, actual: Any, http: Any = None, expected: Any = "-") -> None:
        """An observation the phase asks to record; neither pass nor fail."""
        self._add(step, name, "NOTE", http, expected, actual)

    def failed(self, step: str) -> list[dict]:
        return [r for r in self.rows if r["step"] == step and r["status"] == "FAIL"]

    def finish(self, step: str) -> None:
        bad = self.failed(step)
        if bad:
            pytest.fail("; ".join(f"{r['check']}: expected {r['expected']!r}, got {r['actual']!r}" for r in bad),
                        pytrace=False)


@pytest.fixture(scope="session")
def rec() -> Recorder:
    raw = os.environ.get("E2E_RESULTS", "").strip()
    path = Path(raw).expanduser() if raw else None
    if path and path.exists():
        path.unlink()
    return Recorder(path)


class Api:
    """httpx client that remembers each user's token and working branch."""

    def __init__(self, base_url: str) -> None:
        import httpx

        self.base = base_url
        self.http = httpx.Client(base_url=base_url, timeout=120)
        self.tokens: dict[str, str] = {}
        self.branch: dict[str, int | None] = {}

    def request(self, method: str, path: str, who: str | None = None, branch: Any = "default", **kw):
        headers = dict(kw.pop("headers", {}) or {})
        if who is not None:
            headers["Authorization"] = f"Bearer {self.tokens[who]}"
            b = self.branch.get(who) if branch == "default" else branch
            if b is not None:
                headers["X-Branch-Id"] = str(b)
        url = path if path.startswith("/api/") or path.startswith("/health") else "/api/v1" + path
        return self.http.request(method, url, headers=headers, **kw)

    def get(self, path, who=None, **kw):
        return self.request("GET", path, who, **kw)

    def post(self, path, who=None, **kw):
        return self.request("POST", path, who, **kw)

    def put(self, path, who=None, **kw):
        return self.request("PUT", path, who, **kw)

    def patch(self, path, who=None, **kw):
        return self.request("PATCH", path, who, **kw)

    def login(self, who: str, username: str, password: str):
        resp = self.post("/auth/login", json={"username": username, "password": password})
        if resp.status_code == 200:
            self.tokens[who] = resp.json()["data"]["access_token"]
        return resp


def data(resp) -> Any:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    return body.get("data", body) if isinstance(body, dict) else body


@pytest.fixture(scope="session")
def api() -> Api:
    client = Api(staging_base_url())
    yield client
    client.http.close()


@pytest.fixture(scope="session")
def flow() -> dict:
    """State shared by the steps, in order (a → l)."""
    return {}


@pytest.fixture(scope="session")
def sa_credentials() -> tuple[str, str]:
    user = os.environ.get("E2E_SA_USERNAME", "").strip()
    pw_file = os.environ.get("E2E_SA_PASSWORD_FILE", "").strip()
    if not user or not pw_file:
        pytest.exit("E2E_SA_USERNAME and E2E_SA_PASSWORD_FILE are required", returncode=2)
    return user, Path(pw_file).expanduser().read_text(encoding="utf-8").strip()


def needs(flow: dict, *keys: str) -> None:
    missing = [k for k in keys if k not in flow]
    if missing:
        pytest.skip(f"an earlier step did not produce {missing}")
