"""Who is working now: the team's hours and leave, from data/registry/team.yaml (the lead edits it on the Team page).

An engineer on leave gets no suggested tickets; one off shift gets them only when nobody is on shift.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.core.registry import load_registry, register_document

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ON_SHIFT, OFF_SHIFT, ON_LEAVE = "on_shift", "off_shift", "on_leave"


@dataclass(frozen=True)
class Hours:
    days: frozenset[int]  # 0 is Monday
    start: time
    end: time  # before the start: a night shift, ending the next morning


@dataclass(frozen=True)
class Team:
    offset: timedelta  # the team's local time is UTC plus this
    default: Hours
    engineers: dict[str, Hours]  # by their name in Jira; anyone else works the default hours
    leave: tuple[tuple[str, date, date], ...]  # name, first day, last day
    members: frozenset[str] = frozenset()  # put on the team by the lead
    not_members: frozenset[str] = frozenset()  # taken off it by the lead
    max_open: int = 8  # open tickets at which an engineer is suggested no more, except a P1 or P2


def _hours(doc: dict) -> Hours:
    days = frozenset(DAYS.index(str(d).lower()) for d in doc["days"])
    hours = Hours(days, time.fromisoformat(str(doc["start"])), time.fromisoformat(str(doc["end"])))
    if not days or hours.start == hours.end:
        raise ValueError("Working hours need at least one day, and a start different from the end")
    return hours


def config() -> Team:
    doc = load_registry("team.yaml")
    sign, clock = str(doc["utc_offset"])[0], time.fromisoformat(str(doc["utc_offset"])[1:])
    if sign not in "+-":
        raise ValueError("utc_offset looks like +05:30 or -04:00")
    offset = timedelta(hours=clock.hour, minutes=clock.minute) * (1 if sign == "+" else -1)
    default = _hours(doc["default"])
    engineers = {str(name): _hours({**doc["default"], **(own or {})}) for name, own in (doc.get("engineers") or {}).items()}
    leave = tuple((str(row["name"]), date.fromisoformat(str(row["from"])), date.fromisoformat(str(row["to"])))
                  for row in doc.get("leave") or [])
    if any(first > last for _, first, last in leave):
        raise ValueError("Leave ends on or after the day it starts")
    members, others = (frozenset(str(n) for n in doc.get(key) or []) for key in ("members", "not_members"))
    max_open = int(doc.get("max_open", 8))
    if max_open < 1:
        raise ValueError("max_open is at least 1")
    return Team(offset, default, engineers, leave, members, others, max_open)


register_document("team", "team.yaml", config)


def _working(hours: Hours, local: datetime) -> bool:
    today, yesterday, clock = local.weekday(), (local.weekday() - 1) % 7, local.time()
    if hours.start < hours.end:
        return today in hours.days and hours.start <= clock < hours.end
    return (today in hours.days and clock >= hours.start) or (yesterday in hours.days and clock < hours.end)


def status(name: str, at: datetime | None = None, team: Team | None = None) -> dict:
    """An engineer's state at `at` (UTC; now by default): on_shift, off_shift, or on_leave with its last day."""
    team = team or config()
    at = at or datetime.now(UTC)
    local = (at.astimezone(UTC).replace(tzinfo=None) if at.tzinfo else at) + team.offset
    until = max((last for who, first, last in team.leave if who == name and first <= local.date() <= last), default=None)
    if until is not None:
        return {"state": ON_LEAVE, "until": until}
    working = _working(team.engineers.get(name, team.default), local)
    return {"state": ON_SHIFT if working else OFF_SHIFT, "until": None}
