"""Model stage of the Knowledge Builder: which of these articles describes this resolved ticket, or none of them?

Only this stage can say that no article covers a case. The model chooses from the articles it is shown and must quote the
words of the case that match the article's symptoms; the code checks the id is one it was shown and the quote is really in
the case, and otherwise treats the answer as not sure. The prompt text comes from data/registry/prompts.yaml.
"""

from functools import lru_cache

from pydantic import BaseModel, Field

from app.agents.knowledge_builder.articles import Article
from app.core.config import config_version
from app.core.registry import load_registry, register_document
from app.llm import CallAudit, CallSpec, call_model
from app.models.ticket import Ticket
from app.privacy.masking import Masker

KB_MATCH_PROMPT_NAME = "kb_match"  # the entry in prompts.yaml
MIN_QUOTE = 8  # characters; shorter quotes prove nothing
SYMPTOMS_SHOWN = 500  # characters of an article's symptoms shown to the model


class KBMatch(BaseModel):
    article: str | None = Field(description="Id of the listed article that describes this case; null if none of them does")
    evidence: str | None = Field(description="Exact words from the case that match the article's symptoms; null if no article")
    reason: str = Field(description="One or two sentences for the team")


def kb_match_spec() -> CallSpec[KBMatch]:
    return _build_spec(config_version())


@lru_cache(maxsize=1)
def _build_spec(version: int) -> CallSpec[KBMatch]:
    """The call as configured now; rebuilt after an admin change to the prompt."""
    prompt = load_registry("prompts.yaml")[KB_MATCH_PROMPT_NAME]
    return CallSpec(
        name=KB_MATCH_PROMPT_NAME,
        prompt_version=prompt["version"],
        system=prompt["system"],
        output=KBMatch,
        wrapper=prompt["wrapper"],
        retry_note=prompt["retry_note"],
        max_tokens=prompt["max_tokens"],
    )


register_document("data_quality_prompts", "prompts.yaml", kb_match_spec)  # one prompts file for every call


def _normal(text: str) -> str:
    return " ".join(text.casefold().split())


def checked(answer: KBMatch, shown: list[str], case_text: str) -> tuple[str | None, str | None]:
    """The chosen article and why not, if the answer cannot be trusted. (id, None) is a match; (None, None) is 'no article'."""
    if answer.article is None:
        return None, None
    if answer.article not in shown:
        return None, f"The model named {answer.article}, which was not one of the articles shown"
    if not (answer.evidence and len(answer.evidence.strip()) >= MIN_QUOTE and _normal(answer.evidence) in _normal(case_text)):
        return None, "The model gave no exact words from the case as evidence"
    return answer.article, None


def assess_match(ticket: Ticket, notes: str, candidates: list[Article]) -> tuple[KBMatch, CallAudit]:
    """One model call on the masked case and the candidate articles. Raises app.llm.ModelError when there is no usable answer."""
    prompt = load_registry("prompts.yaml")[KB_MATCH_PROMPT_NAME]
    masker = Masker(known_names=[ticket.reporter_name, ticket.assignee], known_emails=[ticket.reporter_email])
    listed = "\n".join(
        f"- {a.kb_id} ({a.app}): {a.title}\n  Symptoms: {' '.join(a.symptoms.split())[:SYMPTOMS_SHOWN]}" for a in candidates
    )
    text = prompt["ticket_template"].format(
        application=ticket.application or prompt["not_given"], summary=ticket.summary, body=ticket.description,
        notes=notes or prompt["not_given"], candidates=listed,
    )
    return call_model(kb_match_spec(), masker.mask(text), masker)
