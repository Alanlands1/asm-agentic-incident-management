"""Score the Triage rules stage against the answer key.

Usage, from the repo root:  python evaluation/triage_report.py [--model]
  --model  also ask the model about every ticket the rules leave open (real calls; needs the key in backend/.env)
Two sets, open and closed tickets alike, every ticket with an expected priority:
  tuning    JIRA and Mailbox (ams_tickets.xlsx); the rules were written while looking at these
  held-out  ServiceNow (servicenow_tickets.xlsx); not used to write the rules, so the fairer score
"""

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")  # settings read backend/.env

from app.agents.triage.rules import evaluate  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.llm import ModelError  # noqa: E402
from app.models.ticket import Ticket  # noqa: E402
from app.services.ingestion import ingest_workbook  # noqa: E402


def answer_key() -> dict[str, dict]:
    rows = load_workbook(REPO / "evaluation" / "ground_truth.xlsx", read_only=True).active.iter_rows(values_only=True)
    header = next(rows)
    return {r[0]: dict(zip(header, r)) for r in rows}


def tuning_set() -> list[Ticket]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_workbook(db, settings.TICKETS_FILE)
        return db.query(Ticket).order_by(Ticket.id).all()


def held_out_set() -> list[Ticket]:
    workbook = load_workbook(REPO / "data" / "tickets" / "servicenow_tickets.xlsx", read_only=True)
    rows = workbook["servicenow_tickets"].iter_rows(values_only=True)
    header = next(rows)
    return [
        Ticket(id=r["ticket_id"], reporter_name=r["caller"], summary=r["short_description"] or "",
               description=r["description"] or "", application=r["service"], reported_priority=int(r["priority"][0]) if r["priority"] else None,
               opened_at=datetime.fromisoformat(str(r["opened_at"])) if r["opened_at"] else None)
        for r in (dict(zip(header, row)) for row in rows)
    ]


def main() -> None:
    key = answer_key()
    for title, tickets in [("TUNING SET: JIRA + Mailbox", tuning_set()), ("HELD-OUT SET: ServiceNow", held_out_set())]:
        scored = [t for t in tickets if t.id in key and key[t.id]["expected_priority"]]
        print(f"\n===== {title} =====")
        results = [(t, evaluate(t.summary, t.description, t.application, t.opened_at)) for t in scored]
        report(results, key)
        if "--model" in sys.argv:
            model_report(results, key)


# $ per 1M tokens: input, output, cache read (Anthropic list prices, Oct 2026; check before relying on them).
# Cache writes cost 1.25x input. Haiku's cache-read rate is assumed at 10% of input.
PRICES = {"claude-opus-5-5": (4.00, 20.00, 0.20), "claude-sonnet-5-5": (2.00, 10.00, 0.20),
          "claude-haiku-5-5": (0.10, 0.50, 0.01)}


