"""Reject excessive request bodies and concurrent upload batches before parsing."""

import re

from starlette.datastructures import Headers
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from intentcut.backend.shared.http_errors import ErrorResponse


class UploadLimitsMiddleware:
    """One admitted upload per process; native Starlette limits count received bytes."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self._app = app
        self._uploads = RequestBodyLimitMiddleware(app, max_body_size=max_body_bytes)
        self._small_requests = RequestBodyLimitMiddleware(app, max_body_size=16 * 1024)
        self._max_body_bytes = max_body_bytes
        self._upload_active = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        upload = scope["method"] == "POST" and bool(
            re.fullmatch(r"/projects/[^/]+/media/?", scope["path"])
        )
        limit = self._max_body_bytes if upload else 16 * 1024
        length = Headers(scope=scope).get("content-length")
        if length is not None:
            try:
                size = int(length)
                if size < 0:
                    raise ValueError
            except ValueError:
                await self._reject(
                    scope,
                    receive,
                    send,
                    400,
                    "invalid_request",
                    "Invalid Content-Length.",
                )
                return
            if size > limit:
                await self._reject(
                    scope,
                    receive,
                    send,
                    413,
                    "upload_limit",
                    "Request body exceeds the size limit.",
                )
                return
        if not upload:
            await self._small_requests(scope, receive, send)
            return
        if self._upload_active:
            await self._reject(
                scope,
                receive,
                send,
                503,
                "upload_busy",
                "Another upload is in progress.",
            )
            return
        # No await between checking and claiming the slot on the ASGI event loop.
        self._upload_active = True
        try:
            await self._uploads(scope, receive, send)
        finally:
            self._upload_active = False

    @staticmethod
    async def _reject(
        scope: Scope, receive: Receive, send: Send, status: int, code: str, message: str
    ) -> None:
        response = JSONResponse(
            ErrorResponse(code=code, message=message).model_dump(exclude_none=True),
            status_code=status,
        )
        await response(scope, receive, send)
