"""Resolution agent: what the agent reads about a ticket, and how a model call is made about it."""

from dataclasses import dataclass, field

from pydantic import BaseModel

from app.core.registry import load_registry
from app.llm import CallSpec, call_model
from app.privacy.masking import MaskedText, Masker


@dataclass(frozen=True)
class CaseInput:
    """A ticket, copied out of the database so no session is needed while the agent works."""

    id: str
    summary: str
    application: str | None
    body: str  # the description plus the reporter's replies
    reporter_name: str | None = None
    reporter_email: str | None = None
    assignee: str | None = None
    kb_weights: dict[str, float] = field(default_factory=dict)  # KB id -> ranking factor from engineers' ratings


def case_text(case: CaseInput) -> str:
    return f"Application: {case.application or 'not given'}\nSummary: {case.summary}\nDescription:\n{case.body}"


def masker_for(case: CaseInput) -> Masker:
    return Masker(known_names=[case.reporter_name, case.assignee], known_emails=[case.reporter_email])


def spec_for[T: BaseModel](name: str, output: type[T]) -> CallSpec[T]:
    prompt = load_registry("prompts.yaml")[name]
    return CallSpec(
        name=name,
        prompt_version=prompt["version"],
        system=prompt["system"],
        output=output,
        wrapper=prompt["wrapper"],
        retry_note=prompt["retry_note"],
        max_tokens=prompt["max_tokens"],
    )


def call_masked[T: BaseModel](spec: CallSpec[T], masker: Masker, text: str):
    """Blocking. Masks the text with this masker (so placeholders stay the same across calls), then calls the model."""
    user: MaskedText = masker.mask(text)
    return call_model(spec, user, masker)
