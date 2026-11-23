"""The knowledge-base articles, read with Resolution's chunker so there is one reader of the runbooks."""

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

from app.agents.resolution.chunking import chunk_knowledge_base
from app.core.config import settings

HEADING = re.compile(r"^###\s*(KB-[A-Z]+-\d+)\s*\S\s*(.+?)\s*$", re.M)  # "### KB-PAY-001 — Title"
SYMPTOMS = re.compile(r"\*\*Symptoms\*\*\s*(.*?)(?=\n\*\*|\Z)", re.S)
# Error codes, job names and similar: ORA-01555, SYNC-ERR-12, PAY_CALC_MONTHLY, AADSTS50011. Not KB ids.
CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+\b|\b[A-Z]{3,}\d{4,}\b")


TICKET_REF = re.compile(r"INC\d+$|(?:AMS|MBX)-\d+$")  # our sources' ticket references, not error codes


@dataclass(frozen=True)
class Article:
    kb_id: str
    app: str
    title: str
    symptoms: str
    content: str  # the article as written: symptoms, root cause, resolution steps, escalation

    @property
    def codes(self) -> frozenset[str]:
        return codes(self.content)


def codes(text: str) -> frozenset[str]:
    """Error codes and job names in the text, without knowledge-base ids and ticket references."""
    return frozenset(c for c in CODE.findall(text) if not c.startswith("KB-") and not TICKET_REF.match(c))


@lru_cache(maxsize=1)
def articles() -> dict[str, Article]:
    """Every article by id."""
    found = {}
    for chunks in chunk_knowledge_base(settings.KB_DIR).values():
        for chunk in chunks:
            if chunk.kb_id and (heading := HEADING.search(chunk.content)):
                symptoms = SYMPTOMS.search(chunk.content)
                text = symptoms.group(1).strip() if symptoms else ""
                found[chunk.kb_id] = Article(chunk.kb_id, chunk.app, heading.group(2), text, chunk.content)
    return found


def articles_version() -> str:
    """Changes when an article is added, removed or edited, so cases are matched again."""
    return hashlib.sha256("|".join(f"{a.kb_id}:{a.content}" for a in articles().values()).encode()).hexdigest()[:12]
