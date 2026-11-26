"""Work out a fix with the model, on the ticket page: for a ticket no runbook covers, or as a second opinion.

Each turn is one structured model call through app.llm: the ticket, the runbook fix (if any), the fixes already tried,
the engineer's note and the conversation so far are masked together, so a name gets the same placeholder in every turn.
The model answers the engineer and, once it has enough to go on, proposes a fix (cause, steps, how to check it).
Turns are stored as agent runs (agent "fix_chat"): they stay with the ticket and show in "Who did what".
Each turn also carries where the ticket stands (stage, priority, each agent's last result in one line). The model can
name agents whose stored result the console prints (`show`: nothing runs, nothing is retyped), and, only when the
engineer says to, one agent to run again with the extra details the engineer gave (`rerun`).
"Use as the fix" turns a proposal into the ticket's suggested fix (a Resolution run marked source "chat"), so the
usual loop follows: try it, say if it worked, closure note, lead review, Send; Knowledge Builder learns from it.
"""

import logging
import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.agents.resolution.retrieval import retrieve
from app.core.config import config_version
from app.core.registry import load_registry, register_document
from app.llm import CallSpec
from app.models.knowledge import ResolvedCase
from app.models.ticket import AgentRun, PipelineStatus, Ticket
from app.privacy.masking import Masker
from app.services.data_quality import last_run, reporter_text
from app.services.fix import answers, tried
from app.services.jira import AGENTS_BOT, COMMAND_BOT, SLA_BOT, SYSTEM
from app.services.lead_review import priority_of

logger = logging.getLogger("app.fix_chat")

AGENT = "fix_chat"
PROMPT = "fix_chat"  # the entry in data/registry/prompts.yaml
MAX_TURNS = 20  # turns kept in the prompt; older ones drop off
FIXING = (PipelineStatus.REVIEWED, PipelineStatus.NEEDS_LEAD)  # where a proposal can become the suggested fix
SIMILAR = 3  # closed tickets shown to the model
ARTICLES = 3  # knowledge-base articles from the search
EXCERPT = 900  # characters of each article or close note
BOTS = (AGENTS_BOT, SLA_BOT, COMMAND_BOT)
AgentName = Literal["data_quality", "triage", "resolution", "closure_quality"]
NAMES = {"data_quality": "Data Quality", "triage": "Triage", "resolution": "Resolution", "closure_quality": "Closure Quality"}
REASON = 300  # characters of an agent's reason in the status
# Where each agent may run again from the chat. Data Quality and Triage also on a reviewed ticket (the Run buttons stop
# before that): the engineer asked, with new details. Not once the fix is confirmed: the work after it would be lost.
RERUN_AT = {
    "data_quality": (PipelineStatus.PENDING, PipelineStatus.AWAITING_INFO, PipelineStatus.DQ_PASSED, PipelineStatus.TRIAGED,
                     PipelineStatus.ERROR, PipelineStatus.REVIEWED),
    "triage": (PipelineStatus.DQ_PASSED, PipelineStatus.TRIAGED, PipelineStatus.REVIEWED),
    "resolution": (PipelineStatus.REVIEWED,),
    "closure_quality": (PipelineStatus.FIX_CONFIRMED, PipelineStatus.IN_REVIEW, PipelineStatus.APPROVED),
}
PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")  # a saved case is masked already; its placeholders are not this ticket's
WORD = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
# Words every ticket has; two tickets sharing them are not alike.
COMMON = frozenset("""the and for are was were has have had not but with this that from they them their there into onto
our your you all any can cannot since today yesterday please thanks thank regards hello dear team support issue problem
still also only just when what which who how why been being does did done its out get got getting too very more most some
same other others than then now new one two need needs needed working work works customer customers user users""".split())


class ChatError(ValueError):
    """The chat does not fit the ticket now: closed, or nothing to use."""


class ChatFix(BaseModel):
    root_cause: str = Field(description="The most likely cause, in one or two sentences")
    steps: list[str] = Field(min_length=1, description="The steps to fix it, in order; one action per step")
    check: str = Field(description="How the engineer confirms it is fixed")


class Rerun(BaseModel):
    agent: AgentName = Field(description="The agent to run again")
    note: str = Field(description="The extra details the engineer gave for this run, in their words; empty when none")


class ChatAnswer(BaseModel):
    reply: str = Field(description="Your answer to the engineer's latest message: short, plain text")
    fix: ChatFix | None = Field(description="A complete proposed fix once there is enough to go on; null while you "
                                            "still need facts from the engineer")
    show: list[AgentName] = Field(description="Agents whose stored result the console prints under your reply; empty "
                                              "when none is asked about. Do not retype those details in `reply`")
    rerun: Rerun | None = Field(description="Only when the engineer's latest message says to run an agent again; "
                                            "null otherwise")


