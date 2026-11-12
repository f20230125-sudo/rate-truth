"""Bound chunked JSON before FastAPI buffers it, returning the same JSON error shape."""

from fastapi.responses import JSONResponse


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        maximum = 64000 if scope["path"].startswith("/api/") else 2100000
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return
            if len(body) + len(message.get("body", b"")) > maximum:
                response = JSONResponse(
                    {
                        "error": {
                            "code": "invalid_input",
                            "message": "request body exceeds the byte limit",
                        }
                    },
                    status_code=413,
                )
                return await response(scope, receive, send)
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
