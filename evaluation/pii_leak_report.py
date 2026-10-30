"""Check PII masking on every ticket: no known name, email or application name may survive.

Usage, from the repo root:  python evaluation/pii_leak_report.py
"""

import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.common.config import settings  # noqa: E402
from app.common.privacy.masking import Masker, PiiLeakError  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.models.ticket import Ticket  # noqa: E402
from app.platform.tickets.ingestion import ingest_workbook  # noqa: E402


def main() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_workbook(db, settings.TICKETS_FILE)
        tickets = db.query(Ticket).order_by(Ticket.id).all()

    counts, leaks, sample = Counter(), [], None
    for t in tickets:
        masker = Masker(known_names=[t.reporter_name, t.assignee], known_emails=[t.reporter_email])
        try:
            masked = [masker.mask(text) for text in (t.summary, t.description, t.attachments, t.resolution_notes)]
        except PiiLeakError as exc:
            leaks.append(f"{t.id}: {exc}")
            continue
        counts.update(masker.counts)
        if sample is None and t.source == "Mailbox" and masker.counts["PERSON"] and masker.counts["CODE"]:
            sample = (t.id, masked[1])

    print(f"Tickets masked   {len(tickets)}")
    print(f"Leaks            {len(leaks)}")
    print(f"Findings         {dict(counts.most_common())}")
    for leak in leaks:
        print(f"  {leak}")
    if sample:
        print(f"\nExample, {sample[0]} as the model would see it:\n{sample[1]}")


if __name__ == "__main__":
    main()