def model_report(results: list, key: dict[str, dict]) -> None:
    """One real model call per ticket the rules left open, through the same code the service runs."""
    from app.services.triage import model_decision

    asked = [(t, r) for t, r in results if not r.priority]
    answered, errors, dropped, tokens, latency, masked = [], [], Counter(), Counter(), [], Counter()
    for t, r in asked:
        try:
            decision, answer, lost, audit = model_decision(t, t.description, r)
        except ModelError as exc:
            errors.append((t, exc))
            continue
        answered.append((t, decision, answer, lost))
        dropped.update(lost)
        tokens.update(input=audit.input_tokens, output=audit.output_tokens,
                      cache_read=audit.cache_read_tokens, cache_write=audit.cache_write_tokens)
        latency.append(audit.latency_ms)
        masked.update(audit.pii_masked)

    expected = {t.id: key[t.id]["expected_priority"] for t, _ in results}
    right = [a for a in answered if a[1].priority == expected[a[0].id]]
    rules_right = sum(r.priority == expected[t.id] for t, r in results if r.priority)
    price_in, price_out, price_read = PRICES.get(settings.LLM_MODEL, (0, 0, 0))
    cost = (tokens["input"] * price_in + tokens["cache_write"] * price_in * 1.25
            + tokens["cache_read"] * price_read + tokens["output"] * price_out) / 1e6
    print(f"\nModel stage: {settings.LLM_MODEL} ({len(asked)} tickets)")
    print(f"  answered                         {len(answered)}   errors {len(errors)}")
    print(f"  correct                          {len(right)} / {len(answered)}")
    print(f"  too high / too low               {sum(a[1].priority < expected[a[0].id] for a in answered)}"
          f" / {sum(a[1].priority > expected[a[0].id] for a in answered)}")
    print(f"  facts dropped (no real quote)    {dict(dropped) or 0}")
    print(f"  tokens in / out                  {tokens['input']} / {tokens['output']}"
          f"   cache read / write {tokens['cache_read']} / {tokens['cache_write']}")
    print(f"  estimated cost                   ${cost:.3f}  (${cost / max(len(answered), 1):.4f} per ticket)")
    print(f"  latency, median                  {sorted(latency)[len(latency) // 2] if latency else 0} ms")
    print(f"  personal data masked             {dict(masked)}")
    print(f"Rules + model, end to end          {rules_right + len(right)} / {len(results)} correct")
    for t, decision, answer, lost in answered:
        mark = "ok " if decision.priority == expected[t.id] else "BAD"
        print(f"  {mark} {t.id:<11} P{decision.priority} expected=P{expected[t.id]}  rule={answer.rule} "
              f"scope={answer.scope}{' dropped=' + ','.join(lost) if lost else ''}  {answer.reason}")
    for t, exc in errors:
        print(f"  ERR {t.id:<11} {type(exc).__name__}: {exc}")


def report(results: list, key: dict[str, dict]) -> None:
    decided = [(t, r) for t, r in results if r.priority]
    correct = [(t, r) for t, r in decided if r.priority == key[t.id]["expected_priority"]]
    mismatch = [(t, r) for t, r in results if key[t.id]["scenario"] == "priority_mismatch"]
    per_app = defaultdict(lambda: [0, 0, 0])  # decided, correct, total
    for t, r in results:
        stats = per_app[key[t.id]["expected_application"] or "(none)"]
        stats[0] += bool(r.priority)
        stats[1] += r.priority == key[t.id]["expected_priority"]
        stats[2] += 1

    print(f"Tickets with an expected priority  {len(results)}")
    print(f"Decided by the rules               {len(decided)}")
    print(f"  correct                          {len(correct)} / {len(decided)}")
    print(f"  too high (more urgent)           {sum(r.priority < key[t.id]['expected_priority'] for t, r in decided)}")
    print(f"  too low                          {sum(r.priority > key[t.id]['expected_priority'] for t, r in decided)}")
    print(f"Left for the model                 {len(results) - len(decided)}")
    fallback = [(t, r) for t, r in results if not r.priority and r.fallback]
    print(f"  model off, rules' own answer     {sum(r.fallback.priority == key[t.id]['expected_priority'] for t, r in fallback)}"
          f" / {len(fallback)} correct (leaning high when a P1/P2 is possible); "
          f"{len(results) - len(decided) - len(fallback)} stay undecided")
    fixed = sum(r.priority == key[t.id]["expected_priority"] for t, r in mismatch)
    print(f"Reporter priority wrong, fixed     {fixed} / {len(mismatch)}")
    print("\nPer application (decided, correct / total):")
    for app, (d, c, n) in sorted(per_app.items()):
        print(f"  {app:<18} {d:>2} decided, {c:>2} correct / {n}")

    for title, items in [
        ("Wrong priority", [(t, r) for t, r in decided if (t, r) not in correct]),
        ("Left for the model", [(t, r) for t, r in results if not r.priority]),
    ]:
        if items:
            print(f"\n{title}:")
            for t, r in items:
                print(f"  {t.id:<11} got={r.verdict:<9} expected=P{key[t.id]['expected_priority']} "
                      f"reported={t.reported_priority}  {r.reason}")


if __name__ == "__main__":
    main()
