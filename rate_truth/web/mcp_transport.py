"""MCP Host/Origin checks, including explicitly configured subdomain wildcards."""

import os

from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from starlette.requests import Request

from rate_truth.settings import ORIGIN


def configured_security():
    hosts = ["127.0.0.1", "localhost", "127.0.0.1:*", "localhost:*"]
    for name in (
        "RATE_TRUTH_HOSTS",
        "RATE_TRUTH_MCP_HOSTS",
        "VERCEL_URL",
        "VERCEL_PROJECT_PRODUCTION_URL",
    ):
        hosts.extend(h.strip() for h in os.getenv(name, "").split(",") if h.strip())
    return TransportSecuritySettings(
        allowed_hosts=hosts,
        allowed_origins=[os.getenv("RATE_TRUTH_ORIGIN", ORIGIN)],
    )


class MCPTransportSecurity(TransportSecurityMiddleware):
    def _validate_host(self, host):
        if host:
            for allowed in self.settings.allowed_hosts:
                if allowed.startswith("*.") and host.endswith(allowed[1:]):
                    prefix = host[: -len(allowed[1:])]
                    if prefix and all(c.isalnum() or c in ".-" for c in prefix):
                        return True
        return super()._validate_host(host)


class SecureMCP:
    def __init__(self, app):
        self.app = app
        self.security = MCPTransportSecurity(configured_security())

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            response = await self.security.validate_request(
                Request(scope), is_post=scope["method"] == "POST"
            )
            if response:
                return await response(scope, receive, send)
            scope = {**scope, "path": "/", "raw_path": b"/", "root_path": ""}
        await self.app(scope, receive, send)
