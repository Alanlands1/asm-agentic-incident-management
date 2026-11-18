"""Resolution agent knowledge base: chunking, contextual text, fusion and filters. No database and no model."""

import re
from pathlib import Path

import pytest

from app.agents.resolution import contextual
from app.agents.resolution.chunking import Chunk, chunk_document, chunk_knowledge_base, front_matter
from app.agents.resolution.embedding import indexed_text
from app.agents.resolution.retrieval import Filters, _dense_sql, _sparse_sql, rrf
from app.core.config import settings
from app.llm import CallAudit

KB_DIR = settings.KB_DIR


def _kb_ids_in(path: Path) -> list[str]:
    return sorted(set(re.findall(r"^### (KB-[A-Z]+-\d{3})", path.read_text(encoding="utf-8"), re.MULTILINE)))


def test_every_issue_in_every_runbook_becomes_exactly_one_chunk_with_its_id():
    chunks = chunk_knowledge_base(KB_DIR)
    assert len(chunks) == 7
    for source, items in chunks.items():
        issue_ids = [c.kb_id for c in items if c.kb_id]
        assert sorted(issue_ids) == _kb_ids_in(KB_DIR / source), source
        assert len(issue_ids) == len(set(issue_ids)), source


def test_metadata_comes_from_the_runbook_header():
    payroll = chunk_knowledge_base(KB_DIR)["payrollpro.md"]
    assert {c.app for c in payroll} == {"PayrollPro"}
    assert {c.app_id for c in payroll} == {"APP-PAY"}
    assert {c.support_group for c in payroll} == {"AMS-HR-Apps"}
    assert payroll[0].section_type == "header"
    assert any(c.section_type == "overview" for c in payroll)
    assert any(c.section_type == "escalation" for c in payroll)
    billing = chunk_knowledge_base(KB_DIR)["billingengine.md"]
    assert {c.criticality_tier for c in billing} == {"Tier 1"}


def test_chunk_indexes_are_sequential_per_file():
    for items in chunk_knowledge_base(KB_DIR).values():
        assert [c.chunk_index for c in items] == list(range(len(items)))


def test_front_matter_strips_bold_and_stops_at_first_section():
    text = "# App — KB\n\n| Field | Value |\n|---|---|\n| Criticality tier | **Tier 2** (x) |\n\n## Sec\n| A | B |\n"
    assert front_matter(text) == {"Criticality tier": "Tier 2 (x)"}


def test_long_issue_block_is_split_with_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KB_CHUNK_SIZE", 300)
    monkeypatch.setattr(settings, "KB_CHUNK_OVERLAP", 40)
    paragraphs = "\n\n".join(f"Step {i}: check queue depth number {i} and record the result." for i in range(40))
    doc = tmp_path / "demo.md"
    doc.write_text(
        f"# DemoApp — Application Support Knowledge Base\n\n## Known issues and resolutions\n\n"
        f"### KB-DEM-001 — Long issue\n\n**Resolution steps**\n\n{paragraphs}\n",
        encoding="utf-8",
    )
    chunks = chunk_document(doc)
    assert len(chunks) > 1
    assert {c.kb_id for c in chunks} == {"KB-DEM-001"}
    assert all(len(c.content) <= 300 for c in chunks)
    joined = "\n".join(c.content for c in chunks)
    for step in range(40):  # nothing is lost at the split points
        assert f"Step {step}:" in joined


def test_content_hash_changes_with_text_only():
    base = dict(source_path="a.md", chunk_index=0, app="A", app_id=None, kb_id=None, section_type="header",
                title="t", heading_path="A", support_group=None, criticality_tier=None)
    assert Chunk(content="x", **base).content_hash == Chunk(content="x", **base).content_hash
    assert Chunk(content="x", **base).content_hash != Chunk(content="y", **base).content_hash


def test_fallback_context_uses_app_and_heading_path():
    chunk = chunk_knowledge_base(KB_DIR)["payrollpro.md"][1]
    assert contextual.fallback_context(chunk).startswith("PayrollPro runbook.")


