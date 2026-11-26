"""Add a person who may sign in to the console, or change their name, role or password.

Usage: python scripts/create_user.py <email> "<name as in Jira>" <admin|lead|engineer>
The password is asked for, or read from the AMS_USER_PASSWORD environment variable. Run 12_create_users.sql first.
Add --atlassian-only for a person who signs in with Atlassian and has no password here (the email must be their
Atlassian account's).
"""

import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/, so `app` imports when run as a script

from sqlalchemy import select  # noqa: E402

from app.db.session import AsyncSessionLocal, close_db  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import ROLES, hash_password  # noqa: E402


async def main(email: str, name: str, role: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email)
            db.add(user)
        # "-" is no hash: no password matches it
        user.name, user.role, user.password_hash, user.is_active = name, role, hash_password(password) if password else "-", True
        await db.commit()
    await close_db()
    print(f"{email}: {name}, {role}")


if __name__ == "__main__":
    atlassian_only = "--atlassian-only" in sys.argv
    if atlassian_only:
        sys.argv.remove("--atlassian-only")
    if len(sys.argv) != 4 or sys.argv[3] not in ROLES:
        sys.exit(__doc__)
    secret = "" if atlassian_only else os.environ.get("AMS_USER_PASSWORD") or getpass.getpass("Password: ")
    if not atlassian_only and len(secret) < 8:
        sys.exit("The password needs at least 8 characters")
    asyncio.run(main(sys.argv[1].strip().lower(), sys.argv[2].strip(), sys.argv[3], secret))
