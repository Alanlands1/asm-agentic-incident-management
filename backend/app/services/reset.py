"""Demo reset: undo what the agents wrote on the open Jira issues, clear the agents' results and restart every SLA clock.

Closed tickets (the history the agents learn from) and people's own comments are kept, in Jira and here.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.incident import FirstMessage
from app.models.jira import JiraSync
from app.models.ticket import AgentRun, Comment, PipelineStatus, Storm, Ticket
from app.services import atlassian, jira
from app.services.atlassian import AtlassianError

logger = logging.getLogger("app.reset")

OURS = jira.SYSTEM  # how every comment the system writes on an issue starts
BOTS = (jira.AGENTS_BOT, jira.SLA_BOT, jira.COMMAND_BOT)  # authors of the stored copies of those comments


@dataclass
class ResetResult:
    tickets: int = 0  # open tickets reset here
    jira_issues: int = 0  # open Jira issues cleaned
    jira_comments_deleted: int = 0
    jira_moved_back: int = 0
    jira_priorities_restored: int = 0
    jira_errors: list[str] = field(default_factory=list)


async def _clean_issue(c, key: str, me: str, result: ResetResult) -> str | None:
    """Delete our comments, remove our labels and put the issue back in the priority and status it was created in.
    Returns the issue's priority name after the reset."""
    comments = await atlassian.call(c, "GET", f"/rest/api/3/issue/{key}/comment", params={"maxResults": 100})
    for comment in comments["comments"]:
        if comment["author"].get("accountId") == me and jira.adf_text(comment["body"]).strip().startswith(OURS):
            await atlassian.call(c, "DELETE", f"/rest/api/3/issue/{key}/comment/{comment['id']}")
            result.jira_comments_deleted += 1
    labels = [{"remove": label} for label in jira.LABELS]
    await atlassian.call(c, "PUT", f"/rest/api/3/issue/{key}", json={"update": {"labels": labels}})

    issue = await atlassian.call(c, "GET", f"/rest/api/3/issue/{key}",
                                 params={"fields": "status,priority", "expand": "changelog"})
    histories = sorted(issue["changelog"]["histories"], key=lambda h: h["created"])

    # the reporter's priority: a review or "ams agree" may have changed it since
    priority = (issue["fields"].get("priority") or {}).get("name")
    first_priority = next((i["fromString"] for h in histories for i in h["items"] if i["field"] == "priority"), None)
    if first_priority and first_priority != priority:
        await atlassian.call(c, "PUT", f"/rest/api/3/issue/{key}", json={"fields": {"priority": {"name": first_priority}}})
        priority = first_priority
        result.jira_priorities_restored += 1

    moves = [h for h in histories if any(i["field"] == "status" for i in h["items"])]
    if not moves:
        return priority
    first = next(i["fromString"] for i in moves[0]["items"] if i["field"] == "status")
    if issue["fields"]["status"]["name"].casefold() == first.casefold():
        return priority
    url = f"/rest/api/3/issue/{key}/transitions"
    step = next((s for s in (await atlassian.call(c, "GET", url))["transitions"]
                 if s["to"]["name"].casefold() == first.casefold()), None)
    if step is None:
        result.jira_errors.append(f"{key}: no transition back to {first}")
        return priority
    await atlassian.call(c, "POST", url, json={"transition": {"id": step["id"]}})
    result.jira_moved_back += 1
    return priority


async def reset_demo(db: AsyncSession, rerun: bool = True) -> ResetResult:
    """Reset every open ticket to its first state, in Jira and here, then (by default) start the agents again."""
    if jira.sync_lock.locked() or jira.agents_lock.locked():
        raise jira.JiraError("A Jira sync or an agent pass is running: try again in a minute")
    result = ResetResult()
    async with jira.sync_lock, jira.agents_lock:
        open_ids = list(await db.scalars(
            select(Ticket.id).where(Ticket.closed_at.is_(None), Ticket.pipeline_status != PipelineStatus.HISTORICAL)))
        jira_ids = list(await db.scalars(select(Ticket.id).where(Ticket.id.in_(open_ids), Ticket.source == "JIRA")))
        await db.commit()  # no transaction open while Jira answers

        priorities: dict[str, str] = {}  # Jira key -> its priority after the reset
        if jira_ids and settings.JIRA_WRITE_BACK:
            async with atlassian.client() as c:
                me = (await atlassian.call(c, "GET", "/rest/api/3/myself"))["accountId"]
                for key in jira_ids:
                    try:
                        if priority := await _clean_issue(c, key, me, result):
                            priorities[key] = priority
                        result.jira_issues += 1
                    except AtlassianError as exc:
                        result.jira_errors.append(f"{key}: {exc}")
                        logger.warning("Reset: Jira issue %s not cleaned: %s", key, exc)

        now = datetime.now(UTC)
        await db.execute(delete(AgentRun).where(AgentRun.ticket_id.in_(open_ids)))  # reviews and ratings go with them
        await db.execute(delete(FirstMessage).where(FirstMessage.ticket_id.in_(open_ids)))
        await db.execute(delete(Comment).where(Comment.ticket_id.in_(open_ids), Comment.author_email.in_(BOTS)))
        await db.execute(update(Ticket).where(Ticket.id.in_(open_ids)).values(
            pipeline_status=PipelineStatus.PENDING, storm_id=None, status="new",
            resolution_notes=None, resolved_at=None,  # a closure note from before the reset is not this round's work
            opened_at=now.replace(tzinfo=None)))  # the SLA clock starts again; a Jira sync never moves it back
        # Triage reads the reporter's priority from here, and a later sync must not see the restore as a person's decision
        for ticket in await db.scalars(select(Ticket).where(Ticket.id.in_(priorities))):
            name = priorities[ticket.id]
            ticket.reported_priority, ticket.reported_priority_label = jira.PRIORITY_NUMBER.get(name), name
            ticket.raw = {**(ticket.raw or {}), "priority": name}
        await db.execute(delete(Storm).where(~Storm.id.in_(select(Ticket.storm_id).where(Ticket.storm_id.is_not(None)))))
        # marks the reset: status moves before it no longer stop move_triaged from moving an issue again
        db.add(JiraSync(trigger="reset", projects="", started_at=now, finished_at=now))
        await db.commit()
        result.tickets = len(open_ids)

    logger.info("Reset: %s", result)
    if rerun and open_ids:
        jira.start_agents()
    return result
