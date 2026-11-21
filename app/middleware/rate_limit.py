"""Rate limiting (slowapi already declared in requirements.txt).

Every limit is per client IP (``rate_limit_key``: CF-Connecting-IP from
cloudflared or Cloudflare's edge, else the peer), unless a route passes its
own key_func (POST /customers/lookup: per service key)."""
from __future__ import annotations

from slowapi import Limiter

from app.config.settings import settings
from app.middleware.client_ip import rate_limit_key

limiter = Limiter(key_func=rate_limit_key)
limiter.enabled = settings.RATE_LIMIT_ENABLED
