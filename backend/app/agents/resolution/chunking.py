"""Resolution agent, step 1: split the knowledge base runbooks into chunks.

Structure decides the boundaries: one `### KB-...` block is one chunk. A block longer than KB_CHUNK_SIZE is split with
overlap. Text in, chunks out: no model and no database.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.core.config import settings

KB_ID = re.compile(r"KB-[A-Z]+-\d{3}")
TIER = re.compile(r"Tier\s*\d")
TABLE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$")
HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]


@dataclass(frozen=True)
class Chunk:
    source_path: str  # file name under the knowledge base directory, e.g. payrollpro.md
    chunk_index: int  # position in the file, after any size split
    app: str  # application name from the H1 title, e.g. PayrollPro
    app_id: str | None  # from the front table, e.g. APP-PAY
    kb_id: str | None  # from the H3 heading, e.g. KB-PAY-001
    section_type: str  # header | overview | issue | escalation
    title: str  # the most specific heading of the chunk
    heading_path: str  # "PayrollPro > Known issues and resolutions > KB-PAY-001 — ..."
    support_group: str | None
    criticality_tier: str | None  # e.g. "Tier 1"
    content: str  # the chunk as written in the runbook

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def front_matter(text: str) -> dict[str, str]:
    """The Field | Value table between the H1 title and the first H2, with markdown bold removed."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            break
        match = TABLE_ROW.match(line)
        if match and not match.group(1).startswith(("-", "Field")):
            fields[match.group(1)] = match.group(2).replace("**", "")
    return fields


def chunk_document(path: Path) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    h1 = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
    app = h1.split(" — ")[0].strip()
    meta = front_matter(text)
    tier = TIER.search(meta.get("Criticality tier", ""))

    sections = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS, strip_headers=False).split_text(text)
    pieces = RecursiveCharacterTextSplitter(
        chunk_size=settings.KB_CHUNK_SIZE, chunk_overlap=settings.KB_CHUNK_OVERLAP
    ).split_documents(sections)

    chunks: list[Chunk] = []
    for piece in pieces:
        body = piece.page_content.strip()
        if not body:
            continue
        headings = piece.metadata
        kb = KB_ID.search(headings.get("h3") or "")
        h2 = headings.get("h2") or ""
        if kb:
            section_type = "issue"
        elif h2.startswith("Escalation"):
            section_type = "escalation"
        elif h2:
            section_type = "overview"
        else:
            section_type = "header"
        path_parts = [app] + [h for h in (headings.get("h2"), headings.get("h3")) if h]
        chunks.append(
            Chunk(
                source_path=path.name,
                chunk_index=len(chunks),
                app=app,
                app_id=meta.get("Application ID"),
                kb_id=kb.group(0) if kb else None,
                section_type=section_type,
                title=headings.get("h3") or headings.get("h2") or h1,
                heading_path=" > ".join(path_parts),
                support_group=meta.get("Support group"),
                criticality_tier=tier.group(0) if tier else None,
                content=body,
            )
        )
    return chunks


def chunk_knowledge_base(directory: Path) -> dict[str, list[Chunk]]:
    """Chunks for every runbook in the directory, keyed by file name."""
    return {path.name: chunk_document(path) for path in sorted(directory.glob("*.md"))}