def test_contextualize_falls_back_when_model_is_off():
    # conftest switches the model off: every chunk gets the deterministic context
    chunks = chunk_knowledge_base(KB_DIR)["orderhub.md"]
    document = (KB_DIR / "orderhub.md").read_text(encoding="utf-8")
    contexts = contextualize_or_skip(document, chunks)
    assert contexts == [contextual.fallback_context(c) for c in chunks]


def contextualize_or_skip(document, chunks):
    return contextual.contextualize(document, chunks)


def test_model_call_uses_haiku_and_puts_the_runbook_in_the_system_prompt(monkeypatch):
    seen = {}

    def fake_call(spec, user, masker):
        seen["spec"] = spec
        seen["user"] = user
        return contextual.ChunkContext(context="PayrollPro, KB-PAY-001 payslip renderer."), CallAudit(
            provider="anthropic", model="x", prompt_version=spec.prompt_version, attempts=1, input_tokens=0,
            output_tokens=0, latency_ms=0,
        )

    monkeypatch.setattr(contextual, "call_model", fake_call)
    chunk = chunk_knowledge_base(KB_DIR)["payrollpro.md"][1]
    assert contextual.contextualize("RUNBOOK TEXT", [chunk]) == ["PayrollPro, KB-PAY-001 payslip renderer."]
    spec = seen["spec"]
    assert spec.model == settings.KB_CONTEXT_MODEL
    assert spec.prompt_version == "kb_chunk_context@1"
    assert "RUNBOOK TEXT" in spec.system
    assert "{document}" not in spec.system
    assert "<chunk>" in spec.wrapper


def test_indexed_text_puts_context_before_content():
    assert indexed_text("ctx", "body") == "ctx\n\nbody"
    assert indexed_text("", "body") == "body"


def test_rrf_rewards_ids_ranked_well_in_several_lists():
    fused = rrf([[1, 2, 3], [3, 1, 4]])
    assert [chunk_id for chunk_id, _ in fused][:2] == [1, 3]
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)


def test_filters_only_add_clauses_for_fields_that_are_set():
    assert Filters().sql() == ("", {})
    where, params = Filters(app="PayrollPro", section_type="issue").sql()
    assert where == " AND app = :f_app AND section_type = :f_section_type"
    assert params == {"f_app": "PayrollPro", "f_section_type": "issue"}
    assert "AND app = :f_app" in _dense_sql(where)
    assert "kb_chunks.fts @@ q.query AND app = :f_app" in _sparse_sql(where)


class _FakeVector:
    def __init__(self, size):
        self._values = [0.5] * size

    def tolist(self):
        return list(self._values)


class _FakeModel:
    def __init__(self, size):
        self.size = size
        self.calls = []

    def encode_document(self, texts, normalize_embeddings):
        self.calls.append(("document", list(texts), normalize_embeddings))
        return [_FakeVector(self.size) for _ in texts]

    def encode_query(self, text, normalize_embeddings):
        self.calls.append(("query", text, normalize_embeddings))
        return _FakeVector(self.size)


def test_sentence_embedder_uses_document_and_query_prompts_and_checks_size(monkeypatch):
    from app.agents.resolution.embedding import SentenceEmbedder

    monkeypatch.setattr(settings, "EMBEDDING_DIM", 256)
    model = _FakeModel(256)
    embedder = SentenceEmbedder(model)
    assert embedder.model_name == settings.EMBEDDING_MODEL
    assert len(embedder.embed_documents(["a", "b"])) == 2
    assert len(embedder.embed_query("PDF-GEN-500")) == 256
    assert model.calls[0] == ("document", ["a", "b"], True)
    assert model.calls[1] == ("query", "PDF-GEN-500", True)


def test_sentence_embedder_rejects_wrong_size(monkeypatch):
    from app.agents.resolution.embedding import SentenceEmbedder

    monkeypatch.setattr(settings, "EMBEDDING_DIM", 256)
    with pytest.raises(ValueError, match="EMBEDDING_DIM"):
        SentenceEmbedder(_FakeModel(128)).embed_documents(["a"])