def chat_spec() -> CallSpec[ChatAnswer]:
    return _build_spec(config_version())


@lru_cache(maxsize=1)
def _build_spec(version: int) -> CallSpec[ChatAnswer]:
    """The call as configured now; rebuilt after an admin change to the prompt."""
    prompt = load_registry("prompts.yaml")[PROMPT]
    return CallSpec(name=PROMPT, prompt_version=prompt["version"], system=prompt["system"], output=ChatAnswer,
                    wrapper=prompt["wrapper"], retry_note=prompt["retry_note"], max_tokens=prompt["max_tokens"])


register_document("fix_chat_prompts", "prompts.yaml", chat_spec)


def turns(ticket: Ticket) -> list[AgentRun]:
    return [r for r in ticket.agent_runs if r.agent == AGENT]


def team_notes(ticket: Ticket) -> str:
    """What engineers wrote on the ticket (internal notes and replies), not the reporter's and not the system's."""
    notes = [c for c in ticket.comments if not c.from_reporter and c.author_email not in BOTS and not c.body.startswith(SYSTEM)]
    return "\n".join(f"- {c.author_email}: {c.body.strip()}" for c in notes)


def _words(*texts: str | None) -> set[str]:
    return set(WORD.findall(" ".join(t or "" for t in texts).casefold())) - COMMON


def similar_cases(db: Session, ticket: Ticket) -> str:
    """The closed tickets most like this one: Knowledge Builder's saved cases (masked already, so their placeholders
    are replaced) and any other closed ticket with close notes (masked with the rest of this turn). Same application
    first, then shared words. Each with its close notes and the article it matched."""
    found = []  # (ticket id, application, article, summary, description, notes)
    for c in db.scalars(select(ResolvedCase).where(ResolvedCase.ticket_id != ticket.id)):
        found.append((c.ticket_id, c.application, c.kb_article_id, *(PLACEHOLDER.sub("[someone]", t or "")
                                                                       for t in (c.summary, c.description, c.notes))))
    saved = {f[0] for f in found}
    for t in db.scalars(select(Ticket).where(Ticket.id != ticket.id, Ticket.status.in_(("closed", "resolved")),
                                             Ticket.resolution_notes.is_not(None), Ticket.resolution_notes != "")):
        if t.id not in saved:
            found.append((t.id, t.application, None, t.summary, t.description, t.resolution_notes))
    mine, title = _words(ticket.summary, ticket.description), _words(ticket.summary)
    scored = []
    for case in found:  # alike: titles share two words, or one and the texts three, or the texts five
        shared, in_title = len(mine & _words(case[3], case[4])), len(title & _words(case[3]))
        if in_title >= 2 or shared >= 5 or (in_title and shared >= 3):
            scored.append((bool(ticket.application) and case[1] == ticket.application, in_title, shared, case))
    scored.sort(key=lambda s: s[:3], reverse=True)
    return "\n\n".join(
        f"{tid} ({app or 'no application'}{', article ' + kb if kb else ''}): {summary}\nClose notes: {notes[:EXCERPT]}"
        for *_, (tid, app, kb, summary, _, notes) in scored[:SIMILAR]
    )


async def articles(db: AsyncSession, ticket: Ticket, message: str) -> str:
    """Knowledge-base articles the runbook search finds for the ticket and the engineer's message, same application
    first. Empty when the search is not available (e.g. no Postgres)."""
    try:
        chunks = await retrieve(db, f"{ticket.summary} {message}", top_n=12)
    except Exception:  # the chat still works without them
        logger.warning("Knowledge-base search for the chat failed", exc_info=True)
        await db.rollback()
        return ""
    chunks.sort(key=lambda c: c.app != ticket.application)  # stable: keeps the search's order within each group
    seen, found = set(), []
    for c in chunks:
        if c.kb_id and c.kb_id not in seen:
            seen.add(c.kb_id)
            found.append(f"{c.kb_id} ({c.app}): {c.content.strip()[:EXCERPT]}")
        if len(found) == ARTICLES:
            break
    return "\n\n".join(found)


def cannot_rerun(ticket: Ticket, agent: str) -> str | None:
    """Why this agent cannot run again on the ticket now; None when it can."""
    if ticket.closed_at is not None:
        return "the ticket is closed"
    if ticket.pipeline_status not in RERUN_AT[agent]:
        return f"the ticket is at stage '{ticket.pipeline_status}'"
    if agent == "closure_quality" and not (ticket.resolution_notes or "").strip():
        return "there is no closure note yet"
    return None


