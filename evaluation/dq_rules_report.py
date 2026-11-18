"""Score the Data Quality rules stage against the answer key.

Usage, from the repo root:  python evaluation/dq_rules_report.py [--model]
  --model  also ask the model about every ticket the rules leave open (real calls; needs the key in backend/.env)
Runs on a throwaway in-memory database, so backend/ams.db is never touched.
"""

import os
import re
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")  # settings read backend/.env

from app.services.data_quality import run_data_quality  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.llm import ModelError  # noqa: E402
from app.models.ticket import AgentRun, Ticket  # noqa: E402
from app.services.ingestion import ingest_workbook  # noqa: E402
from triage_report import PRICES  # noqa: E402  (list prices, shared with the Triage report)


def answer_key() -> dict[str, dict]:
    rows = load_workbook(REPO / "evaluation" / "ground_truth.xlsx", read_only=True).active.iter_rows(values_only=True)
    header = next(rows)
    return {r[0]: dict(zip(header, r)) for r in rows}


def ask_model(db: Session, runs: list[AgentRun], key: dict[str, dict]) -> list[dict]:
    """One real model call per ticket the rules left open, through the same code the service runs."""
    from app.agents.data_quality.model_check import check_completeness
    from app.agents.data_quality.signals import Signals
    from app.services.data_quality import reporter_text

    results = []
    for run in (r for r in runs if r.verdict == "uncertain"):
        ticket = db.get(Ticket, run.ticket_id)
        row = {"id": ticket.id, "summary": ticket.summary, "expected": key[ticket.id]["dq_should_pass"] == "Yes"}
        try:
            row["answer"], row["audit"] = check_completeness(ticket, reporter_text(ticket), Signals(**run.output["signals"]))
        except ModelError as exc:
            row["error"] = exc
        results.append(row)
    return results


def ask_cases() -> list[dict]:
    """The borderline cases in dq_model_cases.xlsx: rules first, then the model, as the service does."""
    from app.agents.data_quality.model_check import check_completeness
    from app.agents.data_quality.rules import evaluate

    rows = load_workbook(REPO / "evaluation" / "dq_model_cases.xlsx", read_only=True)["cases"].iter_rows(values_only=True)
    header = next(rows)
    results = []
    for case in (dict(zip(header, r)) for r in rows):
        ticket = Ticket(id=case["case_id"], reporter_name=case["reporter_name"], reporter_email=case["reporter_email"],
                        application=case["application"], summary=case["summary"], description=case["description"])
        rules = evaluate(ticket.summary, ticket.description, None, ticket.application)
        row = {"id": ticket.id, "expected": case["expected"] == "complete", "confidence": case["confidence"],
               "why": case["why"], "rules": rules.verdict}
        if rules.verdict != "uncertain":
            row["complete"] = False  # stopped by the rules
        else:
            try:
                row["answer"], row["audit"] = check_completeness(ticket, ticket.description, rules.signals)
                row["complete"] = row["answer"].complete
            except ModelError as exc:
                row["error"] = exc
        results.append(row)
    return results


def cases_report(results: list[dict]) -> None:
    done = [r for r in results if "complete" in r]
    good, unusable = [r for r in done if r["expected"]], [r for r in done if not r["expected"]]
    print(f"\nBorderline cases ({len(results)}; written by us, the support lead should confirm the labels)")
    print(f"  good, passed                     {sum(r['complete'] for r in good)} / {len(good)}")
    print(f"  unusable, held                   {sum(not r['complete'] for r in unusable)} / {len(unusable)}")
    for r in done:
        if r["complete"] != r["expected"]:
            missing = f" missing {r['answer'].missing}" if "answer" in r and not r["answer"].complete else ""
            print(f"  BAD {r['id']} ({r['confidence']}) {'good' if r['expected'] else 'unusable'}, "
                  f"model says {'complete' if r['complete'] else 'incomplete'}{missing}  [{r['why']}]")
    for r in results:
        if "error" in r:
            print(f"  ERR {r['id']}: {type(r['error']).__name__}: {r['error']}")


