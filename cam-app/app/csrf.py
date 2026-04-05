"""CSRF protection middleware using Origin/Referer header validation.

All mutating requests (POST/PUT/DELETE/PATCH) must include an Origin or
Referer header whose host matches the request's Host header.  Datastar's
@post() uses fetch(), which always sends Origin, so this is transparent.
"""

import logging
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        host = request.headers.get("host", "")

        # Check Origin first (preferred, always sent by fetch)
        origin = request.headers.get("origin")
        if origin:
            origin_host = urlparse(origin).netloc
            if origin_host == host:
                return await call_next(request)
            logging.warning(f"CSRF blocked: origin {origin!r} != host {host!r}")
            return Response("CSRF validation failed", status_code=403)

        # Fall back to Referer
        referer = request.headers.get("referer")
        if referer:
            referer_host = urlparse(referer).netloc
            if referer_host == host:
                return await call_next(request)
            logging.warning(f"CSRF blocked: referer {referer!r} != host {host!r}")
            return Response("CSRF validation failed", status_code=403)

        # No Origin or Referer — could be a same-origin form POST from an
        # older browser, or a curl/API call.  SameSite=Lax on the auth cookie
        # is the backstop here; allow the request through.
        return await call_next(request)
