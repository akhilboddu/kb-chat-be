from typing import List
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import compile_path
import re

class WidgetCORSFilter(BaseHTTPMiddleware):
    """Middleware that keeps the `Access-Control-Allow-Origin` header only for widget endpoints.

    It assumes a *global* CORSMiddleware already added **with** ``allow_origins=["*"]``.
    For every response coming out of the app, we check the request path. If it doesn't
    match one of the allowed widget patterns, we strip the CORS headers so the browser
    will treat the response as *not* CORS-enabled.
    """

    def __init__(self, app, allowed_paths: List[str], allowed_origins: List[str] | None = None):
        super().__init__(app)
        # Pre-compile the path patterns to regex objects for fast matching
        self._compiled_patterns = []
        self._allowed_origins = set(allowed_origins or [])
        for pattern in allowed_paths:
            # Starlette's compile_path returns (regex, *rest). We only need the regex.
            regex = compile_path(pattern)[0]
            self._compiled_patterns.append(regex)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)
        origin = request.headers.get("origin")
        # Only bother if this is a cross-origin request that has Origin header
        if origin:
            # Keep header if origin is explicitly allowed
            if origin in self._allowed_origins:
                return response
            if not self._path_allowed(request.url.path):
                # Strip CORS headers added by the global CORSMiddleware
                for hdr in (
                    "access-control-allow-origin",
                    "access-control-allow-credentials",
                    "access-control-allow-methods",
                    "access-control-allow-headers",
                ):
                    if hdr in response.headers:
                        del response.headers[hdr]
        return response

    def _path_allowed(self, path: str) -> bool:
        for regex in self._compiled_patterns:
            if regex.match(path):
                return True
        return False 