def model_report(results: list[dict], caught: int, total: int) -> None:
    done = [r for r in results if "answer" in r]
    right = [r for r in done if r["answer"].complete == r["expected"]]
    passed_wrongly = [r for r in done if r["answer"].complete and not r["expected"]]
    held_wrongly = [r for r in done if not r["answer"].complete and r["expected"]]
    tokens = Counter()
    for r in done:
        a = r["audit"]
        tokens.update(input=a.input_tokens, output=a.output_tokens, read=a.cache_read_tokens, write=a.cache_write_tokens)
    price_in, price_out, price_read = PRICES.get(settings.LLM_MODEL, (0, 0, 0))
    cost = (tokens["input"] * price_in + tokens["write"] * price_in * 1.25 + tokens["read"] * price_read
            + tokens["output"] * price_out) / 1e6
    latency = sorted(r["audit"].latency_ms for r in done)
    leftover = sum(len(re.findall(r"<[A-Z_]+_\d+>", r["answer"].reason + (r["answer"].chase_email or ""))) for r in done)

    print(f"\nModel stage: {settings.LLM_MODEL} ({len(results)} tickets the rules left open)")
    print(f"  answered                         {len(done)}   errors {len(results) - len(done)}")
    print(f"  correct                          {len(right)} / {len(done)}")
    print(f"  incomplete, wrongly passed       {len(passed_wrongly)} / {sum(not r['expected'] for r in done)}")
    print(f"  good, wrongly held               {len(held_wrongly)} / {sum(r['expected'] for r in done)}")
    print(f"  placeholders left in answers     {leftover}")
    print(f"  tokens in / out                  {tokens['input']} / {tokens['output']}   cache read / write {tokens['read']} / {tokens['write']}")
    print(f"  estimated cost                   ${cost:.3f}  (${cost / max(len(done), 1):.4f} per ticket)")
    print(f"  latency, median                  {latency[len(latency) // 2] if latency else 0} ms")
    print(f"Rules + model, end to end          {caught + len(right)} / {total} correct")
    for r in done:
        a = r["answer"]
        if a.complete != r["expected"]:
            print(f"  BAD {r['id']:<11} model says {'complete' if a.complete else 'incomplete ' + str(a.missing)}, "
                  f"expected {'complete' if r['expected'] else 'incomplete'}  {a.reason}")
    for r in done:
        if not r["answer"].complete:
            print(f"\n  incomplete {r['id']}: missing {r['answer'].missing}\n    {r['answer'].chase_email}")
    for r in results:
        if "error" in r:
            print(f"  ERR {r['id']:<11} {type(r['error']).__name__}: {r['error']}")


def main() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    key = answer_key()

    with Session(engine) as db:
        ingest_workbook(db, settings.TICKETS_FILE)
        settings.LLM_ENABLED = False  # backend/.env may switch the model on; this run is the rules stage only
        run_data_quality(db)
        runs = db.query(AgentRun).all()
        settings.LLM_ENABLED = "--model" in sys.argv  # real calls only when asked for
        answers = ask_model(db, runs, key) if settings.LLM_ENABLED else None  # while the session is open

    should_fail = [r for r in runs if key[r.ticket_id]["dq_should_pass"] == "No"]
    should_pass = [r for r in runs if key[r.ticket_id]["dq_should_pass"] == "Yes"]
    caught = [r for r in should_fail if r.verdict != "uncertain"]
    false_fails = [r for r in should_pass if r.verdict != "uncertain"]
    with_app = [r for r in should_pass if key[r.ticket_id]["expected_application"]]
    app_ok = [r for r in with_app if r.output["signals"]["app_found"] == key[r.ticket_id]["expected_application"]]
    shortest_pass = min(should_pass, key=lambda r: r.output["signals"]["body_length"])

    print(f"Open tickets checked      {len(runs)}")
    print(f"Incomplete caught         {len(caught)} / {len(should_fail)}")
    print(f"Good tickets wrongly held {len(false_fails)} / {len(should_pass)}")
    print(f"Left for the model        {len(runs) - len(caught) - len(false_fails)}")
    print(f"Application found         {len(app_ok)} / {len(with_app)}")
    print(f"Shortest good description {shortest_pass.output['signals']['body_length']} characters ({shortest_pass.ticket_id})")

    for title, items in [
        ("Incomplete, left for the model", [r for r in should_fail if r.verdict == "uncertain"]),
        ("Good, wrongly held", false_fails),
        ("Wrong application", [r for r in with_app if r not in app_ok]),
    ]:
        if items:
            print(f"\n{title}:")
            for r in items:
                print(f"  {r.ticket_id:<11} {r.verdict:<16} app={r.output['signals']['app_found']} "
                      f"expected={key[r.ticket_id]['expected_application']}  {r.output['reason']}")

    if answers is not None:
        model_report(answers, len(caught), len(runs))
        cases_report(ask_cases())


if __name__ == "__main__":
    main()
