"""Shared test fixtures."""

import os
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from pydantic import SecretStr

from app.admin import models  # noqa: F401  (config_overrides, config_changes)
from app.api.v1.endpoints.auth import current_user
from app.core.config import settings
from app.db.session import Base, get_db
from app.main import app
from app.models import ticket  # noqa: F401  (registers models on Base.metadata)
from app.models.user import User

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
    from app.services import jira  # noqa: PLC0415  (imported here so settings above are patched first)

    monkeypatch.setattr(jira, "start_resolution", lambda ticket_id=None: None)  # no Resolution left running after a test
    monkeypatch.setattr(jira, "start_knowledge", lambda: None)  # nor Knowledge Builder


@pytest.fixture(autouse=True)
def jira_not_asked_yet(monkeypatch):
    """Who Jira lets be assigned is remembered between requests: every test starts as after a restart, and Jira
    itself is never asked (a test that needs an answer installs its own)."""
    from app.services import jira

    async def away(keys):
        raise jira.AtlassianError("no Jira in tests")

    monkeypatch.setattr(jira, "assignable", away)
    monkeypatch.setattr(jira, "known_people", None)
    monkeypatch.setattr(jira, "_people_asked", None)


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
    """API client backed by a fresh in-memory database, so tests never touch ams.db. Signed in as an admin; a test
    of the sign-in itself removes that (the `anon` fixture in test_auth.py)."""
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    TestSession = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    async def override_get_db():
        async with TestSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[current_user] = lambda: User(id=1, email="admin@test", name="Test Admin", role="admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()
