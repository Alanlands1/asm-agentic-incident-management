"""Shared test fixtures."""

import os
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pydantic import SecretStr

from app.admin import models  # noqa: F401  (config_overrides, config_changes)
from app.core.config import settings
from app.db.session import Base, get_db
from app.main import app
from app.models import ticket  # noqa: F401  (registers models on Base.metadata)

os.environ["TZ"] = "UTC"  # texts for people carry the server's local time; the tests expect UTC
if hasattr(time, "tzset"):  # not on Windows
    time.tzset()


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Tests never reach the real model, whatever backend/.env says; the `provider` fixture installs a scripted one.
    They never write to the real Jira either: a test that writes switches JIRA_WRITE_BACK on and fakes the site."""
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    monkeypatch.setattr(settings, "JIRA_WRITE_BACK", False)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(""))


@pytest.fixture(autouse=True)
def own_confluence_copy(monkeypatch, tmp_path):
    """A Confluence sync in a test writes its pages to a folder of its own, never to data/confluence_copy, so no
    test's pages leak into the articles the next test reads."""
    from app.agents.closure_quality.model_check import kb_ids
    from app.agents.knowledge_builder.articles import articles

    monkeypatch.setattr(settings, "CONFLUENCE_COPY_DIR", tmp_path / "confluence_copy")
    monkeypatch.setattr(settings, "CONFLUENCE_WRITE_BACK", False)
    articles.cache_clear()
    kb_ids.cache_clear()
    yield
    articles.cache_clear()
    kb_ids.cache_clear()


@pytest.fixture
async def client():
    """API client backed by a fresh in-memory database, so tests never touch ams.db."""
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    TestSession = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    async def override_get_db():
        async with TestSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()
