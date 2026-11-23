# Console ticket workflow: Phase 2 leftovers and Phase 3 plan

**Date:** 2026-11-23
**Design:** [`2026-11-20-console-ticket-workflow-design.md`](2026-11-20-console-ticket-workflow-design.md)
**Branch:** `feature/console-workflow-p1` (Phase 1 and most of Phase 2 are on it)
**Why now:** the 19 Nov review (`meetings/2026-11-19-takeaways.md`): the whole flow in the console, a workflow trail
(submitted for review, approved by the lead, closed), and nothing written to Jira but the closure note. Client demo
this week.

## Decisions (user, 2026-11-23)

| # | Decision |
|---|---|
| E1 | After the lead approves, the **engineer or the lead** sends the closure note. No new Incident Manager role. Trail: submitted by the engineer → approved by the lead → closed by whoever pressed Send. |
| E2 | Include two Phase 2 leftovers first: **stop automatic Jira writes** (design D8) and **Resolution reads the engineer's note**. |
| E3 | A person reviews a Triage priority **only when Triage lowered it** (Task 16; replaces design D11). |
| E4 | Lead review before close: **Always / Only P1–P2 / Never**, default **Only P1–P2** (design D3). |

## Status

| Task | State | Commit | Notes |
|---|---|---|---|
| 1 No automatic Jira writes | Done | see log | `JIRA_AGENT_WRITES` (off) gates every automatic write; Send sets the decided priority; 318 tests |
| 2 Resolution reads the note | Done (was already) | see log | `reporter_text()` already adds the note to the case and fingerprint; a test now proves it |
| 3 Lead review setting | Done | see log | `LEAD_REVIEW` (admin-editable), card on the Jira settings page; needs `ADMIN_API_KEY` in `frontend/.env.local` to save |
| 4 Submit, approve, send back (backend) | Done | see log | `services/lead_review.py`, two endpoints, Send and note edits guarded; 330 tests |
| 5 Lead review on the ticket page | Done | see log | Checked on MBX-00014 (P1, mailbox; text marked "TEST (Claude)"): submit, send back, resubmit, approve. Step list now in the bar order (Now was wrong); bar labels shortened to stay on one line |
| 6 Work statuses and the lead's queue | Done | see log | Stage names Fixing, Closure note with the lead, Approved · ready to send; review queue lists notes to review (Lead, Admin); stage counts leave closed tickets out (they counted AMS-6, AMS-14) |
| 7 Check end to end | Done | see log | 330 backend tests; ruff clean on new lines; `npm run build` passes; Engineer and Lead views, light and dark, on MBX-00014. Send to the real Jira not pressed |

---

## Task 1: No automatic Jira writes (design D8)

**Today:** with `JIRA_WRITE_BACK=true` the system comments and labels issues after every agent run (`announce`,
`announce_resolution`, `announce_closure`), moves triaged issues out of the backlog (`move_triaged`), sets the
reviewed priority (`set_priority` from a Triage review), answers `/ams` commands (`answer_commands`) and, with
`SLA_AUTO_WARN`, posts SLA warnings. Today's reset deleted 9 such comments.

**Change:**
1. New setting `JIRA_AGENT_WRITES: bool = False` in `core/config.py` (admin-editable): true brings back the old
   automatic writes, for whoever wants them. `JIRA_WRITE_BACK` stays the master switch.
2. Each automatic write returns without writing unless `JIRA_AGENT_WRITES` is on: the three `announce*`,
   `move_triaged`, `answer_commands`, `send_sla_warnings`, and the `set_priority` call after a Triage review.
3. Kept, engineer-asked only (D9): Post the draft reply, Reply to caller, Send the closure note.
4. Send the closure note also sets the decided priority on the issue when it differs from the reporter's (the decision
   goes back with the note, D8 table).

**Done when:** an agents pass with write-back on makes no Jira call; Send posts the note, sets the decided priority if
it changed, and moves the issue to done. Tests that cover the automatic writes switch the setting on; a new test checks
nothing is written with it off. pytest and ruff pass.

