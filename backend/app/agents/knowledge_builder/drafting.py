"""Draft a knowledge-base article for a gap: a resolved case that no article covers.

The model first says what the case is: a known issue gets a draft; a request, or a problem outside the knowledge base
(a network or laptop problem), does not. It writes from the masked tickets only, in the knowledge base's own four parts.
The code then checks every draft: all parts present, no error code, ID, command or number that is not in the tickets,
and no personal data. A draft that fails is not shown. Unknown parts stay "[expert to add]", and an expert approves
every draft before it counts. The prompt text comes from data/registry/prompts.yaml.
"""

import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.closure_quality.model_check import invented
from app.agents.knowledge_builder.articles import articles
from app.core.config import config_version
from app.core.registry import load_registry, register_document
from app.llm import CallAudit, CallSpec, call_model
from app.models.ticket import Ticket
from app.privacy.masking import Masker

KB_DRAFT_PROMPT_NAME = "kb_draft"  # the entry in prompts.yaml
GAP = "[expert to add]"
GAP_MARK = re.compile(r"\[expert to add\b[^\]]*\]", re.I)  # also "[expert to add: the route]"
FIELDS = ("title", "symptoms", "root_cause", "resolution_steps", "escalation")


class KBDraftAnswer(BaseModel):
    kind: Literal["known_issue", "request", "outside_kb"] = Field(
        description="known_issue: a fault support fixed and could meet again; request: something new or a change; "
        "outside_kb: a network, VPN, device or other problem outside this application"
    )
    title: str | None = Field(description="Short, names the failure; null unless known_issue")
    symptoms: list[str] = Field(description="What users and engineers see, one per item; empty unless known_issue")
    root_cause: str | None = Field(description="Why it happened; null unless known_issue")
    resolution_steps: list[str] = Field(description="The steps an engineer follows, in order; empty unless known_issue")
    escalation: str | None = Field(description="Who to involve and when; null unless known_issue")
    reason: str = Field(description="One or two sentences for the expert who reviews the draft")


def kb_draft_spec() -> CallSpec[KBDraftAnswer]:
    return _build_spec(config_version())


@lru_cache(maxsize=1)
def _build_spec(version: int) -> CallSpec[KBDraftAnswer]:
    """The call as configured now; rebuilt after an admin change to the prompt."""
    prompt = load_registry("prompts.yaml")[KB_DRAFT_PROMPT_NAME]
    return CallSpec(
        name=KB_DRAFT_PROMPT_NAME,
        prompt_version=prompt["version"],
        system=prompt["system"],
        output=KBDraftAnswer,
        wrapper=prompt["wrapper"],
        retry_note=prompt["retry_note"],
        max_tokens=prompt["max_tokens"],
    )


register_document("data_quality_prompts", "prompts.yaml", kb_draft_spec)  # one prompts file for every call


def draft_article(cases: list[tuple[Ticket, str]], application: str) -> tuple[KBDraftAnswer, CallAudit, list[str]]:
    """One model call on the masked tickets, with the application's existing article titles for style and to avoid
    a duplicate. Also returns what was hidden from the model, which must not appear in the draft.
    Raises app.llm.ModelError when there is no usable answer."""
    prompt = load_registry("prompts.yaml")[KB_DRAFT_PROMPT_NAME]
    masker = Masker(
        known_names=[n for t, _ in cases for n in (t.reporter_name, t.assignee)],
        known_emails=[t.reporter_email for t, _ in cases],
    )
    tickets = "\n\n".join(
        prompt["case_template"].format(ticket_id=t.id, summary=t.summary, body=t.description, notes=notes) for t, notes in cases
    )
    titles = "\n".join(f"- {a.kb_id}: {a.title}" for a in articles().values() if a.app == application)
    text = prompt["ticket_template"].format(application=application, titles=titles or prompt["not_given"], cases=tickets)
    answer, audit = call_model(kb_draft_spec(), masker.mask(text), masker)
    return answer, audit, masker.masked_values


def people_of(tickets: list[Ticket]) -> list[str]:
    """The names and emails on the tickets: none of them may appear in an article."""
    return [v for t in tickets for v in (t.reporter_name, t.assignee, t.reporter_email) if v]


def fields_of(answer: KBDraftAnswer) -> dict:
    return {f: getattr(answer, f) for f in FIELDS}


def as_text(fields: dict) -> str:
    return "\n".join([fields["title"] or "", *fields["symptoms"], fields["root_cause"] or "", *fields["resolution_steps"],
                      fields["escalation"] or ""])


def _leaked(text: str, hidden: list[str]) -> bool:
    """Any hidden value, or any part of a hidden name, in the text."""
    words = {w for v in hidden for w in ([v] if "@" in v or any(c.isdigit() for c in v) else [v, *v.split()]) if len(w) >= 3}
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.I) for w in words)


def check_draft(fields: dict, source: str | None, hidden: list[str] = ()) -> list[str]:
    """What is wrong with a draft; empty means it may be shown. `source` is the tickets it was written from; an expert's
    own edit is passed with no source, because an expert may add knowledge the tickets do not have. `hidden` is what was
    masked from the model (or the names on the tickets): none of it may appear."""
    def given(value) -> bool:
        return bool(value) and (any(s.strip() for s in value) if isinstance(value, list) else bool(value.strip()))

    problems = [f"no {f.replace('_', ' ')}" for f in FIELDS if not given(fields.get(f))]
    text = as_text({f: fields.get(f) or ([] if f in ("symptoms", "resolution_steps") else "") for f in FIELDS})
    if source is not None and (made_up := invented(text, source)):
        problems.append(f"codes or numbers that are not in the tickets: {', '.join(made_up)}")
    masker = Masker()  # the pattern detectors (email, phone, IDs) are reliable; a name found by NER alone is not
    masker.mask(text)
    found = sorted(label for label, n in masker.counts.items() if n and label != "PERSON")
    if _leaked(text, list(hidden)):
        found.append("a name or contact from the tickets")
    if found:
        problems.append(f"personal data: {', '.join(found)}")
    return problems


def has_gaps(fields: dict) -> bool:
    """Any "[expert to add]" left, including ones with a hint: "[expert to add: the route]"."""
    return GAP_MARK.search(as_text(fields)) is not None


def markdown(kb_id: str | None, fields: dict, sources: list[str]) -> str:
    """The article in the knowledge base's own format; "DRAFT" until an id is given on approval."""
    lines = [f"### {kb_id or 'DRAFT'} — {fields['title']}", "", "**Symptoms**", *(f"- {s}" for s in fields["symptoms"]), "",
             "**Root cause**", fields["root_cause"], "", "**Resolution steps**",
             *(f"{i}. {s}" for i, s in enumerate(fields["resolution_steps"], 1)), "",
             f"**Escalation:** {fields['escalation']}", "", f"_Drafted from {', '.join(sources)}._", ""]
    return "\n".join(lines)
