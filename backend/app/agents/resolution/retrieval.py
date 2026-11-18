"""Resolution agent: search the knowledge base. Metadata filters first, then dense and full-text search, fused with RRF.

Filters are a hard boundary (the Phase 3 pre-filter in the architecture doc): a chunk outside them is never scored.
"""

from dataclasses import dataclass, replace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RRF_K = 60  # the usual Reciprocal Rank Fusion constant
COLUMNS = "id, app, kb_id, title, heading_path, content, context"
FILTER_COLUMNS = ("app", "kb_id", "criticality_tier", "section_type")


@dataclass(frozen=True)
class Filters:
    app: str | None = None
    kb_id: str | None = None
    criticality_tier: str | None = None
    section_type: str | None = None

    def sql(self) -> tuple[str, dict[str, str]]:
        """' AND ...' clauses for the fields that are set, with bound parameters. Empty when no field is set."""
        clauses: list[str] = []
        params: dict[str, str] = {}
        for field in FILTER_COLUMNS:
            value = getattr(self, field)
            if value is not None:
                clauses.append(f" AND {field} = :f_{field}")
                params[f"f_{field}"] = value
        return "".join(clauses), params


@dataclass(frozen=True)
class RetrievedChunk:
    id: int
    app: str
    kb_id: str | None
    title: str
    heading_path: str
    content: str
    context: str
    score: float


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion. Each ranking adds 1/(k + rank) to an id; ids ranked well in several lists rise to the top."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def fuse_chunks(lists: list[list[RetrievedChunk]], top_n: int) -> list[RetrievedChunk]:
    """RRF across several result lists, e.g. one per query variant. Each chunk keeps its metadata; score is the fused one."""
    by_id: dict[int, RetrievedChunk] = {}
    for chunks in lists:
        for chunk in chunks:
            by_id.setdefault(chunk.id, chunk)
    fused = rrf([[chunk.id for chunk in chunks] for chunks in lists])
    return [replace(by_id[chunk_id], score=score) for chunk_id, score in fused[:top_n]]


async def search_all(
    db: AsyncSession,
    queries: list[str],
    vectors: list[list[float] | None],
    filters: Filters | None = None,
    top_n: int = 20,
    weights: dict[str, float] | None = None,
) -> list[RetrievedChunk]:
    """Every query through retrieve(), fused. vectors[i] is the embedding of queries[i], or None for full-text only.
    weights (KB id -> factor, from engineers' ratings) then move a runbook's chunks up or down."""
    results = [await retrieve(db, q, v, filters, top_n) for q, v in zip(queries, vectors, strict=True)]
    return reweigh(fuse_chunks(results, top_n), weights or {})


def reweigh(chunks: list[RetrievedChunk], weights: dict[str, float]) -> list[RetrievedChunk]:
    """Each chunk's score times its runbook's weight (1.0 when it has none), best first again."""
    if not weights:
        return chunks
    return sorted((replace(c, score=c.score * weights.get(c.kb_id, 1.0)) for c in chunks), key=lambda c: c.score, reverse=True)


def _dense_sql(where: str) -> str:
    return (
        f"SELECT {COLUMNS} FROM kb_chunks WHERE embedding IS NOT NULL{where} "
        "ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :n"
    )


def _sparse_sql(where: str) -> str:
    return (
        "WITH q AS (SELECT websearch_to_tsquery('english', :q) AS query) "
        f"SELECT {COLUMNS} FROM kb_chunks, q WHERE kb_chunks.fts @@ q.query{where} "
        "ORDER BY ts_rank_cd(kb_chunks.fts, q.query) DESC LIMIT :n"
    )


async def retrieve(
    db: AsyncSession,
    query_text: str,
    query_vec: list[float] | None = None,
    filters: Filters | None = None,
    top_n: int = 20,
) -> list[RetrievedChunk]:
    """Top chunks for a query. Without a query vector only the full-text search runs."""
    where, params = (filters or Filters()).sql()
    rankings: list[list[int]] = []
    rows: dict[int, dict] = {}

    if query_vec is not None:
        vector = "[" + ",".join(str(x) for x in query_vec) + "]"
        found = (await db.execute(text(_dense_sql(where)), {**params, "vec": vector, "n": top_n})).mappings().all()
        rankings.append([row["id"] for row in found])
        rows.update({row["id"]: dict(row) for row in found})

    found = (await db.execute(text(_sparse_sql(where)), {**params, "q": query_text, "n": top_n})).mappings().all()
    rankings.append([row["id"] for row in found])
    rows.update({row["id"]: dict(row) for row in found})

    return [_chunk(rows[chunk_id], score) for chunk_id, score in rrf(rankings)[:top_n]]


def _chunk(row: dict, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        id=row["id"],
        app=row["app"],
        kb_id=row["kb_id"],
        title=row["title"],
        heading_path=row["heading_path"],
        content=row["content"],
        context=row["context"],
        score=score,
    )
