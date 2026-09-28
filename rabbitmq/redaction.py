"""Sensitive-data redaction for user-log event envelopes.

Keys whose values must never leave the API boundary. Mirrors the Log Service
(``app/security.py``) key set so both sides agree on what is sensitive.
"""

from typing import Any

# Keys whose values must never be published to RabbitMQ / persisted.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "password_hash",
        "access_token",
        "refresh_token",
        "token",
        "authorization",
        "auth",
        "jwt",
        "api_key",
        "apikey",
        "api-key",
        "client_secret",
        "api_secret",
        "secret",
        "db_password",
        "database_password",
        "credit_card",
        "card_number",
        "cvv",
        "cvc",
        "ssn",
        "id_number",
        "pin",
    }
)

_REDACTED = "[REDACTED]"


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in SENSITIVE_KEYS


def redact_sensitive_data(value: Any) -> Any:
    """Recursively replace values of sensitive keys with "[REDACTED]".

    Works on nested dicts and lists. Non-sensitive values are left untouched.
    """
    if isinstance(value, dict):
        return {
            k: (_REDACTED if _is_sensitive_key(str(k)) else redact_sensitive_data(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    return value