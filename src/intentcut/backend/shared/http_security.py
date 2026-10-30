"""Local-only AI access boundary and private response headers."""

import ipaddress
import re
from urllib.parse import urlsplit

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

    def __init__(
        self,
        app: ASGIApp,
        enabled: bool,
        browser_enabled: bool = False,
        browser_origins: list[str] | None = None,
    ) -> None:
        self.app = app
        self.enabled = enabled
        self.browser_enabled = browser_enabled
        self.browser_origins = frozenset(browser_origins or [])


    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not re.match(
            r"^/projects/[^/]+/(?:ai-jobs|edit-draft)(?:/|$)", scope["path"]
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

    def _local_request(self, scope: Scope) -> bool:
            client = scope.get("client")

            try:
                if not client or not ipaddress.ip_address(client[0]).is_loopback:
                    return False
            except (ValueError, TypeError):
                return False

            headers = Headers(scope=scope)
            hosts = headers.getlist("host")

            if (
                len(hosts) != 1
                or re.fullmatch(
                    r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?",
                    hosts[0],
                ) is None
            ):
                return False

            if any(
                name in {"forwarded", "via"} or name.startswith("x-forwarded-")
                for name in headers
            ):
                return False

            origins = headers.getlist("origin")

            # Preserve trusted direct local clients.
            if not origins:
                return headers.get("sec-fetch-site", "none") == "none"

            # Browser access requires explicit opt-in.
            if not self.browser_enabled or len(origins) != 1:
                return False

            origin = origins[0]

            if origin not in self.browser_origins:
                return False

            try:
                parsed = urlsplit(origin)

                if (
                    parsed.scheme != "http"
                    or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                    or parsed.port is None
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.path
                    or parsed.query
                    or parsed.fragment
                ):
                    return False
            except ValueError:
                return False

            return (
                headers.get("sec-fetch-site")
                in {"same-origin", "same-site", "cross-site"}
                and headers.get("sec-fetch-mode") == "cors"
                and headers.get("sec-fetch-dest", "empty") == "empty"
            )
