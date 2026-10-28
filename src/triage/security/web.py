"""Browser-facing protections: security headers, CSRF tokens and a simple rate limiter."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSRF_COOKIE = "triage_csrf"
CSRF_FIELD = "csrf_token"

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
)
# Swagger UI loads its assets from a CDN, so the API docs page gets a slightly wider policy.
DOCS_CSP = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "style-src 'self' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = True) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        csp = DOCS_CSP if path in ("/docs", "/redoc") else CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = {
                    b"content-security-policy": csp.encode(),
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"strict-origin-when-cross-origin",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=(), payment=()",
                    b"cross-origin-opener-policy": b"same-origin",
                    b"cache-control": b"public, max-age=3600" if path.startswith("/static/") else b"no-store",
                }
                if self.hsts:
                    extra[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in extra]
                message["headers"] = headers + list(extra.items())
            await send(message)

        await self.app(scope, receive, send_with_headers)


def new_csrf_cookie() -> str:
    return secrets.token_urlsafe(32)


def csrf_token_for(secret: str, cookie_value: str) -> str:
    return hmac.new(secret.encode(), cookie_value.encode(), hashlib.sha256).hexdigest()


def csrf_valid(secret: str, cookie_value: str | None, submitted: str | None) -> bool:
    if not cookie_value or not submitted:
        return False
    return hmac.compare_digest(csrf_token_for(secret, cookie_value), submitted)


def client_ip(request: Request) -> str:
    """The caller's IP. Container Apps ingress appends the real client address last in X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Sliding one-minute window per key, kept in memory. Good enough for one or two replicas."""

    def __init__(
        self, per_minute: int, clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000
    ) -> None:
        self.per_minute = per_minute
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            if len(self._hits) > self._max_keys:
                self._hits = {k: q for k, q in self._hits.items() if q and now - q[-1] < 60}
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True
