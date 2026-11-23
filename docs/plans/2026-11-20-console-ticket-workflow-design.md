# Console ticket workflow: design

**Date:** 2026-11-20
**Status:** agreed in brainstorming, ready for the Phase 1 plan
**Design canvas:** https://claude.ai/artifact/As1zg3Wnnm9pwHWy7HXCTy (Overview, My work, Ticket: full flow)

## 1. Goal

An engineer works a ticket from start to finish in the AMS Console. Jira is where the ticket comes from, and the
closure note is the only thing that goes back, when the engineer asks for it. Each agent step is visible on the
ticket page; the step the engineer must act on is always at the top.

## 2. Decisions

| # | Question | Decision |
|---|---|---|
| D1 | Release order | Phase 1 (frontend only) ships first, on today's workflow. Phase 2 and 3 follow. |
| D2 | When Closure Quality runs | In the console, as soon as the engineer confirms the fix worked. It no longer waits for the Jira issue to be resolved. |
| D3 | Lead review before close | Configurable: **Always / Only P1–P2 / Never**, default **Only P1–P2**. |
| D4 | Phase 1 step bar | Only the steps the console really tracks. Fixing and Lead review are added when they exist. |
| D5 | Phase 1 fix rating | Keep today's 1–5 star rating with a reason. "Did it work?" replaces it in Phase 2. |
| D6 | Jira while the fix is checked | Nothing is written to Jira. |
| D7 | After 3 failed fixes | The ticket is flagged **Needs the lead**: shown on the Overview and in the review queue. The engineer can still add notes. |
| D8 | **Writing back to Jira** | **Only when the engineer asks, and only the closure note.** No automatic writes: no agent summaries after each run, no priority or status changes, no SLA warning comments. See section 6. |
| D9 | Replies to the reporter (was Q1) | Allowed as **engineer-asked exceptions**: the Data Quality "missing details" draft and "Reply to caller" go to Jira only when the engineer presses the button. Nothing is posted on its own. |
| D10 | Incidents page (was Q2) | **Out of scope.** The major-incident stakeholder update keeps working as it does today. |
| D11 | Who reviews the Triage priority | **Auto-approve** when the agent raises the priority above what the reporter asked (e.g. reported P3, recommended P2) **and** the agent is confident. **A person reviews** everything else: the same priority, a lower one, no reported priority, or a recommendation the agent is not confident about. Auto-approvals are recorded as a review by `Triage agent (auto)`, so they show in "Who did what" and in the review report. See section 8. |

## 3. Where the console is today

| Area | Exists | Gap |
|---|---|---|
| Menu and top bar | Menu, Sync now, Reset demo, API docs, theme and role switches, attention data | Sticky layout, footer, alert bell, person chip |
| Overview and My work | Stat tiles, "What the agents did", Up next, storms and major incidents, counts by pipeline stage | Work statuses (Fixing, In review, Needs the lead, Closed); "My tasks"; "Closed by you this week" |
| Step bar | Agent runs with times, ratings, decided priority | Grouping, popovers, Now / Coming up / Done |
| Fix rating | Stars 1–5 with a reason (`POST /tickets/{id}/feedback`) | Worked / partly / wrong outcome |
| New fix from a note | Note saved (`PUT /tickets/{id}/guidance`); Resolution can run again | **Resolution does not read the note**, and the note is not in its fingerprint, so a re-run returns the same fix |
| Fix versions | Every agent run is kept | Showing earlier Resolution runs as v1, v2… |
| KB and runbook links | `GET /runbooks/{kb_id}`, copied Confluence pages | Side panel; "used in this fix" needs Resolution to name the sections it used (to check) |
| Closure note | Closure Quality check; `POST /closure/tickets/{id}/review` with `edited` + `final_text` | Runs only on tickets resolved in Jira; no hand-off to a lead |
| Updates | Replies, with a `post_to_jira` flag | Nothing for the screen; see section 6 for what still goes to Jira |
| Who did what | Times on runs, decisions, replies | One timeline |

## 4. Phases

### Phase 1: new screens on today's workflow (frontend only)

- **Shell** (`components/console/app-shell.tsx`, `app-sidebar.tsx`)
  - Left menu: sticky, full height; the item list scrolls, the footer stays (Jira sync line + Sync now, API docs,
    Reset demo).
  - Top bar: sticky with a line once the page scrolls; theme switch; alert bell with the attention count (replaces
    `attention-banner.tsx`); person chip with initials, name and role.
- **Ticket page** (`app/tickets/[id]/page.tsx`, building on the uncommitted edits in that file)
  - Step bar of real steps, grouped Intake / Agents / Close: Jira, Data Quality, Triage, Review by a person,
    Resolution, Closure Quality, Knowledge Builder, Back to Jira. Click (or Enter) opens a popover; Esc, click outside
    or the same step closes it. "Open the section" jumps to and unfolds the step's card. Current step has a red dot.
  - **Now** on top (the step to act on, full card), **Coming up**, **Done** (folded, with a count).
  - Suggested fix keeps today's stars. KB, runbook and similar-ticket links open a side panel.
  - Closure note can be edited, saved through the existing `edited` decision.
  - Updates: reply to the caller (goes to Jira when the engineer sends it, D9) or internal note (stays in the console).
  - Who did what: one timeline from runs, decisions and replies; last 5 plus "Show all".
- **Remove** "Post the summary to Jira" on the ticket page. **Keep** "Post the draft reply to Jira" and "Reply to
  caller" as engineer-asked actions (D9).
