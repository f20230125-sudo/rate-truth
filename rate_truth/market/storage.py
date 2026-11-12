"""Atomic JSON replacement and OS file locks shared by processes on one volume."""

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rate_truth.market.base import MarketError
from rate_truth.settings import DATA


def market_dir():
    default = (
        Path(tempfile.gettempdir()) / "rate-truth/market"
        if os.getenv("VERCEL")
        else (DATA / "market")
    )
    return Path(os.getenv("RATE_TRUTH_MARKET_DIR", default))


def utcnow():
    return datetime.now(UTC)


def scrub(value, secret=None):
    """Remove recursive credential keys, echoed URL credentials, and literal key values."""
    secret = secret or os.getenv("SERPAPI_API_KEY")
    if isinstance(value, dict):
        return {
            scrub(k, secret): scrub(v, secret)
            for k, v in value.items()
            if str(k).casefold() != "api_key"
        }
    if isinstance(value, list):
        return [scrub(v, secret) for v in value]
    if isinstance(value, str):
        if value.startswith(("https://", "http://")):
            p = urlsplit(value)
            query = [
                (k, v)
                for k, v in parse_qsl(p.query, keep_blank_values=True)
                if k.casefold() != "api_key"
            ]
            value = urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), p.fragment))
        value = re.sub(r"(?i)([?&]api_key=)[^&#\s\"']+", r"\1[redacted]", value)
        if secret:
            value = value.replace(secret, "[redacted]")
    return value


def read_json(path, default=None):
    path = Path(path)
    with file_lock(json_lock_path(path)):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(scrub(data), stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        with file_lock(json_lock_path(path)):
            for attempt in range(6):
                try:
                    os.replace(temp, path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.01 * 2**attempt)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def json_lock_path(path):
    # Packaged snapshot directories can be read-only on serverless hosts.
    identity = os.path.normcase(str(Path(path).resolve())).encode()
    return (
        Path(tempfile.gettempdir())
        / "rate-truth-json-locks"
        / (hashlib.sha256(identity).hexdigest() + ".lock")
    )


@contextmanager
def file_lock(path, timeout=15):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + timeout
        acquired = False
        while not acquired:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise MarketError(
                        "market_busy", "market storage is busy; retry later"
                    ) from None
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
