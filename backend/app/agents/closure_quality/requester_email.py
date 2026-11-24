"""Closure Quality: a draft email to the requester once the closure note is final.

One model call on the masked ticket and closure note. The code drops a draft that names a code, ID or number the ticket
does not contain. Nothing is sent from here: the engineer edits the draft and sends it.
"""

from functools import lru_cache

from pydantic import BaseModel, Field

from app.agents.closure_quality.model_check import invented
from app.core.config import config_version
from app.core.registry import load_registry, register_document
from app.llm import CallAudit, CallSpec, call_model
from app.models.ticket import Ticket
from app.privacy.masking import Masker

EMAIL_PROMPT_NAME = "closure_email"  # the entry in prompts.yaml


class RequesterEmail(BaseModel):
    subject: str = Field(description="Short subject naming the issue and saying it is resolved")
    body: str = Field(description="The email: greeting, what was wrong and what was done in plain language, "
                                  "what to do if it happens again, sign-off")


def email_spec() -> CallSpec[RequesterEmail]:
    return _build_spec(config_version())


@lru_cache(maxsize=1)
def _build_spec(version: int) -> CallSpec[RequesterEmail]:
    """The call as configured now; rebuilt after an admin change to the prompt."""
    prompt = load_registry("prompts.yaml")[EMAIL_PROMPT_NAME]
    return CallSpec(
        name=EMAIL_PROMPT_NAME,
        prompt_version=prompt["version"],
        system=prompt["system"],
        output=RequesterEmail,
        wrapper=prompt["wrapper"],
        retry_note=prompt["retry_note"],
        max_tokens=prompt["max_tokens"],
    )


register_document("data_quality_prompts", "prompts.yaml", email_spec)  # one prompts file for every call


def draft_email(ticket: Ticket, notes: str) -> tuple[RequesterEmail, CallAudit, list[str]]:
    """The draft, its audit record, and any code or number in it that the ticket does not contain (then not usable).
    Raises app.llm.ModelError when there is no usable answer."""
    prompt = load_registry("prompts.yaml")[EMAIL_PROMPT_NAME]
    masker = Masker(known_names=[ticket.reporter_name, ticket.assignee], known_emails=[ticket.reporter_email])
    text = prompt["ticket_template"].format(
        id=ticket.id, requester=ticket.reporter_name or prompt["not_given"], engineer=ticket.assignee or prompt["not_given"],
        summary=ticket.summary, body=ticket.description, notes=notes,
    )
    email, audit = call_model(email_spec(), masker.mask(text), masker)
    source = f"{ticket.id}\n{ticket.summary}\n{ticket.description}\n{notes}"
    return email, audit, invented(f"{email.subject}\n{email.body}", source)
