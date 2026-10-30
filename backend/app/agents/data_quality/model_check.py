"""Model stage of the Data Quality agent: is a ticket the rules could not decide complete enough to act on?

The answer schema is code: it is what the eval measures, so changing it goes through review. The prompt text, its
version and the ticket layout come from data/registry/data_quality/prompts.yaml (or its admin override).
"""

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.common.config import config_version
from app.common.llm import CallAudit, CallSpec, call_model
from app.common.privacy.masking import Masker
from app.common.registry import load_registry, register_document
from app.models.ticket import Ticket

DQ_PROMPT_NAME = "dq_completeness"  # the entry in prompts.yaml

# Changing these changes the eval labels: bump the version in prompts.yaml with it.
Missing = Literal["what_happened", "when", "who_affected", "error_message", "steps_to_reproduce", "application"]


class DQCompleteness(BaseModel):
    complete: bool = Field(description="Whether an engineer can start investigating without contacting the reporter")
    missing: list[Missing] = Field(description="What the support team would still need; empty when complete")
    reason: str = Field(description="One or two sentences for the support team")
    chase_email: str | None = Field(
        description="When incomplete, a short, polite email to the reporter asking only for what is missing. Otherwise null"
    )

    @model_validator(mode="after")
    def consistent(self) -> "DQCompleteness":
        if self.complete and self.missing:
            raise ValueError("a complete ticket cannot have missing items")
        if not self.complete and not (self.missing and self.chase_email):
            raise ValueError("an incomplete ticket needs missing items and a chase email")
        return self


def dq_completeness_spec() -> CallSpec[DQCompleteness]:
    return _build_spec(config_version())


@lru_cache(maxsize=1)
def _build_spec(version: int) -> CallSpec[DQCompleteness]:
    """The call as configured now; rebuilt after an admin change (the config version moves)."""
    prompt = load_registry("data_quality/prompts.yaml")[DQ_PROMPT_NAME]
    return CallSpec(
        name=DQ_PROMPT_NAME,
        prompt_version=prompt["version"],
        system=prompt["system"],
        output=DQCompleteness,
        wrapper=prompt["wrapper"],
        retry_note=prompt["retry_note"],
        max_tokens=prompt["max_tokens"],
    )


register_document("data_quality_prompts", "data_quality/prompts.yaml", dq_completeness_spec)


def check_completeness(ticket: Ticket, body: str) -> tuple[DQCompleteness, CallAudit]:
    """One model call on the masked ticket. Raises app.common.llm.ModelError when there is no usable answer."""
    prompt = load_registry("data_quality/prompts.yaml")[DQ_PROMPT_NAME]
    masker = Masker(known_names=[ticket.reporter_name], known_emails=[ticket.reporter_email])
    text = prompt["ticket_template"].format(
        application=ticket.application or prompt["not_given"],
        summary=ticket.summary,
        attachments=ticket.attachments or prompt["not_given"],
        body=body,
    )
    return call_model(dq_completeness_spec(), masker.mask(text), masker)
