"""Close notes that follow the Resolution agent's fix, and the ask on Jira when notes need work."""

from app.agents.closure_quality.model_check import ClosureFacts
from app.llm.client import CallAudit
from app.models.ticket import AgentRun, Ticket
from app.services import jira
from app.services.closure import run
from app.services.closure.run import notes_for

FIX = AgentRun(agent="resolution", verdict="resolved",
               output={"root_cause": "Webhook retries ran out", "steps": ["Replay the webhooks"], "references": ["KB-ORD-001"]})


def _ticket(notes: str, runs: list[AgentRun]) -> Ticket:
    return Ticket(id="AMS-4", resolution_notes=notes, agent_runs=runs)


def test_notes_that_follow_the_suggested_fix_take_its_cause_and_steps():
    notes, adopted = notes_for(_ticket("Followed the suggested fix; 14 orders moved to PAID.", [FIX]))
    assert adopted
    assert notes.startswith("Followed the suggested fix; 14 orders moved to PAID.")  # the engineer's own words first
    assert "Cause: Webhook retries ran out" in notes and "Step 1: Replay the webhooks" in notes and "KB-ORD-001" in notes


def test_other_notes_are_judged_as_written():
    assert notes_for(_ticket("Restarted the pod; orders flow again.", [FIX])) == ("Restarted the pod; orders flow again.", False)
    no_fix = AgentRun(agent="resolution", verdict="no_match", output={})
    assert notes_for(_ticket("Followed the suggested fix.", [no_fix])) == ("Followed the suggested fix.", False)


def test_the_ask_on_jira_lists_what_is_missing_and_the_draft():
    check = AgentRun(agent="closure_quality", verdict="needs_work",
                     output={"questions": ["How did you confirm it is fixed?"],
                             "draft_notes": "Cause: X. [engineer to add: check]"})
    text = jira._closure_text(_ticket("fixed", [check]))
    assert text.splitlines() == [
        "AMS agents · Close notes need work",
        "- How did you confirm it is fixed?",
        "Suggested close notes, from what is already on this issue (fill in anything in brackets):",
        "Cause: X. [engineer to add: check]",
        "Next: reply here with the completed close notes; the agents check them again.",
    ]
    assert text.startswith(jira.SYSTEM)  # skipped as close notes on the next sync, and removed by the demo reset


def test_followed_fix_without_a_check_needs_work_and_asks_only_for_the_check(monkeypatch):

    facts = ClosureFacts.model_construct(
        reason="Only says the procedure was followed.", cause_level="none", cause_quote=None, action_level="vague",
        action_quote="followed the exact procedure", check_level="specific", check_quote="Confirm the orders move to PAID",
        draft_notes="Cause: webhook. [engineer to add: cause]\nCheck: [engineer to add: check]")
    monkeypatch.setattr(run.settings, "LLM_ENABLED", True)
    audit = CallAudit(provider="test", model="test", prompt_version="test", attempts=1, input_tokens=0, output_tokens=0,
                      latency_ms=0)
    monkeypatch.setattr(run, "assess_notes", lambda *a: (facts, audit))
    fix = AgentRun(agent="resolution", verdict="resolved",
                   output={"root_cause": "Webhook retries ran out",
                           "steps": ["Replay the webhooks", "Confirm the orders move to PAID"]})
    ticket = Ticket(id="AMS-4", summary="Orders stuck", description="Orders stuck in PENDING_PAYMENT since 10:00",
                    resolution_notes="Fix completed, followed the exact procedure given by the agent.",
                    agent_runs=[fix], comments=[], status="closed")
    verdict, output, _ = run.judge(ticket)
    assert output["levels"] == {"cause": 2, "action": 2, "check": 0}  # the agent's own "confirm" step is not a check
    assert verdict == "needs_work"
    assert output["questions"] == [run.get_config().questions["check"]]
