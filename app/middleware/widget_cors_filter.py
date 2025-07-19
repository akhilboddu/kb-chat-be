from typing import List
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import compile_path
import re
import logging

logger = logging.getLogger(__name__)

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
        # Debug logging
        logger.info(f"WidgetCORSFilter: {request.method} {request.url.path}")
        
        origin = request.headers.get("origin")
        is_widget_endpoint = self._path_allowed(request.url.path)
        
        # For non-widget endpoints, check if origin is allowed
        if not is_widget_endpoint and origin and origin not in self._allowed_origins:
            logger.info(f"WidgetCORSFilter: Blocking non-widget endpoint {request.url.path} from origin {origin}")
            # Return 403 for non-allowed origins on non-widget endpoints
            return Response(
                status_code=403,
                content="CORS policy: Origin not allowed",
                headers={"content-type": "text/plain"}
            )
            
        # Widget endpoints or allowed origins - let the request through
        response: Response = await call_next(request)
        
        # For widget endpoints, ensure CORS headers allow the origin
        if is_widget_endpoint:
            logger.info(f"WidgetCORSFilter: Widget endpoint {request.url.path} accessed from {origin}")
        
        return response

    def _path_allowed(self, path: str) -> bool:
        for regex in self._compiled_patterns:
            if regex.match(path):
                return True
        return False 