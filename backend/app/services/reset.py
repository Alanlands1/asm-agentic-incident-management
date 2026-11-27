"""Demo reset: undo what the agents wrote on the open Jira issues, clear the agents' results and restart every SLA clock.

Closed tickets (the history the agents learn from) and people's own comments are kept, in Jira and here.

With a saved baseline (DEMO_BASELINE_DIR, app/services/baseline.py) the reset instead puts Jira and the console back
exactly as they were when it was taken.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.incident import FirstMessage
from app.models.jira import JiraProject, JiraSync
from app.models.ticket import AgentRun, Comment, PipelineStatus, Storm, Ticket
from app.services import atlassian, baseline, jira
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
    jira_closed: int = 0  # issues created after the baseline: Jira cannot delete them, so they are closed
    jira_errors: list[str] = field(default_factory=list)
    restored_from: str | None = None  # when the restored baseline was taken; None = no baseline was used


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


async def _restore_issue(c, saved: dict, me: str, result: ResetResult, dry_run: bool) -> None:
    """Put one Jira issue back as the baseline saved it: our later comments deleted, its labels, priority, assignee and
    status as they were. People's comments and the comments in the baseline are never deleted."""
    key = saved["key"]

    async def write(method: str, url: str, json: dict | None = None) -> None:
        if not dry_run:
            await atlassian.call(c, method, url, json=json)

    now = await baseline.read_issue(c, key)
    kept = {comment["id"] for comment in saved["comments"]}
    for comment in now["comments"]:
        if comment["author_id"] == me and comment["ours"] and comment["id"] not in kept:
            await write("DELETE", f"/rest/api/3/issue/{key}/comment/{comment['id']}")
            result.jira_comments_deleted += 1
    fields: dict = {}
    if sorted(now["labels"]) != sorted(saved["labels"]):
        fields["labels"] = saved["labels"]
    if saved["priority"] and now["priority"] != saved["priority"]:
        fields["priority"] = {"name": saved["priority"]}
        result.jira_priorities_restored += 1
    if fields:
        await write("PUT", f"/rest/api/3/issue/{key}", {"fields": fields})
    if now["assignee_id"] != saved["assignee_id"]:
        await write("PUT", f"/rest/api/3/issue/{key}/assignee", {"accountId": saved["assignee_id"]})
    if now["status"].casefold() == saved["status"].casefold():
        return
    url = f"/rest/api/3/issue/{key}/transitions"
    step = next((s for s in (await atlassian.call(c, "GET", url))["transitions"]
                 if s["to"]["name"].casefold() == saved["status"].casefold()), None)
    if step is None:
        result.jira_errors.append(f"{key}: no transition back to {saved['status']}")
        return
    await write("POST", url, {"transition": {"id": step["id"]}})
    result.jira_moved_back += 1


async def _close_issue(c, key: str, result: ResetResult, dry_run: bool) -> None:
    """Move an issue created after the baseline to a done status, found the way jira.close_issue finds it."""
    url = f"/rest/api/3/issue/{key}/transitions"
    steps = (await atlassian.call(c, "GET", url))["transitions"]
    step = next((s for s in steps if (s["to"].get("statusCategory") or {}).get("key") == "done"), None)
    if step is None:
        result.jira_errors.append(f"{key}: created after the baseline and has no move to a done status")
        return
    if not dry_run:
        await atlassian.call(c, "POST", url, json={"transition": {"id": step["id"]}})
    result.jira_closed += 1


async def _restore(db: AsyncSession, saved: baseline.Baseline, result: ResetResult, dry_run: bool) -> None:
    """Put Jira, then the console's tables, back as the baseline saved them. A dry run counts the same and writes
    nothing: Jira is only read, and the database transaction is rolled back."""
    projects = list(await db.scalars(select(JiraProject.key)))
    await db.commit()  # no transaction open while Jira answers
    if settings.JIRA_WRITE_BACK:
        async with atlassian.client() as c:
            me = (await atlassian.call(c, "GET", "/rest/api/3/myself"))["accountId"]
            for issue in saved.issues:
                try:
                    await _restore_issue(c, issue, me, result, dry_run)
                    result.jira_issues += 1
                except AtlassianError as exc:
                    result.jira_errors.append(f"{issue['key']}: {exc}")
                    logger.warning("Reset: Jira issue %s not restored: %s", issue["key"], exc)
            known = {issue["key"] for issue in saved.issues}
            for issue in await jira.search_issues(projects) if projects else []:
                done = (issue["fields"]["status"].get("statusCategory") or {}).get("key") == "done"
                if issue["key"] in known or done:
                    continue
                try:
                    await _close_issue(c, issue["key"], result, dry_run)
                except AtlassianError as exc:
                    result.jira_errors.append(f"{issue['key']}: {exc}")
                    logger.warning("Reset: Jira issue %s not closed: %s", issue["key"], exc)

    now = datetime.now(UTC)
    result.tickets = await db.run_sync(lambda s: baseline.restore_db(s, saved, now))
    # marks the reset: status moves before it no longer stop move_triaged from moving an issue again
    db.add(JiraSync(trigger="reset", projects="", started_at=now, finished_at=now))
    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    result.restored_from = saved.taken_at.isoformat()


async def reset_demo(db: AsyncSession, rerun: bool = True, dry_run: bool = False) -> ResetResult:
    """Reset every open ticket to its first state, in Jira and here, then (by default) start the agents again.

    With a saved baseline (DEMO_BASELINE_DIR) Jira and the console are put back as they were then instead, and the
    agents are not started, whatever rerun says: the restored state is final. dry_run, with a baseline only, returns
    the same counts and writes nothing."""
    if jira.sync_lock.locked() or jira.agents_lock.locked():
        raise jira.JiraError("A Jira sync or an agent pass is running: try again in a minute")
    saved = baseline.load(settings.DEMO_BASELINE_DIR)
    if saved is None and settings.DEMO_BASELINE_DIR is not None:  # a wrong path must not fall back to wiping the tickets
        raise jira.JiraError(f"No baseline in {settings.DEMO_BASELINE_DIR}: fix DEMO_BASELINE_DIR or remove it")
    if dry_run and saved is None:
        raise jira.JiraError("A dry run needs a saved baseline: set DEMO_BASELINE_DIR in backend/.env")
    result = ResetResult()
    async with jira.sync_lock, jira.agents_lock:
        if saved is not None:
            await _restore(db, saved, result, dry_run)
            logger.info("Reset to the baseline of %s%s: %s", result.restored_from, " (dry run)" if dry_run else "", result)
            return result
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
