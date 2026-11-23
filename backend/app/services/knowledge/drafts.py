"""Drafts for knowledge-base gaps, the expert's decision, and the markdown export.

Nothing is published: an approved draft gets the next article id and can be exported as markdown in the knowledge
base's own format. data/ is read-only, so writing it into the runbooks (or Confluence) is a separate step.
"""

import re
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.knowledge_builder.articles import articles
from app.agents.knowledge_builder.config import get_config
from app.agents.knowledge_builder.drafting import FIELDS, check_draft, draft_article, fields_of, has_gaps, markdown, people_of
from app.agents.knowledge_builder.matching import known_application
from app.core.config import settings
from app.llm import ModelError
from app.models.knowledge import KBDraft, ResolvedCase
from app.models.ticket import Ticket

WORDS = re.compile(r"[a-z0-9]{3,}")
KB_NUMBER = re.compile(r"^(KB-[A-Z]+)-(\d+)$")


class DraftError(ValueError):
    """The decision does not fit the draft, e.g. approving one with gaps."""


class AlreadyDecided(DraftError):
    """An expert has already decided on this draft."""


def _similar(a: str, b: str) -> float:
    wa, wb = set(WORDS.findall(a.casefold())), set(WORDS.findall(b.casefold()))
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def draft_for_gap(db: Session, ticket: Ticket, case: ResolvedCase, notes: str, use_model: bool) -> tuple[dict, ModelError | None]:
    """Decide what a new gap needs, and record it on the case. Returns what to record in the run, and any model error."""
    app = known_application(ticket.application)
    if app is None:
        case.gap_kind = "outside_kb"
        return {"draft": "none", "reason": "Not an application in the knowledge base"}, None

    for open_draft in db.scalars(select(KBDraft).where(KBDraft.application == app, KBDraft.status == "draft")):
        first = db.get(ResolvedCase, open_draft.source_ticket_ids[0])
        overlap = _similar(f"{case.summary} {case.description}", f"{first.summary} {first.description}") if first else 0.0
        if overlap >= get_config().draft_similar:
            if ticket.id not in open_draft.source_ticket_ids:
                open_draft.source_ticket_ids = [*open_draft.source_ticket_ids, ticket.id]
            case.gap_kind, case.draft_id = "known_issue", open_draft.id
            return {"draft": "joined", "draft_id": open_draft.id}, None

    if not (settings.LLM_ENABLED and use_model):
        return {"draft": "waiting", "reason": "The model is off; the draft is written when it is on"}, None
    try:
        answer, audit, hidden = draft_article([(ticket, notes)], app)
    except ModelError as exc:
        return {"draft": "failed", "error": type(exc).__name__}, exc

    record = {"kind": answer.kind, "reason": answer.reason, "audit": asdict(audit)}
    case.gap_kind = answer.kind
    if answer.kind != "known_issue":
        return {**record, "draft": "none"}, None
    fields = fields_of(answer)
    hidden = [*hidden, *people_of([ticket])]  # what was masked, and the people on the ticket even if not in its text
    if problems := check_draft(fields, f"{ticket.summary}\n{ticket.description}\n{notes}", hidden):
        return {**record, "draft": "rejected_by_checks", "problems": problems}, None  # not shown to anyone
    draft = KBDraft(application=app, source_ticket_ids=[ticket.id], **fields)
    db.add(draft)
    db.flush()
    case.draft_id = draft.id
    return {**record, "draft": "created", "draft_id": draft.id}, None


def next_kb_id(db: Session, application: str) -> str:
    """The next free article id for the application, after its articles and any approved drafts: KB-PAY-005 -> KB-PAY-006."""
    taken = [a.kb_id for a in articles().values() if a.app == application]
    taken += [d for d in db.scalars(select(KBDraft.kb_id).where(KBDraft.application == application, KBDraft.kb_id.is_not(None)))]
    numbers = [(m.group(1), int(m.group(2))) for kb in taken if (m := KB_NUMBER.match(kb))]
    prefix = numbers[0][0] if numbers else f"KB-{re.sub(r'[^A-Z]', '', application.upper())[:3]}"
    return f"{prefix}-{max((n for _, n in numbers), default=0) + 1:03d}"


def review_draft(db: Session, draft: KBDraft, action: str, reviewer: str, fields: dict | None = None,
                 reason_code: str | None = None, note: str | None = None) -> KBDraft:
    """Record the expert's decision.

    approved  the draft stands as written; nothing may be left "[expert to add]"
    edited    the expert's own text replaces the draft and is approved; the same checks for parts and personal data apply
    rejected  not worth an article (a reason_code is required)
    """
    if draft.status != "draft":
        raise AlreadyDecided(f"This draft is already {draft.status}")
    people = people_of(list(db.scalars(select(Ticket).where(Ticket.id.in_(draft.source_ticket_ids)))))
    if action in ("approved", "edited"):
        changes = {k: v for k, v in (fields or {}).items() if v is not None} if action == "edited" else {}
        final = {f: getattr(draft, f) for f in FIELDS} | changes
        if action == "edited" and final == {f: getattr(draft, f) for f in FIELDS}:
            raise DraftError("An edit needs changed text")
        if problems := check_draft(final, None, people):
            raise DraftError("The article cannot be approved: " + "; ".join(problems))
        if has_gaps(final):
            raise DraftError("Fill in every [expert to add] before approving")
        for f, value in final.items():
            setattr(draft, f, value)
        draft.kb_id, draft.status = next_kb_id(db, draft.application), "approved"
    elif reason_code is None:
        raise DraftError("A rejection needs a reason_code")
    else:
        draft.status = "rejected"
    draft.reviewer, draft.reason_code, draft.note, draft.decided_at = reviewer.strip(), reason_code, note, datetime.now(UTC)
    db.commit()
    return draft


def export(draft: KBDraft) -> str:
    """The draft, or the approved article, as markdown in the knowledge base's own format."""
    return markdown(draft.kb_id, {f: getattr(draft, f) for f in FIELDS}, draft.source_ticket_ids)
