"""Resolution agent: load the runbooks into kb_chunks. Safe to re-run: chunks whose text has not changed are skipped.

Run from backend/:  ../.venv/bin/python -m app.agents.resolution.ingest [--embed]
--embed also fills NULL embeddings with the local model (see embedding.py).
"""

import asyncio
import logging
from datetime import UTC
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.agents.resolution.chunking import Chunk, chunk_knowledge_base
from app.agents.resolution.contextual import contextualize
from app.agents.resolution.embedding import Embedder, indexed_text
from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models.kb import KBChunk, utcnow

logger = logging.getLogger("app.resolution")
EMBED_BATCH = 64


def _row(chunk: Chunk, context: str) -> dict:
    return {
        "source_path": chunk.source_path,
        "chunk_index": chunk.chunk_index,
        "app": chunk.app,
        "app_id": chunk.app_id,
        "kb_id": chunk.kb_id,
        "section_type": chunk.section_type,
        "title": chunk.title,
        "heading_path": chunk.heading_path,
        "support_group": chunk.support_group,
        "criticality_tier": chunk.criticality_tier,
        "authority": "primary",
        "content": chunk.content,
        "context": context,
        "content_hash": chunk.content_hash,
        "embedding": None,  # new text means a new embedding is needed
        "embedding_model": None,
    }


async def ingest_kb(directory: Path | None = None) -> dict[str, int]:
    directory = directory or settings.KB_DIR  # another folder of runbooks, e.g. the pages copied from Confluence
    docs = chunk_knowledge_base(directory)

    async with AsyncSessionLocal() as db:
        stored = {
            (source, index): digest
            for source, index, digest in (
                await db.execute(select(KBChunk.source_path, KBChunk.chunk_index, KBChunk.content_hash))
            ).all()
        }

    # Model calls run with no database session open. They block, so they run in a thread.
    writes: list[dict] = []
    keep: dict[str, list[int]] = {}
    unchanged = 0
    for source, chunks in docs.items():
        keep[source] = [c.chunk_index for c in chunks]
        changed = [c for c in chunks if stored.get((source, c.chunk_index)) != c.content_hash]
        unchanged += len(chunks) - len(changed)
        if changed:
            document = (directory / source).read_text(encoding="utf-8")
            contexts = await asyncio.to_thread(contextualize, document, changed)
            writes.extend(_row(chunk, ctx) for chunk, ctx in zip(changed, contexts, strict=True))

    async with AsyncSessionLocal() as db:
        removed = (
            await db.execute(delete(KBChunk).where(KBChunk.source_path.not_in(list(docs))))
        ).rowcount
        for source, indexes in keep.items():
            result = await db.execute(
                delete(KBChunk).where(KBChunk.source_path == source, KBChunk.chunk_index.not_in(indexes))
            )
            removed += result.rowcount
        if writes:
            stmt = insert(KBChunk)
            columns = [c for c in writes[0] if c not in ("source_path", "chunk_index")]
            stmt = stmt.on_conflict_do_update(
                index_elements=["source_path", "chunk_index"],
                set_={**{c: stmt.excluded[c] for c in columns}, "updated_at": stmt.excluded.updated_at},
            )
            await db.execute(stmt, [{**w, "updated_at": utcnow()} for w in writes])
        await db.commit()

    return {"written": len(writes), "unchanged": unchanged, "removed": removed}


async def embed_pending(embedder: Embedder) -> int:
    """Embed every chunk whose embedding is NULL. Returns how many rows were filled."""
    total = 0
    while True:
        async with AsyncSessionLocal() as db:
            batch = (
                await db.execute(
                    select(KBChunk.id, KBChunk.context, KBChunk.content)
                    .where(KBChunk.embedding.is_(None))
                    .order_by(KBChunk.id)
                    .limit(EMBED_BATCH)
                )
            ).all()
        if not batch:
            return total

        vectors = await asyncio.to_thread(
            embedder.embed_documents, [indexed_text(context, content) for _, context, content in batch]
        )
        if len(vectors) != len(batch):
            raise ValueError(f"embedder returned {len(vectors)} vectors for {len(batch)} chunks")

        async with AsyncSessionLocal() as db:
            for (chunk_id, _, _), vector in zip(batch, vectors, strict=True):
                await db.execute(
                    update(KBChunk)
                    .where(KBChunk.id == chunk_id)
                    .values(embedding=vector, embedding_model=embedder.model_name)
                )
            await db.commit()
        total += len(batch)


def _now():
    from datetime import datetime

    return datetime.now(UTC)


async def _main(embed: bool) -> None:
    logging.basicConfig(level=settings.LOG_LEVEL)
    try:
        stats = await ingest_kb()
        print(f"kb ingest: written={stats['written']} unchanged={stats['unchanged']} removed={stats['removed']}")
        if embed:
            from app.agents.resolution.embedding import SentenceEmbedder

            print(f"kb embed: filled={await embed_pending(SentenceEmbedder())}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embed", action="store_true", help="also embed chunks that have no embedding yet")
    asyncio.run(_main(parser.parse_args().embed))
