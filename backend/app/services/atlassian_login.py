"""Sign in with Atlassian (OAuth 2.0, authorization code). Only says who the person is: their email picks the user here.

Needs an OAuth 2.0 (3LO) app at developer.atlassian.com with the User identity API (scope read:me) and
ATLASSIAN_OAUTH_REDIRECT_URI as its callback URL. Separate from the API token the Jira sync uses.
"""

from urllib.parse import urlencode

import httpx

from app.core.config import settings

AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
PROFILE_URL = "https://api.atlassian.com/me"


class AtlassianLoginError(Exception):
    """Atlassian did not confirm who the person is."""


def enabled() -> bool:
    return bool(settings.ATLASSIAN_OAUTH_CLIENT_ID and settings.ATLASSIAN_OAUTH_CLIENT_SECRET.get_secret_value())


def authorize_url(state: str) -> str:
    """Where the browser goes to sign in at Atlassian; `state` comes back on the callback."""
    return f"{AUTHORIZE_URL}?" + urlencode({
        "audience": "api.atlassian.com", "client_id": settings.ATLASSIAN_OAUTH_CLIENT_ID, "scope": "read:me",
        "redirect_uri": settings.ATLASSIAN_OAUTH_REDIRECT_URI, "state": state, "response_type": "code", "prompt": "consent",
    })


async def email_of(code: str) -> str:
    """The email of the Atlassian account that signed in, in lower case. The access token is used once and not kept."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            token = await c.post(TOKEN_URL, json={
                "grant_type": "authorization_code", "client_id": settings.ATLASSIAN_OAUTH_CLIENT_ID,
                "client_secret": settings.ATLASSIAN_OAUTH_CLIENT_SECRET.get_secret_value(), "code": code,
                "redirect_uri": settings.ATLASSIAN_OAUTH_REDIRECT_URI,
            })
            token.raise_for_status()
            me = await c.get(PROFILE_URL, headers={"Authorization": f"Bearer {token.json()['access_token']}"})
            me.raise_for_status()
            email = me.json().get("email")
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise AtlassianLoginError(type(exc).__name__) from exc
    if not email:
        raise AtlassianLoginError("the Atlassian account shares no email")
    return email.strip().lower()
