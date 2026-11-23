"""Score the Knowledge Builder's matching of resolved tickets to knowledge-base articles.

Usage, from the repo root:  python evaluation/knowledge_report.py [--model]
  --model  also ask the model about every case the rules are not sure of (real calls; needs the key in backend/.env)
Three sets, scored without a database, so nothing is written:
  real      the closed tickets in the sample data that the answer key ties to an article, matched as they are
            and again with the "Followed KB-..." citation removed from the notes
  reworded  evaluation/knowledge_cases.xlsx, 6 cases that should match an article but are worded differently
  none      evaluation/knowledge_cases.xlsx, 10 cases no article covers (7 defects, 2 outside scope, 1 request),
            including a trap: a broken payslip link is not a blank payslip PDF
The cases were written by us; an expert should confirm which article each belongs to.
"""

import os
import re
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
from app.services.knowledge.run import match_case  # noqa: E402

CITATION = re.compile(r"Followed KB-[A-Z]+-\d+\.?\s*")


def sheet(path: Path, name: str) -> list[dict]:
    rows = load_workbook(path, read_only=True)[name].iter_rows(values_only=True)
    header = next(rows)
    return [dict(zip(header, r)) for r in rows if any(r)]


def real_cases() -> list[tuple[Ticket, str, str]]:
    """(ticket, notes, expected article) for every closed ticket the answer key ties to an article."""
    key = {r["ticket_ref"]: r["expected_kb_article"] for r in sheet(REPO / "evaluation" / "ground_truth.xlsx", "Ground_Truth")}
    tickets = [
        (Ticket(id=r["issue_key"], reporter_name=r["reporter"], summary=r["summary"], description=r["description"],
                application=r["components"]), r["resolution_comment"])
        for r in sheet(settings.TICKETS_FILE, "JIRA") if r["status"] == "Done"
    ] + [
        (Ticket(id=r["ticket_id"], reporter_name=r["caller"], summary=r["short_description"], description=r["description"] or "",
                application=r["service"]), r["resolution_notes"])
        for r in sheet(REPO / "data" / "tickets" / "servicenow_tickets.xlsx", "servicenow_tickets") if r["closed_at"]
    ]
    return [(t, notes, key[t.id]) for t, notes in tickets if key.get(t.id)]


def written_cases() -> list[tuple[Ticket, str, str, str]]:
    """(ticket, notes, expected article or 'none', kind)"""
    return [
        (Ticket(id=c["case_id"], summary=c["summary"], description=c["description"], application=c["application"]),
         c["resolution_notes"], c["expected"], c["kind"])
        for c in sheet(REPO / "evaluation" / "knowledge_cases.xlsx", "cases")
    ]


def judge(items: list[tuple[Ticket, str, str, str]]) -> list[dict]:
    out = []
    for ticket, notes, expected, kind in items:
        status, article, method, output, error = match_case(ticket, notes)
        out.append({"id": ticket.id, "kind": kind, "expected": expected, "status": status, "article": article,
                    "method": method, "output": output, "error": error, "reason": output["reason"], "ticket": ticket,
                    "notes": notes})
    return out


def right(item: dict) -> bool:
    """Matched the expected article, or flagged a gap where none is expected."""
    return item["article"] == item["expected"] if item["status"] == "matched" else (item["status"] == "gap" and item["expected"] == "none")


def main() -> None:
    settings.LLM_ENABLED = "--model" in sys.argv  # a plain run is rules only, whatever backend/.env says
    real = real_cases()
    kept = judge([(t, n, e, "real_cited") for t, n, e in real])
    removed = judge([(t, CITATION.sub("", n), e, "real_removed") for t, n, e in real])
    cases = judge(written_cases())
    reworded, none = [c for c in cases if c["kind"] == "match"], [c for c in cases if c["kind"] != "match"]

    def rules(items: list[dict]) -> tuple[int, int, str]:
        matched = [i for i in items if i["output"]["stage"] == "rules" and i["status"] == "matched"]
        ways = Counter(i["method"] for i in matched)
        return len(matched), sum(i["article"] == i["expected"] for i in matched), ", ".join(f"{k} {v}" for k, v in sorted(ways.items()))

    print(f"Rules (no model): {len(real)} real closed tickets, {len(reworded)} reworded cases, {len(none)} cases no article covers")
    for label, items in (("real, citation kept", kept), ("real, citation removed", removed), ("reworded cases", reworded)):
        n, ok, ways = rules(items)
        print(f"  {label:<26} matched {n} / {len(items)}  correct {ok}  wrong {n - ok}  ({ways})")
    wrongly = sum(i["output"]["stage"] == "rules" and i["status"] == "matched" for i in none)
    print(f"  {'no-article cases':<26} wrongly matched {wrongly} / {len(none)} (the rules never say 'no article')")

    if "--model" in sys.argv:
        model_report(real, kept, removed, reworded, none)


