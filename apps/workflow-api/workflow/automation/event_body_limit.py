"""Bound JSON allocation and request read time before FastAPI parses events."""
from __future__ import annotations

import asyncio
import time

from starlette.responses import JSONResponse

from .events import MAX_EVENT_BYTES


class EventBodyLimit:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith("/v1/automation/"):
            await self.app(scope, receive, send)
            return
        total = bytearray()
        deadline = time.monotonic() + 10
        while True:
            if time.monotonic() >= deadline:
                await JSONResponse({"detail": "Event request read timeout"}, status_code=408)(scope, receive, send)
                return
            try:
                message = await asyncio.wait_for(receive(), timeout=max(0.001, deadline - time.monotonic()))
            except TimeoutError:
                await JSONResponse({"detail": "Event request read timeout"}, status_code=408)(scope, receive, send)
                return
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(total) + len(chunk) > MAX_EVENT_BYTES:
                await JSONResponse({"detail": "Event request body exceeds bounds"}, status_code=413)(scope, receive, send)
                return
            total.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(total), "more_body": False}
        await self.app(scope, bounded_receive, send)
