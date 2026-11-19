"""Demo reset: a Jira issue goes back to the priority and status it was created in."""

import asyncio

from app.services import atlassian, reset


def _issue(priority: str, status: str, histories: list[dict]) -> dict:
    return {"fields": {"priority": {"name": priority}, "status": {"name": status}}, "changelog": {"histories": histories}}


def _change(at: str, field: str, before: str, after: str) -> dict:
    return {"created": at, "items": [{"field": field, "fromString": before, "toString": after}]}


def _run(monkeypatch, issue: dict) -> tuple[str | None, reset.ResetResult, list]:
    sent = []

    async def call(c, method, path, params=None, json=None):
        sent.append((method, path, json))
        if path.endswith("/comment"):
            return {"comments": []}
        if path.endswith("/transitions"):
            return {"transitions": [{"id": "11", "to": {"name": "To Do"}}]}
        return issue if method == "GET" else {}

    monkeypatch.setattr(atlassian, "call", call)
    result = reset.ResetResult()
    priority = asyncio.run(reset._clean_issue(None, "AMS-7", "me", result))
    return priority, result, sent


def test_restores_the_reporters_priority(monkeypatch):
    # reported High, a person set Medium, then Low: the reset puts High back
    issue = _issue("Low", "To Do", [_change("2026-11-18T13:30", "priority", "Medium", "Low"),
                                    _change("2026-11-18T13:20", "priority", "High", "Medium")])
    priority, result, sent = _run(monkeypatch, issue)
    assert priority == "High"
    assert result.jira_priorities_restored == 1
    assert ("PUT", "/rest/api/3/issue/AMS-7", {"fields": {"priority": {"name": "High"}}}) in sent


def test_leaves_an_unchanged_priority_and_still_moves_the_status_back(monkeypatch):
    issue = _issue("High", "In Progress", [_change("2026-11-18T13:20", "status", "To Do", "In Progress")])
    priority, result, sent = _run(monkeypatch, issue)
    assert priority == "High"
    assert result.jira_priorities_restored == 0
    assert result.jira_moved_back == 1
    assert not any(m == "PUT" and j and "fields" in j for m, _, j in sent)
