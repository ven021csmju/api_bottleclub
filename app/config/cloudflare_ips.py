"""Cloudflare's IP ranges (Phase 49): parsed apart from app.middleware.client_ip
so the settings can check them at start without importing the settings."""
from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# https://www.cloudflare.com/ips-v4 and /ips-v6, read 2026-11-21. Replace with
# CLOUDFLARE_IP_RANGES (comma-separated) or CLOUDFLARE_IP_RANGES_FILE (one per
# line, # comments) when Cloudflare publishes a change.
CLOUDFLARE_IP_RANGES_DEFAULT = (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
)


def parse_networks(entries: list[str] | tuple[str, ...]) -> tuple[IPNetwork, ...]:
    """CIDRs (or single IPs); a malformed entry raises ValueError."""
    out = []
    for raw in entries:
        entry = raw.split("#", 1)[0].strip()
        if entry:
            out.append(ipaddress.ip_network(entry, strict=True))
    return tuple(out)


@lru_cache(maxsize=4)
def _networks(ranges: str, ranges_file: str) -> tuple[IPNetwork, ...]:
    if ranges_file:
        nets = parse_networks(Path(ranges_file).expanduser().read_text().splitlines())
    elif ranges:
        nets = parse_networks(ranges.split(","))
    else:
        nets = parse_networks(CLOUDFLARE_IP_RANGES_DEFAULT)
    if not nets:
        raise ValueError("no Cloudflare IP range configured")
    return nets