## Task 2: Resolution reads the engineer's note

**Today:** the note to the agents (`tickets.guidance`) is saved, but Resolution does not read it, so Run again returns
the same fix. Resolution already reads the fixes that did not work (`fix.tried`).

**Change:** `services/resolution.py` `_case()` adds the note to the case text ("Note from the engineer: …"), masked
like the rest, so it is in the prompt and in the fingerprint: a new note allows a new run; an unchanged one skips.

**Done when:** a test shows the case text carries the note and `input_changed` turns true when the note changes.

## Task 3: Lead review setting (D3)

**Change:** setting `LEAD_REVIEW: Literal["always", "p1_p2", "never"] = "p1_p2"`, admin-editable, shown with a short
explanation on the Jira settings page (Admin), saved through `PUT /admin/settings/LEAD_REVIEW`. One helper,
`needs_lead_review(ticket)`, decides from the setting and the decided priority (the review's final priority, else
Triage's).

**Done when:** each value gives the right answer for P1, P2, P3 and no priority (unit test); the page changes it live.

## Task 4: Submit, approve, send back (backend)

**Stages** (no migration, `pipeline_status` is a string): `in_review` (waiting for the lead) and `approved` (the lead
accepted; ready to send).

**Flow:**
- `fix_confirmed` → engineer **Submit for review** → `in_review`. Only when the note has no `[engineer to add: …]`
  gaps. Refused (409) when the setting does not require a review for this ticket.
- `in_review` → lead **Approve** → `approved`; or **Send back** with a comment (required) → `fix_confirmed`, the
  comment shown on the ticket.
- **Send the closure note:** from `fix_confirmed` when no review is needed, else only from `approved`.
- Saving the closure note after approval sends it back to `fix_confirmed` (the lead approved a different text).

**Storage:** a `Review` row per step, agent `lead_review`, action `submitted` / `approved` / `sent_back`, with the
reviewer and the comment. "Who did what" and the ticket detail read them.

**Endpoints:** `POST /tickets/{id}/submit-review` `{reviewer}`; `POST /tickets/{id}/lead-review`
`{action: approved | sent_back, reviewer, note}`. The detail carries `lead_review_required` and the review rows.

**Done when:** tests for each transition and each refusal; Send refused before approval when a review is required.

## Task 5: Lead review on the ticket page

- Step bar: **Lead review** in the Close group, between Closure Quality and Knowledge Builder; "Not needed" (done)
  when the setting does not ask for it.
- Closure note card: **Submit for review** instead of Send when a review is required; read-only while in review.
- Now = **Lead review** while `in_review`: the Lead sees Approve and Send back (comment box); the Engineer sees who it
  waits for. After approval Now = **Send the closure note**, with who approved it.
- A sent-back comment shows above the closure note until it is submitted again.
- Who did what: submitted for review, approved, sent back (with the comment), closed by.

**Done when:** in Chrome, a P2 ticket goes engineer → submit → lead sends back → engineer edits and submits → lead
approves → Send (Send itself only with the user's OK, it writes to the real Jira). `npm run build` passes.

## Task 6: Work statuses and the lead's queue

- Overview stage tiles and the dashboard `STAGES`: Fixing (`reviewed`), Closure note (`fix_confirmed`), In review,
  Ready to send (`approved`), Needs the lead, Closed.
- Review queue (`/review`): for the Lead, a section "Waiting for your review" listing `in_review` tickets, next to the
  priorities to review.

**Done when:** the tiles count the new stages; the lead finds an `in_review` ticket from the menu in one click.

## Task 7: Check end to end

One ticket per stage as Engineer and Lead; light and dark; phone width. pytest, ruff (touched files), `npm run build`.
Update this table and the design's status.

## Left for later

My tasks and "Closed by you this week" (design Phase 3, last bullet); realistic demo tickets (19 Nov ask 3); the story
deck (ask 4).
