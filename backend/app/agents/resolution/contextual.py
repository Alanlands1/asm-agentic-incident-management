"""Resolution agent, step 2: Contextual Retrieval. A short blurb per chunk says where the chunk sits in its runbook.

The blurb is stored in `context` and searched together with the chunk. The whole runbook goes in the system prompt, so
the provider caches it across that runbook's chunks. Ingest only: no ticket text is ever sent here.
"""

import logging

from pydantic import BaseModel, Field

from app.agents.resolution.chunking import Chunk
from app.core.config import settings
from app.core.registry import load_registry
from app.llm import CallSpec, ModelError, call_model
from app.privacy.masking import Masker

logger = logging.getLogger("app.resolution")

PROMPT_NAME = "kb_chunk_context"  # the entry in data/registry/prompts.yaml


class ChunkContext(BaseModel):
    context: str = Field(description="One or two sentences placing the chunk in its runbook")


def _spec(document: str) -> CallSpec[ChunkContext]:
    prompt = load_registry("prompts.yaml")[PROMPT_NAME]
    return CallSpec(
        name=PROMPT_NAME,
        prompt_version=prompt["version"],
        system=prompt["system"].format(document=document),
        output=ChunkContext,
        wrapper=prompt["wrapper"],
        retry_note=prompt["retry_note"],
        max_tokens=prompt["max_tokens"],
        model=settings.KB_CONTEXT_MODEL,
    )


def fallback_context(chunk: Chunk) -> str:
    """Used when the model is off or fails: the application and the heading path, which is still a useful search key."""
    return f"{chunk.app} runbook. {chunk.heading_path}."


def contextualize(document: str, chunks: list[Chunk]) -> list[str]:
    """One context per chunk, in order. Blocking (model calls): run it in a thread from async code."""
    contexts: list[str] = []
    for chunk in chunks:
        masker = Masker()
        try:
            answer, _ = call_model(_spec(document), masker.mask(chunk.content), masker)
            contexts.append(answer.context)
        except ModelError as exc:
            logger.warning(f"kb context fallback for {chunk.source_path}#{chunk.chunk_index}: {exc}")
            contexts.append(fallback_context(chunk))
    return contexts
