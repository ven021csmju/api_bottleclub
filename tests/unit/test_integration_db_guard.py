"""The integration-test database guard refuses anything but the test cluster port."""
import pytest

from tests.integration import conftest as guard

GOOD = "postgresql+psycopg://u:p@127.0.0.1:55432/bottle_club_phase22_test"


@pytest.fixture()
def opted_in(monkeypatch):
    monkeypatch.setenv("ALLOW_DESTRUCTIVE_TEST_DB", "1")
    monkeypatch.delenv("TEST_DB_ALLOWED_PORTS", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(guard_settings(), "DATABASE_URL", "postgresql+psycopg://none:none@127.0.0.1:1/none_dev")
    monkeypatch.setattr(guard_settings(), "ENVIRONMENT", "test")


def guard_settings():
    from app.config.settings import settings

    return settings


def test_port_55432_is_accepted(monkeypatch, opted_in):
    monkeypatch.setenv("TEST_DATABASE_URL", GOOD)
    assert guard._validated_test_database_url().port == 55432


@pytest.mark.parametrize("port", ["5432", "5433"])
def test_dev_and_prod_ports_are_refused(monkeypatch, opted_in, port):
    monkeypatch.setenv("TEST_DATABASE_URL", GOOD.replace(":55432/", f":{port}/"))
    with pytest.raises(pytest.exit.Exception, match="port must be one of"):
        guard._validated_test_database_url()


def test_default_port_is_refused(monkeypatch, opted_in):
    monkeypatch.setenv("TEST_DATABASE_URL", GOOD.replace(":55432/", "/"))
    with pytest.raises(pytest.exit.Exception, match="port must be one of"):
        guard._validated_test_database_url()


def test_allowed_ports_can_be_configured(monkeypatch, opted_in):
    monkeypatch.setenv("TEST_DB_ALLOWED_PORTS", "55433")
    monkeypatch.setenv("TEST_DATABASE_URL", GOOD)
    with pytest.raises(pytest.exit.Exception):
        guard._validated_test_database_url()
    monkeypatch.setenv("TEST_DATABASE_URL", GOOD.replace(":55432/", ":55433/"))
    assert guard._validated_test_database_url().port == 55433
