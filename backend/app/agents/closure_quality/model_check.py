"""Model stage of the Closure Quality agent: how specific are the cause, the action and the check in the close notes?

The model never decides pass or fail. For each part it reports a level and the exact words that show it; the code
checks every quote against the notes, adds up the score and applies the pass rule from closure_rules.yaml.
A level without a real quote counts as none. The draft it may write is checked for invented codes and numbers.
The answer schema is code, because the eval measures it; the prompt text comes from data/registry/prompts.yaml.
"""

import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.closure_quality.config import PARTS, ClosureConfig
from app.agents.resolution.chunking import chunk_knowledge_base
from app.core.config import config_version, settings
from app.core.registry import load_registry, register_document
from app.llm import CallAudit, CallSpec, call_model
from app.models.ticket import Ticket
from app.privacy.masking import Masker

CLOSURE_PROMPT_NAME = "closure_score"  # the entry in prompts.yaml
LEVELS = {"none": 0, "vague": 1, "specific": 2}
MIN_QUOTE = 8  # characters; shorter quotes ("fixed") prove nothing
GAP = re.compile(r"\[engineer to add: (?:cause|action|check)\]")
KB_ID = re.compile(r"\bKB-[A-Z]+-\d+\b")

Level = Literal["none", "vague", "specific"]


class ClosureFacts(BaseModel):
    cause_level: Level = Field(description="How specific the notes are about what was wrong")
    cause_quote: str | None = Field(description="Exact words from the resolution notes; null when none")
    action_level: Level = Field(description="How specific the notes are about what was done to fix it")
    action_quote: str | None = Field(description="Exact words from the resolution notes; null when none")
    check_level: Level = Field(description="How specific the notes are about how it was confirmed fixed")
    check_quote: str | None = Field(description="Exact words from the resolution notes; null when none")
    draft_notes: str | None = Field(
        description="Better notes using only facts already in the ticket, gaps marked [engineer to add: cause|action|check]. "
        "Null when cause, action and check are all specific"
    )
    reason: str = Field(description="One or two sentences for the engineer")


def closure_spec() -> CallSpec[ClosureFacts]:
    return _build_spec(config_version())


@lru_cache(maxsize=1)
def _build_spec(version: int) -> CallSpec[ClosureFacts]:
    """The call as configured now; rebuilt after an admin change to the prompt."""
    prompt = load_registry("prompts.yaml")[CLOSURE_PROMPT_NAME]
    return CallSpec(
        name=CLOSURE_PROMPT_NAME,
        prompt_version=prompt["version"],
        system=prompt["system"],
        output=ClosureFacts,
        wrapper=prompt["wrapper"],
        retry_note=prompt["retry_note"],
        max_tokens=prompt["max_tokens"],
    )


register_document("data_quality_prompts", "prompts.yaml", closure_spec)  # one prompts file for every call


def _normal(text: str) -> str:
    return " ".join(text.casefold().split())


def verified(facts: ClosureFacts, notes: str) -> tuple[dict[str, int], dict[str, str | None], list[str]]:
    """Levels as numbers, with any level that has no real quote from the notes dropped to none."""
    levels, quotes, dropped = {}, {}, []
    for part in PARTS:
        level, quote = LEVELS[getattr(facts, f"{part}_level")], getattr(facts, f"{part}_quote")
        if level and not (quote and len(quote.strip()) >= MIN_QUOTE and _normal(quote) in _normal(notes)):
            level, quote = 0, None
            dropped.append(part)
        levels[part], quotes[part] = level, quote
    return levels, quotes, dropped


@lru_cache(maxsize=1)
def kb_ids() -> frozenset[str]:
    """Ids of the knowledge-base articles that exist, read with Resolution's chunker."""
    return frozenset(c.kb_id for chunks in chunk_knowledge_base(settings.KB_DIR).values() for c in chunks if c.kb_id)


def cited_articles(notes: str) -> list[str]:
    """Existing knowledge-base articles the notes cite. An id that does not exist counts for nothing."""
    return sorted(set(KB_ID.findall(notes)) & kb_ids())


def score(levels: dict[str, int], config: ClosureConfig) -> tuple[int, bool]:
    """The total out of 6, and whether the notes pass the rule from closure_rules.yaml."""
    total = sum(levels.values())
    return total, levels["action"] >= config.min_action and total >= config.min_total


def technical_tokens(text: str) -> set[str]:
    """Words that look like codes, IDs, commands or numbers: they contain a digit or underscore, or capitals in a row."""
    words = (w.strip(".,;:()[]\"'") for w in GAP.sub(" ", text).split())
    return {w for w in words if w and (any(c.isdigit() or c == "_" for c in w) or re.search(r"[A-Z]{2,}", w))}


def invented(draft: str, source: str) -> list[str]:
    """Codes, IDs and numbers in the draft that appear nowhere in the ticket it was built from."""
    return sorted(t for t in technical_tokens(draft) if t.casefold() not in source.casefold())


def assess_notes(ticket: Ticket, replies: str, notes: str) -> tuple[ClosureFacts, CallAudit]:
    """One model call on the masked ticket. Raises app.llm.ModelError when there is no usable answer."""
    prompt = load_registry("prompts.yaml")[CLOSURE_PROMPT_NAME]
    masker = Masker(
        known_names=[ticket.reporter_name, ticket.assignee], known_emails=[ticket.reporter_email]
    )
    text = prompt["ticket_template"].format(
        summary=ticket.summary, body=ticket.description,
        replies=replies or prompt["not_given"], notes=notes or prompt["not_given"],
    )
    return call_model(closure_spec(), masker.mask(text), masker)
