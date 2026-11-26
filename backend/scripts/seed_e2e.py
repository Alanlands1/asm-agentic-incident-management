"""A throwaway SQLite database for the console's browser tests (frontend/e2e).

The sample tickets, plus one ticket (AMS-1209) past Data Quality and Triage with a suggested fix, so the ticket page has
a result to rate, and one person per role to sign in as (<role>@e2e.test, password e2e-password). Nothing reaches Supabase, Jira or the model. Usage: python scripts/seed_e2e.py <path.db>
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/, so `app` imports when run as a script
db_path = Path(sys.argv[1]).resolve()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"  # before the app reads its settings

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.admin.models  # noqa: E402,F401  (registers the admin tables)
import app.models  # noqa: E402,F401  (registers every table)
from app.core.config import settings  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.models.ticket import AgentRun, PipelineStatus, Review, Ticket  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import demo_history  # noqa: E402
from app.services.auth import ROLES, hash_password  # noqa: E402
from app.services.ingestion import ingest_workbook  # noqa: E402

TICKET = "AMS-1209"

db_path.parent.mkdir(parents=True, exist_ok=True)
db_path.unlink(missing_ok=True)
engine = create_engine(f"sqlite:///{db_path.as_posix()}")
Base.metadata.create_all(engine)
with Session(engine) as db:
    print(ingest_workbook(db, settings.TICKETS_FILE))
    ticket = db.get(Ticket, TICKET)
    db.add(AgentRun(ticket_id=TICKET, agent="data_quality", verdict="passed", output={"stage": "rules", "reason": "Complete."}))
    triage = AgentRun(ticket_id=TICKET, agent="triage", verdict="P3",
                      output={"stage": "rules", "priority": 3, "reason": "One team affected."})
    db.add(triage)
    db.flush()
    db.add(Review(ticket_id=TICKET, agent_run_id=triage.id, agent="triage", action="accepted", final_priority=3,
                  reviewer="AMS agents (auto)", note="Approved without review: Triage did not lower the priority"))
    db.add(AgentRun(ticket_id=TICKET, agent="resolution", verdict="resolved",
                    output={"root_cause": "The payslip job read a stale template.", "confidence": "high",
                            "steps": ["Re-run the payslip job with the current template.", "Open three payslips to check."],
                            "references": ["KB-PAY-001"]}))
    ticket.pipeline_status = PipelineStatus.REVIEWED
    for role in ROLES:
        db.add(User(email=f"{role}@e2e.test", name=f"E2E {role.title()}", role=role, password_hash=hash_password("e2e-password")))
    db.commit()
    print(f"{demo_history.generate(db)} demo history tickets for the reports")
print(f"Seeded {db_path}")
