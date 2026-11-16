"""Runbooks of the knowledge base (data/knowledge_base/*.md), one section per id: GET /runbooks/{kb_id}."""

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import REPO_DIR

router = APIRouter(prefix="/runbooks", tags=["runbooks"])

KB_DIR = REPO_DIR / "data" / "knowledge_base"


class RunbookOut(BaseModel):
    id: str
    title: str
    application: str | None  # from the file's first heading
    markdown: str  # the section under the runbook's heading


@router.get("/{kb_id}", response_model=RunbookOut, summary="One runbook, as it is written in the knowledge base")
def runbook(kb_id: str) -> RunbookOut:
    heading = re.compile(rf"^### {re.escape(kb_id)} — (.+)$", re.M)
    for path in sorted(KB_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if found := heading.search(text):
            section = re.split(r"^(?:---|#{1,3} .*)$", text[found.end():], maxsplit=1, flags=re.M)[0]
            application = re.match(r"# (.+?) — ", text)
            return RunbookOut(id=kb_id, title=found[1].strip(), application=application[1] if application else None,
                              markdown=section.strip())
    raise HTTPException(status_code=404, detail=f"No runbook {kb_id} in the knowledge base")
