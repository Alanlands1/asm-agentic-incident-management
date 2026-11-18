"""Shared Atlassian Cloud access for Jira and Confluence: the API token from the environment.

Read-only, except jira.post_comment, jira.set_priority, jira.announce and jira.move_triaged.
"""

from typing import Any

import httpx

from app.core.config import settings


class AtlassianError(RuntimeError):
    """Atlassian is not configured or answered with an error."""


def configured() -> bool:
    return bool(settings.ATLASSIAN_BASE_URL and settings.ATLASSIAN_EMAIL and settings.ATLASSIAN_API_TOKEN.get_secret_value())


def client() -> httpx.AsyncClient:
    if not configured():
        raise AtlassianError(
            "Atlassian is not set up: add ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN to backend/.env"
        )
    return httpx.AsyncClient(
        base_url=settings.ATLASSIAN_BASE_URL.rstrip("/"),
        auth=(settings.ATLASSIAN_EMAIL, settings.ATLASSIAN_API_TOKEN.get_secret_value()),
        headers={"Accept": "application/json"},
        timeout=30,  # DNS alone can take 5s on some networks
    )


async def call(c: httpx.AsyncClient, method: str, url: str, **kwargs) -> Any:
    try:
        r = await c.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise AtlassianError(f"Couldn't reach Atlassian: {exc.__class__.__name__}") from exc
    if r.status_code in (401, 403):
        raise AtlassianError("Atlassian refused the API token: check ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN")
    if not r.is_success:
        raise AtlassianError(f"Atlassian answered {r.status_code} for {url.split('?')[0]}")
    return r.json() if r.content else None  # a successful write may answer with no body


async def whoami() -> str:
    async with client() as c:
        return (await call(c, "GET", "/rest/api/3/myself"))["displayName"]
