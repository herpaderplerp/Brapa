import hmac
import secrets
from typing import Annotated

from fastapi import Form, HTTPException, Request

CSRF_SESSION_KEY = "csrf_token"


def csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return str(token)


def valid_csrf_token(request: Request, submitted: str) -> bool:
    token = request.session.get(CSRF_SESSION_KEY)
    return bool(token and submitted and hmac.compare_digest(str(token), submitted))


def require_csrf_token(
    request: Request,
    csrf_token: Annotated[str, Form()] = "",
) -> None:
    if not valid_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
