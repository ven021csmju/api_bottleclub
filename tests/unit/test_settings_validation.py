"""Configuration validation tests.

These tests instantiate ``Settings`` directly and assert validation failures
for insecure placeholder / missing values. The tests themselves do not import
``app.db.session`` or connect to any database or external service. Note that
pytest still loads ``tests/conftest.py``, whose fixtures import application
modules lazily; importing ``app.db.session`` creates an engine object but
never opens a connection.
"""

from pydantic import ValidationError
import pytest

from app.config.settings import Settings

_LOCAL_DEV_DATABASE_URL = (
    "postgresql+psycopg://postgres:postgres@localhost:5432/bottle_club_dev"
)

_SECURE_JWT = "a-very-secure-secret-key-that-is-long-enough-32"
_PROD_DB_URL = "postgresql+psycopg://user:pass@prod-host:5432/prod_db"


def _make_settings(**overrides) -> Settings:
    # Production needs CORS_ORIGINS since Phase 44 (tests/unit/test_cors_origins.py).
    return Settings(**{"CORS_ORIGINS": "https://pos.example.com", **overrides})


def test_production_rejects_dev_database_default():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        _make_settings(
            ENVIRONMENT="production",
            DATABASE_URL=_LOCAL_DEV_DATABASE_URL,
            JWT_SECRET_KEY=_SECURE_JWT,
        )


def test_staging_rejects_dev_database_default():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        _make_settings(
            ENVIRONMENT="staging",
            DATABASE_URL=_LOCAL_DEV_DATABASE_URL,
            JWT_SECRET_KEY=_SECURE_JWT,
        )


def test_production_rejects_old_jwt_placeholder():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        _make_settings(
            ENVIRONMENT="production",
            DATABASE_URL=_PROD_DB_URL,
            JWT_SECRET_KEY="change-me-in-production",
        )


def test_production_rejects_new_jwt_placeholder():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        _make_settings(
            ENVIRONMENT="production",
            DATABASE_URL=_PROD_DB_URL,
            JWT_SECRET_KEY="change-me-to-a-long-random-string-at-least-32-characters",
        )


def test_staging_rejects_old_jwt_placeholder():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        _make_settings(
            ENVIRONMENT="staging",
            DATABASE_URL=_PROD_DB_URL,
            JWT_SECRET_KEY="change-me-in-production",
        )


def test_development_allows_placeholder_jwt():
    # Known limitation: placeholder JWT accepted when ENVIRONMENT=development.
    # This does NOT protect a production host accidentally set to development.
    settings = _make_settings(
        ENVIRONMENT="development",
        DATABASE_URL=_LOCAL_DEV_DATABASE_URL,
        JWT_SECRET_KEY="change-me-in-production",
    )
    assert settings.JWT_SECRET_KEY == "change-me-in-production"


def test_development_allows_dev_database_default():
    settings = _make_settings(
        ENVIRONMENT="development",
        DATABASE_URL=_LOCAL_DEV_DATABASE_URL,
        JWT_SECRET_KEY=_SECURE_JWT,
    )
    assert settings.DATABASE_URL == _LOCAL_DEV_DATABASE_URL


def test_production_rejects_short_jwt():
    with pytest.raises(ValidationError, match="32 characters"):
        _make_settings(
            ENVIRONMENT="production",
            DATABASE_URL=_PROD_DB_URL,
            JWT_SECRET_KEY="short",
        )


def test_staging_rejects_short_jwt():
    with pytest.raises(ValidationError, match="32 characters"):
        _make_settings(
            ENVIRONMENT="staging",
            DATABASE_URL=_PROD_DB_URL,
            JWT_SECRET_KEY="short",
        )


def test_production_accepts_valid_config():
    settings = _make_settings(
        ENVIRONMENT="production",
        DATABASE_URL=_PROD_DB_URL,
        JWT_SECRET_KEY=_SECURE_JWT,
    )
    assert settings.ENVIRONMENT == "production"
    assert settings.JWT_SECRET_KEY == _SECURE_JWT


def test_case_insensitive_environment():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        _make_settings(
            ENVIRONMENT="Production",
            DATABASE_URL=_LOCAL_DEV_DATABASE_URL,
            JWT_SECRET_KEY=_SECURE_JWT,
        )


@pytest.mark.parametrize(
    "environment, value, expected",
    [
        ("production", None, False),
        ("staging", None, False),
        ("development", None, False),
        ("test", None, False),
        ("production", True, True),
        ("development", False, False),
        ("test", False, False),
    ],
)
def test_registration_default_is_closed_in_production(environment, value, expected):
    overrides = {"ENVIRONMENT": environment, "REGISTRATION_ENABLED": value}
    if environment in {"production", "staging"}:
        overrides.update(JWT_SECRET_KEY=_SECURE_JWT, DATABASE_URL=_PROD_DB_URL)
    assert _make_settings(**overrides).registration_enabled is expected
