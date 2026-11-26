"""Sign-in: password hashes (scrypt, standard library) and sessions kept in the database."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User, UserSession

ROLES = ("admin", "lead", "engineer")
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT).hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, expected = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except ValueError:
        return False


_NOBODY = hash_password(secrets.token_hex(16))  # checked when the email is unknown, so both failures take as long


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def sign_in(db: AsyncSession, email: str, password: str) -> tuple[User, str] | None:
    """The user and a new session token for the cookie, or None when the email or password is wrong."""
    user = await db.scalar(select(User).where(User.email == email.strip().lower()))
    if not verify_password(password, user.password_hash if user else _NOBODY) or user is None or not user.is_active:
        return None
    return user, await start_session(db, user)


async def sign_in_as(db: AsyncSession, email: str) -> tuple[User, str] | None:
    """The same for a person whose email someone else confirmed (Atlassian). None when nobody here has that email."""
    user = await db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        return None
    return user, await start_session(db, user)


async def start_session(db: AsyncSession, user: User) -> str:
    """A new session for the user; returns the token for the cookie."""
    now = datetime.now(UTC)
    await db.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at < now))
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=_hash(token), user_id=user.id, expires_at=now + timedelta(hours=settings.SESSION_HOURS)))
    await db.commit()
    return token


async def user_of(db: AsyncSession, token: str) -> User | None:
    """Who the session token belongs to; None when it is unknown or expired, or the person was switched off."""
    session = await db.get(UserSession, _hash(token))
    if session is None:
        return None
    expires = session.expires_at if session.expires_at.tzinfo else session.expires_at.replace(tzinfo=UTC)  # SQLite drops the zone
    if expires < datetime.now(UTC):
        return None
    user = await db.get(User, session.user_id)
    return user if user and user.is_active else None


async def sign_out(db: AsyncSession, token: str) -> None:
    await db.execute(delete(UserSession).where(UserSession.token_hash == _hash(token)))
    await db.commit()
