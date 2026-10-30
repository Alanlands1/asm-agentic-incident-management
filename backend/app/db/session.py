"""Database engine, session factory and FastAPI dependency."""

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.common.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables that do not exist yet."""
    from app.models import ticket  # noqa: F401  (registers models on Base.metadata)
    from app.platform.admin import models  # noqa: F401  (config_overrides, config_changes)

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """Yield a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
