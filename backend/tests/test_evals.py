"""Evaluation helpers for the RAGAS report: KB article parsing, sample building and the hit rate. No network, no ragas."""

import sys
from pathlib import Path

from app.agents.resolution.answer import ResolutionAnswer

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "evaluation"))

import ragas_report as report  # noqa: E402


def test_kb_articles_stops_at_the_next_issue_rule_or_section(tmp_path):
    (tmp_path / "app.md").write_text(
        "# App\n\n### KB-APP-001 — First issue\n\n**Root cause**\nCause one.\n\n---\n\n"
        "### KB-APP-002 — Second issue\n\nCause two.\n\n## Escalation contacts\n\n| L2 | Team |\n",
        encoding="utf-8",
    )
    articles = report.kb_articles(tmp_path)
    assert articles["KB-APP-001"] == "### KB-APP-001 — First issue\n\n**Root cause**\nCause one."
    assert articles["KB-APP-002"] == "### KB-APP-002 — Second issue\n\nCause two."


def test_kb_articles_reads_the_real_runbooks():
    articles = report.kb_articles(REPO / "data" / "knowledge_base")
    assert articles["KB-BIL-001"].startswith("### KB-BIL-001")
    assert "Escalation contacts" not in articles["KB-BIL-007"]
    assert all(text.startswith("### KB-") for text in articles.values())


def test_build_sample_uses_the_kb_articles_the_agent_was_shown():
    answer = ResolutionAnswer(verdict="resolved", root_cause="Cause", steps=["1. Restart", "2. Check"],
                              references=["KB-PAY-001"], confidence="high")
    trace = [{"turn": 0, "queries": ["q"], "kb_ids": ["KB-PAY-001", "KB-PAY-002"]},
             {"turn": 1, "queries": ["q2"], "kb_ids": ["KB-PAY-001", "KB-PAY-404"]},
             {"turn": 2, "rejected_references": ["KB-PAY-999"]}]
    articles = {"KB-PAY-001": "Article one", "KB-PAY-002": "Article two", "KB-PAY-003": "Not shown"}

    sample = report.build_sample("INC1", "ticket text", answer, trace, "KB-PAY-001", articles)

    assert sample["retrieved_contexts"] == ["Article one", "Article two"]  # shown once each, unknown ids dropped
    assert sample["response"] == "Cause\n1. Restart\n2. Check"
    assert sample["reference"] == "Article one"
    assert sample["kb_hit"] is True
    assert sample["scores"] is None


def test_build_sample_for_no_match_uses_the_note_as_the_response():
    answer = ResolutionAnswer(verdict="no_match", confidence="low", notes="Escalate to AMS-Payroll.")
    sample = report.build_sample("INC2", "ticket text", answer, [{"turn": 0, "kb_ids": []}], "KB-PAY-002",
                                 {"KB-PAY-002": "Article"})
    assert sample["response"] == "Escalate to AMS-Payroll."
    assert sample["retrieved_contexts"] == []
    assert sample["kb_hit"] is False


def test_kb_hit_and_hit_rate():
    assert report.kb_hit(["KB-A-001", "KB-A-002"], "KB-A-002")
    assert not report.kb_hit([], "KB-A-002")
    samples = [{"kb_hit": True}, {"kb_hit": False}, {"kb_hit": True}, {"kb_hit": True}]
    assert report.hit_rate(samples) == 0.75
    assert report.hit_rate([]) == 0.0


def test_summarise_skips_samples_without_a_score():
    samples = [
        {"kb_hit": True, "scores": {"faithfulness": 1.0, "context_precision": 0.5, "context_recall": None}},
        {"kb_hit": False, "scores": None},
        {"kb_hit": True, "scores": {"faithfulness": 0.5, "context_precision": 1.0, "context_recall": 1.0}},
    ]
    summary = report.summarise(samples)
    assert summary["faithfulness"] == (0.75, 2)
    assert summary["context_precision"] == (0.75, 2)
    assert summary["context_recall"] == (1.0, 1)
    assert summary["kb_hit"] == (2 / 3, 3)