def model_report(real: list, kept: list, removed: list, reworded: list, none: list) -> None:
    every = kept + removed + reworded + none
    used = [i for i in every if i["output"]["ai"] == "used"]
    tokens = Counter()
    for i in used:
        a = i["output"]["audit"]
        tokens.update(input=a["input_tokens"], output=a["output_tokens"], read=a["cache_read_tokens"], write=a["cache_write_tokens"])
    price_in, price_out, price_read = PRICES.get(settings.LLM_MODEL, (0, 0, 0))
    cost = (tokens["input"] * price_in + tokens["write"] * price_in * 1.25 + tokens["read"] * price_read
            + tokens["output"] * price_out) / 1e6
    latency = sorted(i["output"]["audit"]["latency_ms"] for i in used)
    gaps = [i for i in none if i["status"] == "gap"]

    print(f"\nModel stage: {settings.LLM_MODEL} ({len(used)} cases the rules were not sure of)")
    print(f"  errors                           {sum(bool(i['error']) for i in every)}")
    print(f"  real, citation kept              correct {sum(map(right, kept))} / {len(kept)}")
    print(f"  real, citation removed           correct {sum(map(right, removed))} / {len(removed)}")
    print(f"  reworded cases                   correct {sum(map(right, reworded))} / {len(reworded)}")
    print(f"  no-article cases                 flagged as a gap {len(gaps)} / {len(none)}   "
          f"wrongly matched {sum(i['status'] == 'matched' for i in none)}   unsure {sum(i['status'] == 'uncertain' for i in none)}")
    print(f"  tokens in / out                  {tokens['input']} / {tokens['output']}   cache read / write {tokens['read']} / {tokens['write']}")
    print(f"  estimated cost                   ${cost:.3f}  (${cost / max(len(used), 1):.4f} per case)")
    print(f"  latency, median                  {latency[len(latency) // 2] if latency else 0} ms")
    for i in every:
        if not right(i):
            print(f"  BAD {i['id']:<10} {i['kind']:<12} expected {i['expected']}, got {i['status']} {i['article'] or ''}  {i['reason']}")
    draft_report([i for i in none if i["status"] == "gap"])


EXPECTED_DRAFT = {"defect": "created", "request": "request", "out_of_scope": "outside_kb"}


def draft_report(gaps: list[dict]) -> None:
    """Draft an article for each gap, as the service does, and print every draft for a person to read."""
    from app.agents.knowledge_builder.drafting import check_draft, draft_article, fields_of, markdown, people_of
    from app.agents.knowledge_builder.matching import known_application

    results, texts = [], []
    for i in gaps:
        ticket, app = i["ticket"], known_application(i["ticket"].application)
        if app is None:
            results.append((i, "outside_kb", [], None))
            continue
        answer, audit, hidden = draft_article([(ticket, i["notes"])], app)
        if answer.kind != "known_issue":
            results.append((i, answer.kind, [], audit))
            continue
        fields = fields_of(answer)
        problems = check_draft(fields, f"{ticket.summary}\n{ticket.description}\n{i['notes']}", [*hidden, *people_of([ticket])])
        results.append((i, "rejected_by_checks" if problems else "created", problems, audit))
        texts.append(markdown(None, fields, [ticket.id]))

    used = [a for *_, a in results if a]
    cost_in = sum(a.input_tokens + a.cache_read_tokens + a.cache_write_tokens for a in used)
    print(f"\nDrafts for the {len(gaps)} gaps ({len(used)} model calls, {cost_in} input tokens)")
    print(f"  as expected                      {sum(outcome == EXPECTED_DRAFT[i['kind']] for i, outcome, _, _ in results)} / {len(results)}")
    for i, outcome, problems, _ in results:
        mark = "ok " if outcome == EXPECTED_DRAFT[i["kind"]] else "BAD"
        print(f"  {mark} {i['id']:<8} {i['kind']:<12} -> {outcome}{'  ' + '; '.join(problems) if problems else ''}")
    for text in texts:
        print("\n" + text)


if __name__ == "__main__":
    main()
