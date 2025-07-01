from fastapi import Request, WebSocket, HTTPException
from app.services.auth_service import get_user_from_token


def require_cookie_auth(request: Request = None, websocket: WebSocket = None):
    """Dependency that validates the `auth_token` cookie on both HTTP and WebSocket routes.

    The first parameter supplied by FastAPI will be either *request* (for normal
    HTTP endpoints) or *websocket* (for `WebSocketRoute`s).  We inspect
    whichever one is not ``None``.
    """

    conn = request or websocket

    if conn is None:
        # Should not happen, but guard just in case FastAPI changes internals.
        raise HTTPException(status_code=500, detail="Unexpected dependency context")

    # Allow public WebSocket endpoints (e.g. /api/ws/{conversation_id})
    if isinstance(conn, WebSocket):
        return None  # Skip auth for websockets

    auth_token = conn.cookies.get("auth_token") if hasattr(conn, "cookies") else None
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user_info = get_user_from_token(auth_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    return user_info 