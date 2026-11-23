"""Work out a fix with the model, on the ticket page: for a ticket no runbook covers, or as a second opinion.

Each turn is one structured model call through app.llm: the ticket, the runbook fix (if any), the fixes already tried,
the engineer's note and the conversation so far are masked together, so a name gets the same placeholder in every turn.
The model answers the engineer and, once it has enough to go on, proposes a fix (cause, steps, how to check it).
Turns are stored as agent runs (agent "fix_chat"): they stay with the ticket and show in "Who did what".
"Use as the fix" turns a proposal into the ticket's suggested fix (a Resolution run marked source "chat"), so the
usual loop follows: try it, say if it worked, closure note, lead review, Send; Knowledge Builder learns from it.
"""

from functools import lru_cache

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import config_version
from app.core.registry import load_registry, register_document
from app.llm import CallSpec
from app.models.ticket import AgentRun, PipelineStatus, Ticket
from app.privacy.masking import Masker
from app.services.data_quality import last_run, reporter_text
from app.services.fix import answers, tried

AGENT = "fix_chat"
PROMPT = "fix_chat"  # the entry in data/registry/prompts.yaml
MAX_TURNS = 20  # turns kept in the prompt; older ones drop off
FIXING = (PipelineStatus.REVIEWED, PipelineStatus.NEEDS_LEAD)  # where a proposal can become the suggested fix


class ChatError(ValueError):
    """The chat does not fit the ticket now: closed, or nothing to use."""


class ChatFix(BaseModel):
    root_cause: str = Field(description="The most likely cause, in one or two sentences")
    steps: list[str] = Field(min_length=1, description="The steps to fix it, in order; one action per step")
    check: str = Field(description="How the engineer confirms it is fixed")


class ChatAnswer(BaseModel):
    reply: str = Field(description="Your answer to the engineer's latest message: short, plain text")
    fix: ChatFix | None = Field(description="A complete proposed fix once there is enough to go on; null while you "
                                            "still need facts from the engineer")


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


def prepare(db: Session, ticket: Ticket, message: str) -> tuple[str, Masker]:
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
                        for r in turns(ticket)[-MAX_TURNS:]) or none
    text = prompt["ticket_template"].format(
        summary=ticket.summary, application=ticket.application or none, body=reporter_text(ticket),
        runbook=runbook, tried=tried([r for r in ticket.agent_runs if r.agent == "resolution"], answers(db, ticket.id)) or none,
        history=history, message=message,
    )
    masker = Masker(known_names=[ticket.reporter_name, ticket.assignee], known_emails=[ticket.reporter_email])
    return text, masker


def save_turn(db: Session, ticket: Ticket, message: str, author: str, answer: ChatAnswer, audit: dict) -> AgentRun:
    """Store one turn. Not committed."""
    run = AgentRun(ticket_id=ticket.id, agent=AGENT, verdict="proposed" if answer.fix else "answered",
                   output={"question": message, "asked_by": author, "reply": answer.reply,
                           "fix": answer.fix.model_dump() if answer.fix else None, "audit": audit})
    db.add(run)
    return run


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
