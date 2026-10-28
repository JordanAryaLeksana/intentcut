"""Local-only AI access boundary and private response headers."""

import ipaddress
import re

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from intentcut.backend.shared.http_errors import ErrorResponse

PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
}


class AIJobLocalAccessMiddleware:
    """Opt-in, direct loopback clients only; never trust forwarded identity.

    This is a local development boundary, not an authentication implementation.
    Run on loopback with proxy headers disabled and never behind a public proxy.
    """

    def __init__(self, app: ASGIApp, enabled: bool) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not re.match(
            r"^/projects/[^/]+/ai-jobs(?:/|$)", scope["path"]
        ):
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(PRIVATE_HEADERS)
            await send(message)

        if not self.enabled:
            status, code, message = (
                503,
                "ai_api_unavailable",
                "The local AI job API is disabled.",
            )
        elif not self._local_request(scope):
            status, code, message = (
                403,
                "local_access_required",
                "Direct trusted local access is required.",
            )
        else:
            await self.app(scope, receive, private_send)
            return
        response = JSONResponse(
            ErrorResponse(code=code, message=message).model_dump(exclude_none=True),
            status_code=status,
        )
        await response(scope, receive, private_send)

    @staticmethod
    def _local_request(scope: Scope) -> bool:
        client = scope.get("client")
        try:
            if not client or not ipaddress.ip_address(client[0]).is_loopback:
                return False
        except ValueError:
            return False
        headers = Headers(scope=scope)
        hosts = headers.getlist("host")
        # Host checks prevent DNS rebinding. Browser and proxy requests are refused.
        return (
            len(hosts) == 1
            and re.fullmatch(
                r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", hosts[0]
            )
            is not None
            and "origin" not in headers
            and headers.get("sec-fetch-site", "none") == "none"
            and not any(
                name in {"forwarded", "via"} or name.startswith("x-forwarded-")
                for name in headers
            )
        )
