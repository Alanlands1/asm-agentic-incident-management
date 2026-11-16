"""What needs a person now: open or declared storms, and P1/P2 tickets whose first message is not sent yet."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.incident import FirstMessage
from app.models.ticket import Storm, Ticket
from app.services.triage import sla

ACTIVE_STORM = ("open", "declared")


@dataclass
class Attention:
    storms: list[Storm]
    items: list[sla.SlaItem]  # open P1/P2, most at risk first
    sent: dict[str, FirstMessage]  # ticket id -> its latest sent message

    @property
    def count(self) -> int:
        return len(self.storms) + sum(1 for i in self.items if i.ticket.id not in self.sent)


def attention(db: Session, at: datetime | None = None) -> Attention:
    storms = list(db.scalars(select(Storm).where(Storm.status.in_(ACTIVE_STORM)).order_by(Storm.opened_at.desc())))
    items = sla.open_p1_p2(db, at)
    sent: dict[str, FirstMessage] = {}
    by_storm: dict[int, FirstMessage] = {}
    ids, storm_ids = [i.ticket.id for i in items], {i.storm_id for i in items if i.storm_id}
    rows = select(FirstMessage).where(or_(FirstMessage.ticket_id.in_(ids), FirstMessage.storm_id.in_(storm_ids)))
    for m in db.scalars(rows.order_by(FirstMessage.id)):  # the last one wins
        sent[m.ticket_id] = m
        if m.storm_id:
            by_storm[m.storm_id] = m
    for i in items:  # one message per storm covers every ticket in it
        if i.ticket.id not in sent and i.storm_id in by_storm:
            sent[i.ticket.id] = by_storm[i.storm_id]
    return Attention(storms, items, sent)


def attention_count(db: Session, at: datetime | None = None) -> int:
    return attention(db, at).count


def record_sent(db: Session, ticket: Ticket, text: str, sent_by: str) -> FirstMessage:
    message = FirstMessage(ticket_id=ticket.id, storm_id=ticket.storm_id, text=text, sent_by=sent_by)
    db.add(message)
    db.commit()
    return message
