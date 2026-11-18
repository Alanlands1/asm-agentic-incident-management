"""Score the Closure Quality agent against labelled cases and the real close notes.

Usage, from the repo root:  python evaluation/closure_report.py [--model]
  --model  also ask the model about every note the rules do not stop (real calls; needs the key in backend/.env)
Two sets, scored without a database, so nothing is written:
  cases  evaluation/closure_cases.xlsx: written by us (10 good, 10 vague, 10 the rules should stop, a test ticket).
         The support lead should confirm the labels.
  real   the close notes of the closed tickets in the sample data: all are good (a test ticket is skipped, not scored)
"""

import os
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")  # settings read backend/.env

from triage_report import PRICES  # noqa: E402  (list prices, shared with the Triage report)

from app.core.config import settings  # noqa: E402
from app.models.ticket import Ticket  # noqa: E402
from app.services.closure.run import judge  # noqa: E402

STOPPED_BY_RULES = {"empty", "filler", "too_short", "copy"}


def sheet(path: Path, name: str) -> list[dict]:
    rows = load_workbook(path, read_only=True)[name].iter_rows(values_only=True)
    header = next(rows)
    return [dict(zip(header, r)) for r in rows if any(r)]


def cases() -> list[dict]:
    return [
        {"id": c["case_id"], "expected": c["expected"], "kind": c["kind"], "confidence": c["confidence"], "why": c["why"],
         "ticket": Ticket(id=c["case_id"], summary=c["summary"], description=c["description"], application=c["application"],
                          resolution_notes=c["resolution_notes"] or None)}
        for c in sheet(REPO / "evaluation" / "closure_cases.xlsx", "cases")
    ]


def real_notes() -> list[dict]:
    """Closed tickets from both sources; all of them should be judged good (or skipped as a test)."""
    tickets = [
        Ticket(id=r["issue_key"], reporter_name=r["reporter"], summary=r["summary"], description=r["description"],
               application=r["components"], resolution_notes=r["resolution_comment"])
        for r in sheet(settings.TICKETS_FILE, "JIRA") if r["status"] == "Done"
    ] + [
        Ticket(id=r["ticket_id"], reporter_name=r["caller"], summary=r["short_description"], description=r["description"] or "",
               application=r["service"], resolution_notes=r["resolution_notes"])
        for r in sheet(REPO / "data" / "tickets" / "servicenow_tickets.xlsx", "servicenow_tickets") if r["closed_at"]
    ]
    return [{"id": t.id, "expected": "good", "kind": "real", "confidence": "clear", "why": "", "ticket": t} for t in tickets]


def run(items: list[dict]) -> list[dict]:
    for item in items:
        item["verdict"], item["output"], item["error"] = judge(item["ticket"])
    return items


def acceptable(item: dict) -> bool:
    """Right answer for the label; a real note may also be skipped as a test ticket."""
    return item["verdict"] == item["expected"] or (item["kind"] == "real" and item["verdict"] == "not_applicable")


def by_rules(item: dict) -> bool:
    """The rules decided this note on their own; a verdict from the model stage does not count."""
    return item["output"]["stage"] == "rules" and item["verdict"] != "uncertain"


def main() -> None:
    settings.LLM_ENABLED = "--model" in sys.argv  # a plain run is rules only, whatever backend/.env says
    labelled, real = run(cases()), run(real_notes())

    by_kind = lambda kinds: [i for i in labelled if i["kind"] in kinds]  # noqa: E731
    stopped = lambda items: [i for i in items if by_rules(i)]  # noqa: E731
    print(f"Rules (no model): {len(labelled)} labelled cases, {len(real)} real notes")
    print(f"  empty, filler, too short, copy   stopped by the rules {len(stopped(by_kind(STOPPED_BY_RULES)))} / {len(by_kind(STOPPED_BY_RULES))}")
    print(f"  test ticket                      skipped {len(stopped(by_kind({'test'})))} / {len(by_kind({'test'}))}")
    print(f"  good notes                       wrongly stopped {len(stopped(by_kind({'good'})))} / {len(by_kind({'good'}))}")
    print(f"  vague notes                      stopped {len(stopped(by_kind({'vague'})))} / {len(by_kind({'vague'}))} (the rest go to the model)")
    print(f"  real notes                       wrongly stopped {sum(by_rules(i) and i['verdict'] == 'needs_work' for i in real)} / {len(real)}; "
          f"test tickets skipped {sum(by_rules(i) and i['verdict'] == 'not_applicable' for i in real)}")

    if "--model" in sys.argv:
        model_report(labelled, real)


