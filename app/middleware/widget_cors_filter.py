from typing import List
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import compile_path
import re

class WidgetCORSFilter(BaseHTTPMiddleware):
    """Middleware that allows widget endpoints to be accessed from any origin.

    This middleware overrides CORS headers for specific widget endpoints to allow
    them to be embedded on any website. For widget endpoints, it sets the
    Access-Control-Allow-Origin header to match the requesting origin.
    
    For non-widget endpoints, it preserves the CORS policy set by the main 
    CORSMiddleware.
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
        
        # If this is a widget endpoint, always allow CORS from any origin
        if self._path_allowed(request.url.path) and origin:
            # Override CORS headers for widget endpoints to allow any origin
            response.headers["access-control-allow-origin"] = origin
            response.headers["access-control-allow-credentials"] = "true"
            response.headers["access-control-allow-methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["access-control-allow-headers"] = "Accept, Content-Type, Authorization, X-Requested-With, Origin, User-Agent"
            response.headers["vary"] = "Origin"
            return response
            
        # For non-widget endpoints, keep the original behavior
        if origin:
            # Keep header if origin is explicitly allowed
            if origin in self._allowed_origins:
                return response
            # Otherwise use the default CORS policy set by CORSMiddleware
        return response

    def _path_allowed(self, path: str) -> bool:
        for regex in self._compiled_patterns:
            if regex.match(path):
                return True
        return False 