- Verify: `npm run build` in `frontend/`.

### Phase 2: the fix loop (small backend changes)

- **Resolution reads the note** (`services/resolution.py`, `agents/resolution/`): the note, the previous fix and the
  engineer's outcome go into the prompt; the note goes into the fingerprint so a new note allows a new run.
- **Fix outcome:** new endpoint to record worked / partly (note required) / wrong (note required) for a Resolution
  run; new pipeline status `fix_confirmed`. New numbered migration in `backend/db/scripts/`.
- **Versions and cap:** earlier Resolution runs show as Fix v1, v2…; after 3 "wrong" outcomes the ticket becomes
  **Needs the lead** (D7).
- **Closure Quality in the console** (D2): runs when the fix is confirmed; the closure note unlocks then.
- Verify: `./.venv/bin/pytest backend/tests/`, `./.venv/bin/ruff check backend/`, `npm run build`.

### Phase 3: review and close

- **Setting** "Lead review before close": Always / Only P1–P2 / Never (D3), on a Settings page, stored in the admin
  config (`03_create_admin_config.sql`).
- **Submit for review** when the setting requires it: the lead accepts, or sends it back with a comment.
- **Send the closure note to Jira:** an engineer action (or the lead's, after accepting) that posts the closure note
  and sets the final status. The Knowledge Builder runs after it.
- **Work statuses** for the Overview stage tiles and step bar: Fixing, In review, Needs the lead, Closed.
- **My tasks** worked out from the review queue, the closure queue and unrated fixes; **Closed by you this week**.

### Left out

Change records, "Same issue elsewhere", "On hold".

## 5. Ticket page states

| State | Now | Coming up | Done |
|---|---|---|---|
| New, agents running | Data Quality or Triage result | Later agents | Jira import |
| Priority to review | Triage, agree or change | Resolution, Closure, Knowledge | Jira, Data Quality |
| Fix suggested (P2: waiting for the outcome) | Suggested fix | Closure note (locked in Phase 2) | …, Review by a person |
| Fix confirmed (P2) | Closure note | Lead review (P3, if required), Knowledge | …, Resolution |
| In review (P3) | Lead review | Back to Jira | …, Closure Quality |
| Ready to close | Send the closure note to Jira | Knowledge | everything before |

## 6. Writing back to Jira (D8)

The console writes to Jira **only when an engineer asks, and only the closure note** (with the final status).

What changes:

| Today | After |
|---|---|
| `announce` / `announce_resolution` comment after agent runs | Off |
| `move_triaged` moves the issue's status | Off |
| `set_priority` when a reviewed priority is decided | Off: the decided priority stays in the console and goes back with the closure note |
| `SLA_AUTO_WARN` comments at each 25% of the SLA | Off |
| Ticket page "Post the summary to Jira" | Removed |
| Ticket page "Post the draft reply to Jira" | Kept, engineer-asked only (D9) |
| Ticket page "Reply to caller" | Kept, engineer-asked only (D9) |
| Incidents page stakeholder update | Unchanged, out of scope (D10) |
| — | New: **Send the closure note to Jira**, an engineer action at the end |

`JIRA_WRITE_BACK` stays as the master switch: when it is false, nothing is sent, the closure note included.

## 7. Open questions

- **Q1, Q2:** answered, now D9 and D10.
- **Q4 Triage confidence (D11):** answered, option **(a)**: low confidence = `leaned_high`, `ai == "failed"`, any `dropped_facts`, or the model (not the rules) set the priority.
- **Q3 "Used in this fix".** Does Resolution's output say which runbook sections it used? If not, the side panel
  shows the article without highlights until it does.

## 8. Auto-approving a raised priority (D11)

Today every recommendation waits for a person (`pipeline_status = triaged`), and the output already carries
`needs_review` (true for a lowered P1/P2, a large shift, a guess, or a kept reported priority).

**Rule** (in `services/triage/run.py`, after the recommendation is made):

```
raised    = recommended and reported and recommended < reported     # P1 is the highest
confident = not low_confidence(output)
if raised and confident:  record review(action="accepted", reviewer="Triage agent (auto)")  -> reviewed
else:                     stay triaged, waiting for a person
```

**Confidence: a gap.** Triage has no confidence score today. What exists: `leaned_high` (the rules guessed high),
`kept_reported`, `ai == "failed"` (no usable model answer), `dropped_facts` (facts the model could not quote), and
whether the rules or the model settled the priority. **Decided: (a)** (Q4).
- **(a)** count it as low confidence when any of these is true: `leaned_high`, `ai == "failed"`, `dropped_facts` not
  empty, or the model (not the rules) set the priority. No model change.
- **(b)** ask the model for a confidence (high / medium / low) in `TriageAssessment` and auto-approve only on high.
  Needs a prompt and schema change and a new prompt version.

**Where:** Phase 2 (backend). Needs tests for each case: raised + confident, raised + low confidence, same, lowered,
no reported priority, storm follower. A setting to switch auto-approval off goes with the Phase 3 review setting.

**Note:** with D8, auto-approving does not write the priority to Jira.

## 9. Done means

- Phase 1: the three screens match the canvas within the decisions above; nothing on them writes to Jira;
  `npm run build` passes.
- Phase 2: a note gives a different fix; outcomes are stored; the closure note unlocks on "worked" or "partly";
  3 failures flag the lead; backend tests and ruff pass.
- Phase 3: the review setting works for all three values; the closure note reaches Jira only from the engineer's
  (or lead's) action; the Overview shows the work statuses.
