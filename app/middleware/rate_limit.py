"""Rate limiting (slowapi already declared in requirements.txt)."""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config.settings import settings

limiter = Limiter(key_func=get_remote_address)
limiter.enabled = settings.RATE_LIMIT_ENABLED