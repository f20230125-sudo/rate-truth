"""Forwarded addresses are trusted only behind an explicitly trusted proxy."""

import os
from ipaddress import ip_address


def client_ip(request):
    if os.getenv("RATE_TRUTH_TRUST_PROXY", "false").lower() == "true":
        for header in ("x-vercel-forwarded-for", "x-real-ip"):
            value = request.headers.get(header, "").split(",", 1)[0].strip()
            try:
                return str(ip_address(value))
            except ValueError:
                continue
    return request.client.host if request.client else "local"
