import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.user import User

SESSION_USER_KEY = "user_id"


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    """Load the logged-in user from the signed session cookie, or None."""
    raw = request.session.get(SESSION_USER_KEY)
    if not raw:
        return None
    try:
        user_id = uuid.UUID(raw)
    except (ValueError, TypeError):
        return None
    return await db.get(User, user_id)


CurrentUser = Annotated[User | None, Depends(get_current_user)]


class RequireLogin:
    """Dependency that redirects to /login when no user is present.

    Raise via FastAPI's exception-as-response pattern: routes depending on this
    receive a guaranteed non-None User, otherwise the request is redirected.
    """

    async def __call__(self, user: CurrentUser) -> User:
        if user is None:
            # Returning a response from a dependency isn't allowed, so we signal
            # via exception handled in main.py.
            raise _NotAuthenticated()
        return user


class _NotAuthenticated(Exception):
    pass


require_login = RequireLogin()
LoggedInUser = Annotated[User, Depends(require_login)]


def login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)
