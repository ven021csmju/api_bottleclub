"""RabbitMQ user-log event envelope (Phase 4).

The envelope is the stable message format exchanged between the Main Backend
and the User Log Worker. Validation reuses the project conventions:

- ``event_id`` is a UUID, normalised to a string.
- ``timestamp`` is timezone-aware; naive input is treated as UTC.
- ``data`` must not carry sensitive values (same key list as the Log Service
  redaction) - secrets are rejected at the boundary before they can ever be
  published. The field is still passed through redaction defensively when
  mapped to a Log Service item.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rabbitmq.redaction import _is_sensitive_key, redact_sensitive_data


def utc_now() -> datetime:
    """Timezone-aware UTC now (matches app.models convention)."""
    return datetime.now(timezone.utc)


def _validate_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("event_id must be a valid UUID") from exc


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ensure_no_sensitive_data(data: Dict[str, Any]) -> None:
    """Reject payloads whose data tree contains sensitive keys (recursive)."""

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                if _is_sensitive_key(str(key)):
                    raise ValueError(f"sensitive key '{str(key)}' is not allowed in event data")
                walk(value, path + (str(key),))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, path + (f"[{index}]",))

    walk(data, ())


class UserLogEvent(BaseModel):
    """Stable event envelope published to the ``user_logs`` exchange."""

    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str
    event_type: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    source: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    customer_id: Optional[str] = None
    request_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    data: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id")
    @classmethod
    def _validate_event_id(cls, value: str) -> str:
        return _validate_uuid(value)

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, value: datetime) -> datetime:
        return _normalize_timestamp(value)

    @model_validator(mode="after")
    def _reject_sensitive_data(self) -> "UserLogEvent":
        ensure_no_sensitive_data(self.data)
        return self

    def to_log_service_item(self) -> dict:
        """Map the envelope onto the Log Service ``/api/logs/user/batch`` item schema."""
        return {
            "user_id": self.user_id,
            "action": self.event_type,
            "request_id": self.request_id,
            "event_id": self.event_id,
            "created_at": self.timestamp.isoformat(),
            "metadata": redact_sensitive_data(self.data),
        }

    def safe_log_fields(self) -> dict:
        """Fields safe to include in logs (never the message body)."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "request_id": self.request_id,
            "source": self.source,
            "user_id": self.user_id,
        }