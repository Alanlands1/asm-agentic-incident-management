"""What the agents write on a Jira issue once Data Quality has passed."""

from app.models.ticket import AgentRun, PipelineStatus, Ticket
from app.services import jira

DQ = AgentRun(agent="data_quality", verdict="passed", output={"answer": {"reason": "Symptom, error and app are clear. More."}})


def test_a_triaged_issue_also_says_data_quality_passed():
    triage = AgentRun(agent="triage", verdict="P2", output={"priority": 2, "reason": "Orders are stuck."})
    ticket = Ticket(id="AMS-4", pipeline_status=PipelineStatus.TRIAGED, reported_priority=2, agent_runs=[DQ, triage])
    text, label = jira._announcement(ticket)
    assert text.splitlines()[:3] == ["AMS agents · Recommended priority: P2",
                                     "Data Quality: complete. Symptom, error and app are clear.", "Why: Orders are stuck."]
    assert label == "ams-p2"


def test_an_issue_waiting_for_triage_is_told_its_details_are_complete():
    ticket = Ticket(id="AMS-4", pipeline_status=PipelineStatus.DQ_PASSED, agent_runs=[DQ])
    text, label = jira._announcement(ticket)
    assert text == ("AMS agents · Details complete\nData Quality: complete. Symptom, error and app are clear.\n"
                    "Waiting for the Triage agent.")
    assert label == "ams-dq-passed" and label in jira.LABELS  # the reset and the next verdict remove it
