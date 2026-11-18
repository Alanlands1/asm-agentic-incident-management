"""Group open tickets that report the same issue at once into a storm, with one main ticket and the rest linked to it.

Runs over every open ticket, so it does not need to happen the moment a ticket arrives: re-running is safe and updates
the storms it already made. Advisory only: nothing is sent, and declaring a major incident just records who did.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.triage.config import Rule, get_config
from app.agents.triage.rules import evaluate, find_rule
from app.core.registry import load_registry, register_document
from app.models.ticket import PipelineStatus, Storm, Ticket

WORDS = re.compile(r"[a-z0-9]{3,}")


@dataclass(frozen=True)
class StormConfig:
    window_min: dict[str | None, int]  # application -> minutes; None is the default
    people_needed: dict[str | None, int]
    quiet_min: int
    similar_text: float
    cross_app: dict[str, tuple[re.Pattern, ...]]


def config() -> StormConfig:
    doc = load_registry("storms.yaml")
    default, apps = doc["default"], doc["applications"] or {}
    cfg = StormConfig(
        window_min={None: default["window_min"], **{a: v.get("window_min", default["window_min"]) for a, v in apps.items()}},
        people_needed={
            None: default["people_needed"], **{a: v.get("people_needed", default["people_needed"]) for a, v in apps.items()}
        },
        quiet_min=doc["quiet_min"],
        similar_text=doc["similar_text"],
        cross_app={name: tuple(re.compile(p, re.I) for p in patterns) for name, patterns in doc["cross_app"].items()},
    )
    if min(*cfg.window_min.values(), *cfg.people_needed.values(), cfg.quiet_min) < 1 or not 0 < cfg.similar_text <= 1:
        raise ValueError("window_min, people_needed and quiet_min must be at least 1, and similar_text between 0 and 1")
    return cfg


register_document("storms", "storms.yaml", config)


def now() -> datetime:
    """Ticket times are naive; they are compared as UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class _Item:
    ticket: Ticket
    application: str | None
    keys: set[str]  # known issues: job:..., rule:..., cross:...
    words: frozenset[str]
    has_job: bool

    @property
    def person(self) -> str:
        t = self.ticket
        return (t.reporter_email or t.reporter_name or t.id).strip().casefold()


def _item(ticket: Ticket, cfg: StormConfig) -> _Item:
    triage_config = get_config()
    result = evaluate(ticket.summary, ticket.description, ticket.application, ticket.opened_at)
    app, keys = result.signals.application, {f"job:{j}" for j in result.signals.failed_jobs}
    rule = find_rule(triage_config, app, result.decision.rule) if result.decision else None
    if isinstance(rule, Rule):  # only an application's own known issue; a generic "outage" would join unrelated tickets
        keys.add(f"rule:{rule.name}")
    text = f"{ticket.summary}\n{ticket.description}"
    keys |= {f"cross:{name}" for name, patterns in cfg.cross_app.items() if any(p.search(text) for p in patterns)}
    words = frozenset(WORDS.findall(f"{ticket.summary} {ticket.description[:300]}".casefold()))
    return _Item(ticket, app, keys, words, bool(result.signals.failed_jobs))


def _alike(a: _Item, b: _Item, cfg: StormConfig) -> bool:
    gap = abs(a.ticket.opened_at - b.ticket.opened_at)
    shared = a.keys & b.keys
    if any(k.startswith("cross:") for k in shared) and gap <= timedelta(minutes=cfg.window_min[None]):
        return True  # login problems on any application
    if a.application is None or a.application != b.application:
        return False
    if gap > timedelta(minutes=cfg.window_min.get(a.application, cfg.window_min[None])):
        return False
    if shared:
        return True
    union = a.words | b.words
    return bool(union) and len(a.words & b.words) / len(union) >= cfg.similar_text


def _clusters(items: list[_Item], cfg: StormConfig) -> list[list[_Item]]:
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in combinations(range(len(items)), 2):
        if _alike(items[i], items[j], cfg):
            parent[find(i)] = find(j)
    groups: dict[int, list[_Item]] = {}
    for i, item in enumerate(items):
        groups.setdefault(find(i), []).append(item)
    return [sorted(g, key=lambda x: (x.ticket.opened_at, x.ticket.id)) for g in groups.values() if len(g) > 1]


@dataclass
class StormRun:
    created: int = 0
    updated: int = 0
    linked: int = 0  # tickets that follow a main ticket
    storms: list[Storm] = field(default_factory=list)


def detect_storms(db: Session, at: datetime | None = None) -> StormRun:
    """Find storms among the open tickets and store them. Safe to re-run: existing storms are updated, not duplicated."""
    cfg, at, result = config(), at or now(), StormRun()
    tickets = db.scalars(
        select(Ticket).where(
            Ticket.pipeline_status.notin_([PipelineStatus.HISTORICAL, PipelineStatus.REJECTED]), Ticket.opened_at.is_not(None)
        )
    ).all()

    for cluster in _clusters([_item(t, cfg) for t in tickets], cfg):
        apps = {i.application for i in cluster}
        app = apps.pop() if len(apps) == 1 else None  # None: spans applications
        people = len({i.person for i in cluster})
        if people < cfg.people_needed.get(app, cfg.people_needed[None]):
            continue

        ids = sorted({i.ticket.storm_id for i in cluster if i.ticket.storm_id})
        storm = db.get(Storm, ids[0]) if ids else Storm(
            application=app, issue_key="", main_ticket_id="", people=0, ticket_count=0,
            opened_at=at, last_ticket_at=at, status="open",
        )
        for other in ids[1:]:  # two storms grew into one: keep the older, drop the other unless a person declared it
            if (extra := db.get(Storm, other)) is not None and extra.declared_at is None:
                db.delete(extra)
        counts = Counter(k for i in cluster for k in i.keys)
        member_ids = {i.ticket.id for i in cluster}
        main = storm.main_ticket_id if storm.main_ticket_id in member_ids else next(
            (i for i in cluster if i.has_job), cluster[0]).ticket.id  # the failed job if there is one, else the first
        first, last = cluster[0].ticket.opened_at, max(i.ticket.opened_at for i in cluster)

        result.created += storm.id is None
        result.updated += storm.id is not None
        storm.application, storm.main_ticket_id, storm.people, storm.ticket_count = app, main, people, len(cluster)
        storm.issue_key = min(counts, key=lambda k: (-counts[k], k)) if counts else "similar text"
        storm.opened_at, storm.last_ticket_at = first, last
        storm.status = "declared" if storm.declared_at else "open" if at - last <= timedelta(minutes=cfg.quiet_min) else "closed"
        db.add(storm)
        db.flush()
        for i in cluster:
            i.ticket.storm_id = storm.id
        result.linked += len(cluster) - 1
        result.storms.append(storm)
    return result


def declare(db: Session, storm: Storm, declared_by: str) -> Storm:
    """A person declares a major incident. This only records it: the major-incident agent picks it up from here."""
    storm.declared_by, storm.declared_at, storm.status = declared_by.strip(), datetime.now(timezone.utc), "declared"
    db.commit()
    return storm