def model_report(labelled: list[dict], real: list[dict]) -> None:
    good, vague = [i for i in labelled if i["kind"] == "good"], [i for i in labelled if i["kind"] == "vague"]
    judged = [i for i in labelled + real if i["output"]["ai"] in ("used", "failed")]
    done = [i for i in judged if i["output"]["ai"] == "used"]
    tokens, drafts = Counter(), Counter()
    for i in done:
        a = i["output"]["audit"]
        tokens.update(input=a["input_tokens"], output=a["output_tokens"], read=a["cache_read_tokens"], write=a["cache_write_tokens"])
        if i["verdict"] == "needs_work":
            drafts["needs_work"] += 1
            drafts["draft"] += bool(i["output"]["draft_notes"])
            drafts["invented"] += bool(i["output"]["draft_invented"])
            drafts["gaps"] += "[engineer to add" in (i["output"]["draft_notes"] or "")
        drafts["quotes_dropped"] += len(i["output"]["dropped_quotes"])
    price_in, price_out, price_read = PRICES.get(settings.LLM_MODEL, (0, 0, 0))
    cost = (tokens["input"] * price_in + tokens["write"] * price_in * 1.25 + tokens["read"] * price_read
            + tokens["output"] * price_out) / 1e6
    latency = sorted(i["output"]["audit"]["latency_ms"] for i in done)

    print(f"\nModel stage: {settings.LLM_MODEL} ({len(judged)} notes the rules did not stop)")
    print(f"  answered                         {len(done)}   errors {len(judged) - len(done)}")
    print(f"  good cases passed                {sum(i['verdict'] == 'good' for i in good)} / {len(good)}")
    print(f"  vague cases held                 {sum(i['verdict'] == 'needs_work' for i in vague)} / {len(vague)}   "
          f"(borderline: {sum(i['verdict'] == 'needs_work' for i in vague if i['confidence'] == 'borderline')} / "
          f"{sum(i['confidence'] == 'borderline' for i in vague)})")
    print(f"  real notes judged good           {sum(i['verdict'] == 'good' for i in real)} / {len(real)}   "
          f"wrongly held {sum(i['verdict'] == 'needs_work' for i in real)}")
    print(f"  drafts                           {drafts['draft']} / {drafts['needs_work']} held notes got a draft; "
          f"{drafts['invented']} dropped for an invented code or number; {drafts['gaps']} still have gaps for the engineer")
    print(f"  quotes dropped (not in notes)    {drafts['quotes_dropped']}")
    print(f"  tokens in / out                  {tokens['input']} / {tokens['output']}   cache read / write {tokens['read']} / {tokens['write']}")
    print(f"  estimated cost                   ${cost:.3f}  (${cost / max(len(done), 1):.4f} per note)")
    print(f"  latency, median                  {latency[len(latency) // 2] if latency else 0} ms")

    for i in labelled + real:
        if not acceptable(i):
            o = i["output"]
            print(f"  BAD {i['id']:<10} {i['kind']:<9} ({i['confidence']}) expected {i['expected']}, got {i['verdict']}"
                  f"{' score ' + str(o['score']) + ' ' + str(o['levels']) if o['score'] is not None else ''}  {o['reason']}")
        if i["error"]:
            print(f"  ERR {i['id']}: {type(i['error']).__name__}: {i['error']}")


if __name__ == "__main__":
    main()
