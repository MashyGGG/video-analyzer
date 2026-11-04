"""Bound request bytes before JSON parsing; raw media has its own streaming limit too."""

import asyncio

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.sources.adapters import MAX_BYTES


class BodyLimit(Exception):
    pass


class AcquisitionLimits:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].startswith("/api/v1/assets/")
        ):
            await self.app(scope, receive, send)
            return
        maximum = MAX_BYTES if scope["path"] == "/api/v1/assets/upload" else 8192
        received = 0

        async def limited() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > maximum:
                raise BodyLimit()
            return message

        try:
            async with asyncio.timeout(185):
                if maximum == MAX_BYTES:
                    # Upload endpoint streams and enforces its own declared/actual lengths.
                    await self.app(scope, receive, send)
                else:
                    payload = bytearray()
                    while True:
                        message = await limited()
                        if message["type"] == "http.disconnect":
                            return
                        payload.extend(message.get("body", b""))
                        if not message.get("more_body", False):
                            break

                    async def buffered() -> Message:
                        return {"type": "http.request", "body": bytes(payload), "more_body": False}

                    await self.app(scope, buffered, send)
        except (BodyLimit, TimeoutError):
            response = JSONResponse(
                {
                    "code": "MEDIA_TOO_LARGE",
                    "message": "请求超过体积或时间限制，请重新上传。",
                    "retryable": False,
                    "details": {"fallback": "upload"},
                },
                status_code=413,
            )
            await response(scope, receive, send)
