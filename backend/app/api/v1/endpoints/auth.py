"""Sign-in with email and password, or with Atlassian. The session is an HttpOnly cookie; every other endpoint asks for it."""

import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.services import atlassian_login, auth

COOKIE = "ams_session"
STATE_COOKIE = "ams_oauth_state"  # ties the Atlassian callback to the browser that started it

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=256, examples=["lead@contoso.com"])
    password: str = Field(..., min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: str
    name: str  # as in Jira: the name on the tickets assigned to them
    role: str  # admin | lead | engineer


async def current_user(ams_session: str | None = Cookie(None), db: AsyncSession = Depends(get_db)) -> User:
    """The signed-in person, from the session cookie. 401 without a valid session."""
    user = await auth.user_of(db, ams_session) if ams_session else None
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in first")
    return user


def require_role(*roles: str):
    """A dependency that lets only these roles through. 403 for anyone else who is signed in."""

    async def allowed(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Only {' or '.join(roles)} may do this")
        return user

    return allowed


@router.post("/login", response_model=UserOut, summary="Sign in")
async def login(payload: LoginIn, response: Response, db: AsyncSession = Depends(get_db)) -> UserOut:
    """Checks the email and password and sets the session cookie. The same 401 for an unknown email and a wrong password."""
    signed_in = await auth.sign_in(db, payload.email, payload.password)
    if signed_in is None:
        raise HTTPException(status_code=401, detail="Wrong email or password")
    user, token = signed_in
    _set_session(response, token)
    return UserOut.model_validate(user)


def _set_session(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=settings.SESSION_HOURS * 3600, httponly=True, samesite="lax",
                        secure=settings.SESSION_COOKIE_SECURE, path="/")


class ProvidersOut(BaseModel):
    atlassian: bool


@router.get("/providers", response_model=ProvidersOut, summary="Which other ways to sign in are switched on")
async def providers() -> ProvidersOut:
    return ProvidersOut(atlassian=atlassian_login.enabled())


@router.get("/atlassian/start", summary="Sign in with Atlassian: go to Atlassian", status_code=307)
async def atlassian_start() -> RedirectResponse:
    if not atlassian_login.enabled():
        raise HTTPException(status_code=503, detail="Sign in with Atlassian is switched off: set ATLASSIAN_OAUTH_CLIENT_ID "
                                                    "and ATLASSIAN_OAUTH_CLIENT_SECRET in backend/.env")
    state = secrets.token_urlsafe(24)
    response = RedirectResponse(atlassian_login.authorize_url(state))
    response.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax",
                        secure=settings.SESSION_COOKIE_SECURE, path="/")
    return response


@router.get("/atlassian/callback", summary="Sign in with Atlassian: back from Atlassian", status_code=307)
async def atlassian_callback(
    code: str | None = None, state: str | None = None, ams_oauth_state: str | None = Cookie(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Atlassian sends the browser here. The person is signed in when their Atlassian email is a user here, then sent
    to the console; otherwise back to the sign-in page with the reason (?error=atlassian | no_access)."""
    failed = RedirectResponse("/login?error=atlassian")
    failed.delete_cookie(STATE_COOKIE, path="/")
    if not code or not state or not ams_oauth_state or not secrets.compare_digest(state, ams_oauth_state):
        return failed
    try:
        email = await atlassian_login.email_of(code)
    except atlassian_login.AtlassianLoginError:
        return failed
    signed_in = await auth.sign_in_as(db, email)
    if signed_in is None:  # a real Atlassian account, but nobody added them here
        failed.headers["location"] = "/login?error=no_access"
        return failed
    response = RedirectResponse("/")
    response.delete_cookie(STATE_COOKIE, path="/")
    _set_session(response, signed_in[1])
    return response


@router.post("/logout", status_code=204, summary="Sign out")
async def logout(response: Response, ams_session: str | None = Cookie(None), db: AsyncSession = Depends(get_db)) -> None:
    """Ends the session and clears the cookie. Also fine when nobody is signed in."""
    if ams_session:
        await auth.sign_out(db, ams_session)
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=UserOut, summary="Who is signed in")
async def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/users", response_model=list[UserOut], summary="Everyone who may sign in",
            dependencies=[Depends(require_role("admin"))])
async def users(db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    """For the admin's persona list in the console: the people an admin can view the console as."""
    rows = await db.scalars(select(User).where(User.is_active).order_by(User.name, User.role))
    return [UserOut.model_validate(u) for u in rows]
