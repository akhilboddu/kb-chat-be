from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import time
from collections import defaultdict
from typing import Dict, List, Tuple
import asyncio
import logging

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware for FastAPI
    Implements a sliding window rate limiter
    """
    
    def __init__(
        self,
        app,
        calls: int = 100,
        period: int = 60,
        auth_calls: int = 10,  # Stricter limit for auth endpoints
        auth_period: int = 60
    ):
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.auth_calls = auth_calls
        self.auth_period = auth_period
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self.cleanup_interval = 60  # Clean up old entries every minute
        self._cleanup_task = None
        
    async def startup(self):
        """Start the cleanup task"""
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        
    async def shutdown(self):
        """Stop the cleanup task"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def _periodic_cleanup(self):
        """Periodically clean up old request timestamps"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_old_requests()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in rate limit cleanup: {e}")
    
    async def _cleanup_old_requests(self):
        """Remove old request timestamps"""
        current_time = time.time()
        
        # Create a list of IPs to clean up to avoid modifying dict during iteration
        ips_to_clean = []
        
        for ip, timestamps in self.requests.items():
            # Keep only recent timestamps
            self.requests[ip] = [
                ts for ts in timestamps
                if current_time - ts < max(self.period, self.auth_period)
            ]
            
            # Mark empty entries for removal
            if not self.requests[ip]:
                ips_to_clean.append(ip)
        
        # Remove empty entries
        for ip in ips_to_clean:
            del self.requests[ip]
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request"""
        # Check for forwarded IP (when behind proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()
        
        # Check for real IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fall back to direct connection IP
        if request.client:
            return request.client.host
        
        return "unknown"
    
    def _is_auth_endpoint(self, path: str) -> bool:
        """Check if the request is for an auth endpoint"""
        auth_paths = [
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/forgot-password",
            "/api/auth/reset-password"
        ]
        return any(path.startswith(p) for p in auth_paths)
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Process the request with rate limiting"""
        # Skip rate limiting for health checks and docs
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)
        
        client_ip = self._get_client_ip(request)
        now = time.time()
        
        # Determine rate limit based on endpoint type
        is_auth = self._is_auth_endpoint(request.url.path)
        limit_calls = self.auth_calls if is_auth else self.calls
        limit_period = self.auth_period if is_auth else self.period
        
        # Clean old requests for this IP
        self.requests[client_ip] = [
            req_time for req_time in self.requests[client_ip]
            if now - req_time < limit_period
        ]
        
        # Check rate limit
        if len(self.requests[client_ip]) >= limit_calls:
            # Calculate retry after
            oldest_request = min(self.requests[client_ip])
            retry_after = int(limit_period - (now - oldest_request))
            
            logger.warning(
                f"Rate limit exceeded for {client_ip} on {request.url.path} "
                f"({len(self.requests[client_ip])} requests in {limit_period}s)"
            )
            
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)}
            )
        
        # Record this request
        self.requests[client_ip].append(now)
        
        # Process the request
        response = await call_next(request)
        
        # Add rate limit headers to response
        remaining = limit_calls - len(self.requests[client_ip])
        response.headers["X-RateLimit-Limit"] = str(limit_calls)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        response.headers["X-RateLimit-Reset"] = str(int(now + limit_period))
        
        return response


def get_rate_limit_middleware(
    calls: int = 100,
    period: int = 60,
    auth_calls: int = 10,
    auth_period: int = 60
) -> RateLimitMiddleware:
    """
    Factory function to create rate limit middleware
    
    Args:
        calls: Number of allowed calls for general endpoints
        period: Time period in seconds for general endpoints
        auth_calls: Number of allowed calls for auth endpoints
        auth_period: Time period in seconds for auth endpoints
    
    Returns:
        Configured RateLimitMiddleware instance
    """
    return lambda app: RateLimitMiddleware(
        app,
        calls=calls,
        period=period,
        auth_calls=auth_calls,
        auth_period=auth_period
    )