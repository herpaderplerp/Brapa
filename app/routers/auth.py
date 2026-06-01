from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import SESSION_USER_KEY, CurrentUser
from app.auth.oauth import enabled_providers, is_enabled, oauth
from app.config import settings
from app.db import get_db
from app.models.user import OAuthAccount, User
from app.templating import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user: CurrentUser):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"title": "Log in", "providers": enabled_providers()}
    )


@router.get("/login/{provider}")
async def login_provider(provider: str, request: Request):
    if not is_enabled(provider):
        raise HTTPException(status_code=404, detail="Unknown or disabled provider")
    client = oauth.create_client(provider)
    redirect_uri = f"{settings.base_url}/auth/{provider}/callback"
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/auth/{provider}/callback")
async def auth_callback(
    provider: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not is_enabled(provider):
        raise HTTPException(status_code=404, detail="Unknown or disabled provider")
    client = oauth.create_client(provider)
    token = await client.authorize_access_token(request)

    info = token.get("userinfo") or {}
    if not info:
        # Fallback for providers that don't return an OIDC id_token.
        resp = await client.get("userinfo", token=token)
        info = resp.json()

    sub = str(info.get("sub") or info.get("id") or "")
    if not sub:
        raise HTTPException(status_code=400, detail="Provider returned no account id")
    email = info.get("email")
    name = info.get("name")
    picture = info.get("picture")

    # Allowlist gate: reject non-invited emails before creating any account.
    if not settings.email_allowed(email):
        return templates.TemplateResponse(
            request, "not_invited.html", {"title": "Not invited", "email": email}, status_code=403
        )

    user = await _find_or_create_user(db, provider, sub, email, name, picture)
    request.session[SESSION_USER_KEY] = str(user.id)

    dest = "/" if user.is_onboarded else "/onboarding"
    return RedirectResponse(dest, status_code=303)


async def _find_or_create_user(
    db: AsyncSession,
    provider: str,
    sub: str,
    email: str | None,
    name: str | None,
    picture: str | None,
) -> User:
    acct = (
        await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_account_id == sub,
            )
        )
    ).scalar_one_or_none()
    if acct:
        return await db.get(User, acct.user_id)

    # New identity. If a user with this email exists, link to it; else create.
    user: User | None = None
    if email:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
    if user is None:
        user = User(email=email, avatar_url=picture)
        db.add(user)
        await db.flush()

    db.add(
        OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_account_id=sub,
            email=email,
        )
    )
    await db.flush()
    return user


@router.get("/logout")
async def logout(request: Request):
    request.session.pop(SESSION_USER_KEY, None)
    return RedirectResponse("/", status_code=303)
