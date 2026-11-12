"""Versioned HMAC capabilities; replicas share RATE_TRUTH_SECRET."""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets

_DEV_SECRET = secrets.token_bytes(32)
_warned = False


def signing_secret():
    global _warned
    configured = os.getenv("RATE_TRUTH_SECRET")
    if configured:
        return configured.encode()
    if not _warned:
        logging.getLogger(__name__).warning(
            "RATE_TRUTH_SECRET unset: temporary development secret is local to this process"
        )
        _warned = True
    return _DEV_SECRET


def _encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def sign(payload, secret):
    body = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return body + "." + _encode(hmac.digest(secret, body.encode(), "sha256"))


def verify(token, secret):
    if not isinstance(token, str) or len(token) > 4096:
        raise ValueError("invalid capability")
    body, signature = token.split(".")
    expected = _encode(hmac.digest(secret, body.encode(), "sha256"))
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid capability")
    return json.loads(
        base64.b64decode(body + "=" * (-len(body) % 4), altchars=b"-_", validate=True)
    )


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()