def status(db: Session, ticket: Ticket) -> str:
    """Where the ticket stands, in a few lines: stage, priority, each agent's last result, what can run again."""
    lines = [f"Stage: {ticket.pipeline_status}",
             f"Priority: reported {_p(ticket.reported_priority)}, in force {_p(priority_of(db, ticket))}"]
    for agent, name in NAMES.items():
        run = last_run(ticket, agent)
        if run is None:
            lines.append(f"{name}: not run yet")
            continue
        o = run.output or {}
        reason = str(o.get("reason") or (o.get("answer") or {}).get("reason") or o.get("root_cause") or "").strip()
        lines.append(f"{name}: {run.verdict}{' - ' + reason[:REASON] if reason else ''}")
    can = [name for agent, name in NAMES.items() if cannot_rerun(ticket, agent) is None]
    lines.append(f"Can run again now: {', '.join(can) or 'none'}")
    return "\n".join(lines)


def _p(priority: int | None) -> str:
    return f"P{priority}" if priority else "not set"


def prepare(db: Session, ticket: Ticket, message: str, kb: str = "") -> tuple[str, Masker]:
    """The text the model reads for this turn, and the masker that hides personal details in it. Not masked yet."""
    if ticket.closed_at is not None:
        raise ChatError(f"Ticket {ticket.id} is closed")
    prompt = load_registry("prompts.yaml")[PROMPT]
    none = prompt["not_given"]
    fix = last_run(ticket, "resolution")
    runbook = none
    if fix is not None and fix.verdict == "resolved":
        o = fix.output
        source = "the chat" if o.get("source") == "chat" else ", ".join(o.get("references") or []) or "the runbook"
        runbook = "\n".join([f"From {source}. Cause: {o.get('root_cause') or none}",
                             *(f"{i}. {s}" for i, s in enumerate(o.get("steps") or [], 1))])
    elif fix is not None:
        runbook = "No runbook article covers this ticket."
    history = "\n".join(f"Engineer: {r.output.get('question', '')}\nAssistant: {r.output.get('reply', '')}"
                        for r in [t for t in turns(ticket) if not t.output.get("cleared")][-MAX_TURNS:]) or none
    text = prompt["ticket_template"].format(
        summary=ticket.summary, application=ticket.application or none, body=reporter_text(ticket),
        runbook=runbook, tried=tried([r for r in ticket.agent_runs if r.agent == "resolution"], answers(db, ticket.id)) or none,
        history=history, message=message, notes=team_notes(ticket) or none, cases=similar_cases(db, ticket) or none,
        kb=kb or none, status=status(db, ticket),
    )
    masker = Masker(known_names=[ticket.reporter_name, ticket.assignee], known_emails=[ticket.reporter_email])
    return text, masker


def save_turn(db: Session, ticket: Ticket, message: str, author: str, answer: ChatAnswer, audit: dict,
              rerun: dict | None = None) -> AgentRun:
    """Store one turn: the reply, the stored results it points at (`shown`: agent -> run id) and what a rerun did.
    Not committed."""
    shown = {a: r.id for a in dict.fromkeys(answer.show) if (r := last_run(ticket, a)) is not None}
    run = AgentRun(ticket_id=ticket.id, agent=AGENT, verdict="proposed" if answer.fix else "answered",
                   output={"question": message, "asked_by": author, "reply": answer.reply,
                           "fix": answer.fix.model_dump() if answer.fix else None, "shown": shown, "rerun": rerun,
                           "audit": audit})
    db.add(run)
    return run


def clear(ticket: Ticket) -> int:
    """Start the ticket's chat afresh: its turns leave the chat window and the model's view of the chat so far. They
    stay stored, for the activity log and for a fix that came from one. Returns how many were cleared. Not committed."""
    fresh = [r for r in turns(ticket) if not r.output.get("cleared")]
    for r in fresh:
        r.output = {**r.output, "cleared": True}
    return len(fresh)


def use(db: Session, ticket: Ticket, run_id: int, reviewer: str, input_hash: str | None) -> AgentRun:
    """Make a proposal from the chat the ticket's suggested fix. `input_hash`: what Resolution would see now, so the
    next agents' pass does not replace the chosen fix with a new search. Not committed."""
    chat = next((r for r in turns(ticket) if r.id == run_id), None)
    if ticket.closed_at is not None or ticket.pipeline_status not in FIXING:
        raise ChatError(f"Ticket {ticket.id} is not being fixed now")
    if chat is None or not chat.output.get("fix"):
        raise ChatError("That answer has no proposed fix")
    proposal = chat.output["fix"]
    run = AgentRun(ticket_id=ticket.id, agent="resolution", verdict="resolved", input_hash=input_hash, output={
        "verdict": "resolved", "root_cause": proposal["root_cause"], "steps": proposal["steps"], "references": [],
        "confidence": "medium", "source": "chat", "chat_run_id": chat.id, "chosen_by": reviewer,
        "notes": f"AI suggestion from the chat, chosen by {reviewer}; not from a runbook. Check: {proposal['check']}",
    })
    db.add(run)
    return run
