"""Replies on tickets."""

from sqlalchemy.orm import Session

from app.models.ticket import Comment, PipelineStatus, Ticket


def add_comment(db: Session, ticket: Ticket, author_email: str, body: str) -> Comment:
    """Store a reply. A reply from the reporter sends a ticket awaiting information back for a fresh check."""
    from_reporter = bool(ticket.reporter_email) and author_email.strip().casefold() == ticket.reporter_email.casefold()
    comment = Comment(ticket=ticket, author_email=author_email.strip(), body=body, from_reporter=from_reporter)
    db.add(comment)
    if from_reporter and ticket.pipeline_status == PipelineStatus.AWAITING_INFO:
        ticket.pipeline_status = PipelineStatus.PENDING
    db.commit()
    return comment
