"""Confluence copy: page text conversion and the sync endpoints, with Confluence itself faked."""

import pytest

from app.agents.resolution.chunking import chunk_knowledge_base
from app.services import confluence

STORAGE = (
    "<table><tbody><tr><th>Field</th><th>Value</th></tr><tr><td>Tier</td><td><strong>Tier 1</strong></td></tr></tbody></table>"
    '<ac:structured-macro ac:name="info"><ac:parameter ac:name="title">hidden</ac:parameter>'
    "<ac:rich-text-body><p>Payroll window&ndash;P1.</p></ac:rich-text-body></ac:structured-macro>"
    "<h2>Known issues</h2><ul><li>Job <code>PAY_CALC</code> fails<ul><li>restart it</li></ul></li></ul>"
    '<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[select 1;]]></ac:plain-text-body></ac:structured-macro>'
)


def test_page_text():
    assert confluence.page_text(STORAGE) == (
        "| Field | Value |\n| Tier | **Tier 1** |\n\n"
        "Payroll window–P1.\n\n"
        "## Known issues\n\n"
        "- Job `PAY_CALC` fails\n  - restart it\n\n"
        "select 1;"
    )


@pytest.fixture
def fake_confluence(monkeypatch):
    state = {"pages": [
        {"id": "1", "title": "PayrollPro — Application Support Knowledge Base", "version": 1,
         "body": "| Field | Value |\n| Application ID | APP-PAY |\n\n"
                 "## Known issues\n\n### KB-PAY-001 — Payslip blank\n\nRestart it.",
         "url": None},
        {"id": "2", "title": "OrderHub", "version": 1, "body": "text", "url": None},
    ]}

    async def fetch(space_id):
        assert space_id == "131075"
        return state["pages"]
    async def ingest(folder):  # the Resolution agent's ingest writes to the real database: record what it is given
        state["fed"] = chunk_knowledge_base(folder)
    monkeypatch.setattr(confluence, "fetch_pages", fetch)
    monkeypatch.setattr(confluence, "ingest_kb", ingest)
    return state


async def test_sync_creates_updates_and_removes(client, fake_confluence):
    r = await client.put("/api/v1/confluence/spaces", json=[{"key": "AMSKB", "id": "131075", "name": "AMS Knowledge Base"}])
    assert r.status_code == 200
    first = (await client.post("/api/v1/confluence/sync")).json()
    assert (first["pulled"], first["created"], first["updated"], first["removed"], first["error"]) == (2, 2, 0, 0, None)
    payroll = fake_confluence["fed"]["confluence-1.md"]  # the Resolution agent gets each page as a runbook it can chunk
    assert {(c.app, c.app_id) for c in payroll} == {("PayrollPro", "APP-PAY")}
    assert [c.kb_id for c in payroll if c.kb_id] == ["KB-PAY-001"]

    fake_confluence["pages"] = [{"id": "1", "title": "PayrollPro", "version": 2, "body": "new text", "url": None}]
    second = (await client.post("/api/v1/confluence/sync")).json()
    assert (second["created"], second["updated"], second["removed"]) == (0, 1, 1)

    pages = (await client.get("/api/v1/confluence/pages")).json()
    assert [p["id"] for p in pages] == ["1"]
    assert (await client.get("/api/v1/confluence/pages/1")).json()["body"] == "new text"
    assert len((await client.get("/api/v1/confluence/syncs")).json()) == 2


async def test_sync_without_spaces_is_recorded_as_failed(client):
    r = (await client.post("/api/v1/confluence/sync")).json()
    assert r["error"].startswith("No spaces selected")
