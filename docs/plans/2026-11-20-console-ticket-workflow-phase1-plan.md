# Console ticket workflow: Phase 1 plan (frontend only)

**Design:** [`2026-11-20-console-ticket-workflow-design.md`](2026-11-20-console-ticket-workflow-design.md), decisions D1–D10
**Canvas:** https://claude.ai/artifact/As1zg3Wnnm9pwHWy7HXCTy
**Scope:** `frontend/` only. No backend, schema or API changes. Nothing on these screens writes to Jira unless an
engineer presses a button that says so (D8, D9).

**Rules for every task** (from `CLAUDE.md` and `frontend/frontend-guidelines.md`)
- Use the shadcn primitives in `src/components/ui/`; add new ones with `npx shadcn@latest add <name>`, never hand-roll
  buttons, dialogs, badges, inputs or tables.
- `@/` imports, match the file's existing style, surgical changes only.
- After each task: `npm run build` and `npm run lint` in `frontend/` pass with 0 errors.
- Commit only when the user asks; each task below is one commit when they do.


## Status (2026-11-20)

Branch `feature/console-workflow-p1`, from `dev` at `3460cc4`.

| Task | State | Commit | Notes |
|---|---|---|---|
| 0 Branch and baseline | Done | `c9dd26c`, `3460cc4` (on `dev`) | WIP committed first; lint baseline: 3 errors, 2 warnings in untouched files |
| 1 Primitives | Done | `3ae8727` | popover, collapsible; sheet skipped (would overwrite `button.tsx`), Dialog used instead |
| 2 Left menu | Done | `3ae8727` | Checked in Chrome: desktop, short window, phone menu. Reset demo shows for Admin only |
| 3 Top bar | Done | `3ae8727` | Sticky from md up only (wraps to 3 rows on a phone); bell replaces the banner |
| 4 Runbook side panel | Done | `c0817f9` | `RunbookButton` in its own file with `panel`; not yet seen open on a ticket with references |
| 5–8 Ticket page | Done | `c0817f9` | Checked on AMS-6 and AMS-3: step bar, popovers, Esc, Open the section, Now / Coming up / Done |
| 9 Close notes | Done | `b9e5898`, `657a789` | Saved live on AMS-3 (text marked "TEST (Claude)"); second save gets 409; saved notes show read-only |
| 10 Updates | Done | `5548cd1` | Internal note added live on AMS-6 (marked "TEST (Claude)"); Reply to caller greyed out with the reason while write-back is off. Sending a reply to Jira not tested (it would post to the real issue) |
| 11 Who did what | Done | `d7f57d0` | Checked against the API on AMS-6 (4 entries), AMS-3 (11, Show all) and AMS-1 (empty). No ticket has a rating yet, so a rating line was not seen live |
| 12 Check end to end | Checked, code review to do | | See "Task 12 results" below |
| 13 Live results | Done, not committed | | Added at the user's request; one small backend field. See Task 13 below |
| 14 Auto-approval, Resolution right away, animations | Done, not committed | | Added at the user's request; changes Triage's behaviour. See Task 14 below |
| 15 Fix loop and closure note | Done, not committed; Send not tried on the real Jira | | Pulled forward from design Phase 2 and 3 at the user's request. See Task 15 below |
| 16 Review only when lowered, card motion | Done, not committed | | Asked for on 2026-11-23. See Task 16 below |

**Outside the plan, found while testing**
- `b03538c` backend fix: `decided` on `GET /tickets/{id}` took the newest review of any agent, so saving close notes
  hid the decided priority. Now Triage reviews only. Test added; 301 then 302 backend tests pass.
- `657a789` backend: `GET /tickets/{id}` also returns `closure_decision`, so the page knows a check is decided.
  (Planned for Phase 2, done early at the user's request.)
- Loading crash on the ticket page (lists built before the ticket loaded) fixed before `c0817f9`.
- On a closed ticket, unfinished cards are listed under "Needs a look" instead of "Coming up".

**Task 12 results (2026-11-20)**
- Build passes; lint unchanged from the baseline (3 errors, 2 warnings in untouched files).
- One ticket per stage: pending and awaiting_info (AMS-11), triaged (AMS-6), reviewed (AMS-14), closed (AMS-3),
  historical (AMS-1). Now, step popovers (keyboard: Enter opens, Esc closes, focus returns), runbook side panel (opens
  460px on the right, Esc closes), sticky menu, top bar and right column, Who did what.
- Roles: Engineer, Lead and Admin on the ticket page; bell for Lead and Admin only.
- Widths: Chrome would not resize, so 1440px and 390px were checked in a same-origin iframe of that width. 390px: no
  sideways scroll, phone menu opens with its footer.
- Jira: `JIRA_WRITE_BACK` was on in `backend/.env`; switched off for the test, then set back to true. With it off, no
  write reached Jira on page loads or after a run (`POST /tickets/AMS-11/run-agents`). Before the switch, the backend's
  scheduled job posted a Resolution comment to the real AMS-14 issue; it is still there.
- Fixed: on a reviewed ticket whose Resolution had already run, the Now line still said Resolution would run on the
  next sync. Not seen live: after a demo reset no open reviewed ticket had a Resolution run.
- Found, not fixed (backend, outside Phase 1): the runbook panel says "could not be opened" for KB-ORD-006.
  Resolution cites articles from `data/confluence_copy/`, but `GET /runbooks/{id}` only reads `data/knowledge_base/`.
- Found, minor: on the phone menu the close button sits on the top edge, half cut off.
- Not checked: a rating line in Who did what (no ticket has a rating).

**Left behind by testing:** none in the local database (a demo reset at 18:53 cleared the "TEST (Claude)" close-notes decision on AMS-3 and internal note on AMS-6).
Task 13 testing then left AMS-11 **rejected** (a test note to the agents read as "not an incident"; the note is cleared)
with an internal note "TEST (Claude): live update check" in its Updates. Only a demo reset puts it back.
Task 14 testing: AMS-7 was agreed at P3 by "Alan Test" (a real lowered case), and Resolution found its fix (KB-PAY-001).

**For Phase 2:** comments do not record whether they were an internal note or sent to Jira, so older updates can't be labelled. Add a column when the backend work starts.

---

## Task 0: Branch and baseline

**Why:** `src/app/tickets/[id]/page.tsx` has uncommitted edits (tabs, layout) that this work builds on; `backend/`
has two more uncommitted files that are not part of it.

1. Ask the user whether to commit the current work on `dev` first. Do not discard or stash anything without asking.
2. Create a branch `feature/console-workflow-p1` from `dev` (a git worktree if the user prefers).
3. Baseline: `npm run build` and `npm run lint` in `frontend/`. Note any errors that already exist so they are not
   blamed on this work.

**Done when:** on the new branch, baseline recorded.

**Result (2026-11-20):** WIP committed on `dev` as `c9dd26c` (Jira summary crash fix + test, 3 passed, ruff clean)
and `3460cc4` (ticket page steps + tabs). Branch `feature/console-workflow-p1` created from `3460cc4`.
Baseline: `npm run build` passes. `npm run lint` has 3 errors and 2 warnings that already existed, none in files this
plan touches: `react-hooks/set-state-in-effect` in `app/tickets/page.tsx:87`, `hooks/use-dq-rules.ts:27`,
`hooks/use-dq-runs.ts:26`; unused vars in `components/dq/dq-breadcrumb-nav.tsx:18` and
`components/layout/agent-sidebar.tsx:9`. "Lint passes" in later tasks means no new problems.

## Task 1: Add the missing primitives

`src/components/ui/` has no popover, sheet or collapsible.

1. In `frontend/`: `npx shadcn@latest add popover sheet collapsible` (style `base-nova`, from `components.json`).
2. Do not edit the generated files beyond what the build needs.

**Done when:** the three files exist under `src/components/ui/`; build passes.

**Result:** `popover.tsx` and `collapsible.tsx` added. `sheet` was **not** added: the CLI wanted to overwrite the
customised `button.tsx`. The side panel (Task 4) uses the existing `Dialog` placed on the right, the same way
`app-shell.tsx` already builds the mobile menu. Build and lint pass.

## Task 2: Left menu: sticky, scrolls inside, footer stays

**Files:** `src/components/console/app-shell.tsx`, `src/components/console/app-sidebar.tsx`,
new `src/components/console/sidebar-footer.tsx`

1. `app-shell.tsx`: the desktop `<aside>` becomes `sticky top-[76px] h-[calc(100vh-92px)]` (below the sticky top bar
   from Task 3) instead of `top-4 max-h-[calc(100vh-2rem)]`; drop its `overflow-y-auto`.
2. `app-sidebar.tsx`: the nav fills its height (`h-full`). The groups wrapper is the only part that scrolls:
   `min-h-0 flex-1 overflow-y-auto overscroll-contain`, thin semi-white scrollbar (`[scrollbar-width:thin]` plus
   `[scrollbar-color:rgb(255_255_255/0.35)_transparent]`). The existing API docs link moves into the footer.
3. `sidebar-footer.tsx` (pinned under the groups, `shrink-0`, top border `border-sidebar-border`):
   - Jira line: "Jira · last sync HH:MM" from `jiraService.getSyncs(1)`; hidden if the call fails.
   - **Sync now**: `jiraService.syncNow()`, spinner while running, refreshes the line; disabled while running.
   - **API docs** link (moved from step 2).
   - **Reset demo**: reuse `ResetDemoButton`, with a small "Demo" badge (`Badge variant="outline"`).
   - Text 11–12px, icons 14px, buttons `size="xs"`, colours from the `sidebar-*` tokens.
4. Mobile (menu in the `Dialog`): same footer, no sticky.

**Done when:** on a 768px-tall window with all Admin items, the footer stays visible and only the items scroll;
the mobile menu still opens and closes; build passes.

## Task 3: Top bar: sticky, bell, person chip

**Files:** `app-shell.tsx`, new `src/components/console/attention-bell.tsx`, new
`src/components/console/person-chip.tsx`, `src/components/console/attention-banner.tsx` (removed)

1. Header: `sticky top-0 z-20 bg-background`, `py-3`; a bottom border and soft shadow appear once
   `window.scrollY > 4` (small `useScrolled` hook inside `app-shell.tsx`, passive scroll listener, cleaned up).
2. Right side, in order: `ThemeToggle` (existing), `AttentionBell`, `PersonChip`.
3. `AttentionBell`: icon button (`Button variant="secondary" size="icon"`, `aria-label` with the count and reason),
   red count badge from `useAttention()`; links to `/incidents`. Same rules as the banner it replaces: shown to admin
   and lead only, hidden when the count is 0 or on error. Tooltip text = the banner's sentence.
4. `PersonChip`: initials circle, name and role label from `ROLES` and `useViewAs()`; replaces the grey name span.
5. Remove `<AttentionBanner />` from `app-shell.tsx`; delete `attention-banner.tsx` once nothing imports it.

**Done when:** the bar stays on scroll with the line appearing; the bell count matches what the banner showed; the
role switch still works; build passes.

## Task 4: Runbook links open a side panel

**Files:** new `src/components/console/runbook-button.tsx`, `src/components/console/persona-overview.tsx`

1. Move `RunbookButton` out of `persona-overview.tsx` into its own file, unchanged in behaviour; import it back.
2. Add a `panel` option: opens a `Dialog` placed as a right-hand panel (full height, max-w ~460px) with the runbook text, its title and an
   **Open in Confluence** link when the runbook has a URL. Esc, the close button and the overlay close it.
3. Highlights for "used in this fix" are **not** in Phase 1 (design Q3).

**Done when:** the Overview's runbook buttons work as before; a `panel` button opens the side sheet; build passes.

## Task 5: Step model for the ticket page

**File:** `src/app/tickets/[id]/page.tsx` (new helper near the top, or `src/components/console/ticket-steps.ts` if it
grows past ~80 lines)

1. A pure function `ticketSteps(ticket, ratingOf)` returning 8 steps in 3 groups (D4, real steps only):
   - **Intake:** Jira (done once imported), Data Quality, Triage, Review by a person
   - **Agents:** Resolution, Closure Quality
   - **Close:** Knowledge Builder, Back to Jira (done when the ticket is closed in the source)
2. Each step: `key`, `name`, `state` (`done` | `now` | `attention` | `waiting`), one-line `summary`, popover
   `headline` and `lines`, optional `stars`, `sectionId`. States reuse the existing `DQ_STEP`, `LATER_STEP`,
   `pipeline_status` and `CAN_RUN` logic already in the file; do not change those tables.
3. **Now** = the first step that is `attention`, or the first `waiting` step a person can act on; at most one.

**Done when:** the function compiles and covers every `pipeline_status` value in `STAGES` plus `historical`.

## Task 6: Step bar with popovers

**File:** `src/app/tickets/[id]/page.tsx` (replaces the `<ol>` of `Step`s in "Where the agents are")

1. Three groups side by side, a divider between them, each with a mono label and progress ("✓ done" or "n/m").
2. Each step is a `PopoverTrigger` button: 22px circle (✓, ⚠, number or spinner while running), name, and only for
   **Now** a second line in the primary colour. A red dot on the Now step's circle.
3. Popover content: step name and agent, state badge, headline, two lines, stars if rated, and
   **Open the section** (scrolls to `sectionId`, opens it if folded). Click to open, Esc or outside click to close,
   one at a time (Popover default behaviour). No hover opening.
4. Keep the existing **Run / Run again** buttons: inside the popover for that agent's step, with the same
   `disabled` and `title` rules as today.
5. Remove **Post the summary to Jira** from this card (D8).

**Done when:** keyboard only: Tab to a step, Enter opens, Esc closes and focus returns; Run again still runs the
agent; build passes.

## Task 7: Now, Coming up, Done

**File:** `src/app/tickets/[id]/page.tsx`

1. Replace the "What to do next" strip and the agent-results `Tabs` with three areas under the step bar:
   - **Now:** a "Now" badge, the agent's name and the `NEXT` sentence, then that step's section card, open.
   - **Coming up:** the later steps' section cards, folded to one line each.
   - **Done (n):** one `Collapsible`, folded by default; inside, the finished steps' cards, newest first, each
     folded to one line with a ✓.
2. When the Now step changes after a run, scroll it into view (respect `prefers-reduced-motion`).
3. The right column (Details) stays; it becomes `lg:sticky lg:top-[76px]`.

**Done when:** for each stage in the design's section 5 table, the right step is in Now; build passes.

## Task 8: One card per step

**File:** `src/app/tickets/[id]/page.tsx`

Each card is a `Card` with a one-line header (state dot, title, one-line summary, agent badge, chevron) that folds
with `Collapsible`. Bodies reuse what the page already renders:
- **Data Quality:** verdict, flags, the existing `Run` details; the draft reply with **Post the draft reply to Jira**
  (kept, engineer-asked, D9).
- **Triage + Review by a person:** recommended vs reported vs decided priority, reason; `ReviewActions` while
  `triaged`.
- **Resolution:** the fix from the run output via `Run`; runbook ids as `RunbookButton` with `panel` (Task 4);
  `FeedbackStars` (D5, unchanged).
- **Closure Quality:** verdict and the checked notes (editing is Task 9).
- **Knowledge Builder:** verdict (matched / gap) or "Runs after Closure Quality".
- Earlier runs of an agent: a "Earlier checks (n)" list inside that agent's card, replacing the old tab.
- Description moves to the top of the page under the title.

**Done when:** everything the old tabs showed is still reachable; build passes.

## Task 9: Edit the closure note

**Files:** `src/services/pipeline-service.ts`, `src/app/tickets/[id]/page.tsx`

1. Add `pipelineService.closureReview(ticketId, { action, reviewer, final_text?, reason_code?, note? })` calling
   `POST /closure/tickets/{id}/review` (body shape from `backend/app/schemas/closure.py`, `ClosureReviewCreate`).
2. In the Closure Quality card: a `Textarea` prefilled with the checked notes, **Save my version** (`edited`,
   `final_text`), **Accept as is** (`accepted`). A 409 shows "Already decided for this check".
3. Text above the box: "Goes to Jira only when you send the closure note" (sending is Phase 3).

**Done when:** saving shows the decision; a second save on the same check shows the 409 message; build passes.

## Task 10: Updates: reply or internal note

**Files:** `src/services/pipeline-service.ts`, `src/app/tickets/[id]/page.tsx`

1. Add `pipelineService.addComment(ticketId, author, body, postToJira)` calling `POST /tickets/{id}/comments`;
   `replyInJira` becomes a call to it with `true`.
2. The Replies card becomes **Updates**: the list as today, then a two-button toggle **Reply to caller** /
   **Internal note**, a `Textarea` and **Send**. Reply → `postToJira: true` (only when `JIRA_WRITE_BACK` is on; else
   the button says so and is disabled). Internal → `false`. The label under the toggle says who will see it.

**Done when:** an internal note appears in the list and not in Jira; a reply is posted only after pressing Send.

## Task 11: Who did what

**File:** `src/app/tickets/[id]/page.tsx` (right column, under Details)

1. One list, newest first, from `agent_runs` (agent, verdict, `created_at`), `feedback` (who rated, stars,
   `created_at`) and `comments` (author, `created_at`). The decided priority goes in by its `created_at`
   (the API always sent it; the frontend type now has it too).
2. Last 5, then **Show all (n)**.

**Done when:** the list matches the ticket's data; build passes.

## Task 12: Check it end to end

1. `npm run build` and `npm run lint` in `frontend/`.
2. With the backend running, open one ticket per stage (pending, awaiting_info, triaged, reviewed, closed) as Admin,
   Lead and Engineer; check Now, the popovers, the side panel and the sticky menu and top bar, at 1440px and 390px.
3. Check nothing writes to Jira on page load or after a run (watch the backend log for Jira calls).
4. Ask for a code review (`/code-review`), then report what was checked and what was not.


## Task 13: Live results while agents run

**Why:** asked for after Task 12. A result only showed after a refresh unless the person pressed Run on that page, and
the only sign of a run was the spinner on the step's circle.

**Files:** `backend/app/schemas/ticket.py`, `backend/app/api/v1/endpoints/tickets.py`, `backend/tests/test_tickets.py`,
`frontend/src/types/pipeline.ts`, `frontend/src/app/tickets/[id]/page.tsx`

1. Backend: `GET /tickets/{id}` returns `agents_running`, true while the agents' pass after a Jira sync holds
   `jira.agents_lock`. Test added.
2. The ticket page reads the ticket again while the tab is visible: every 3 s while an agent runs (own run or
   `agents_running`), else every 30 s. A failed read keeps what is shown.
3. Under the Now line, while agents work: a spinner and "Data Quality is checking this ticket…" for a run started
   here, or "The agents are working through the latest Jira sync. This page updates by itself."
4. Run buttons and the agents' note wait while agents work (title says why). The page does not scroll to a new Now
   step while someone is typing.

**Result:** 303 backend tests pass, ruff unchanged in the touched files, build passes, lint unchanged. Checked on
AMS-11: a note added through the API showed in Updates and Who did what without a reload; the status line showed during
a run and the result appeared without a reload. The background-sync line was not seen live (no new Jira tickets to
start a pass); the backend test covers the flag.


## Task 14: Auto-approval, Resolution right away, animations

**Why:** asked for after Task 13. A person should only have to approve a priority Triage lowered; after a decision the
next agent should start at once and show its result live, with the cards moving in rather than swapping.

**Decisions (user, 2026-11-20):** auto-approve when Triage's priority is the same as the reporter's or more urgent; a
person reviews when it is lower or the reporter gave none; an auto-approval does not change the Jira priority (console
only); Resolution starts right away after any decision.

**Backend:** `services/triage/run.py` records an accepted review by `AMS agents (auto)` and moves the ticket to
`reviewed`, else `triaged` as before (storm followers too). The agreement report leaves auto-approvals out.
`jira.start_resolution()` runs Resolution (and its Jira comment, if write-back is on) in the background after a person's
review, after a console run that ended auto-approved, and at the end of every agents pass. `agents_running` is also true
while Resolution runs. Tests: two new, three updated to the new rule (they expected `triaged` for raised priorities);
tests never start background Resolution (`conftest.py`).

**Frontend:** while an agent works on the ticket, the Now card becomes a pulsing placeholder with "Resolution is looking
for the fix in the runbooks…" (or the agent's own line), and its step in the bar spins. The step that just got a result
stays open under Now as **Just finished**. The Now block and Just finished slide in; new Who did what rows fade in; step
circles change colour smoothly. All motion is off under `prefers-reduced-motion`.

**Result:** 305 backend tests pass; ruff unchanged in the touched files; build passes; lint unchanged. Checked live on
AMS-7 (write-back off for the backend process): Agree with P3, then the placeholder and Resolution line, Triage under
Just finished, and 11 s later the fix under Just finished with Now on Closure Quality, all without a reload; nothing
written to Jira. Not seen live: an auto-approval (tickets triaged before this change keep waiting; a demo reset and
sync would show it). AMS-14 (reporter P2, Triage P2) is one of those.

---

## Task 15: Fix loop and closure note

**Why:** asked for after Task 14, to match the canvas's ticket flow. **Decisions (user, 2026-11-20):** the fix loop
and the closure note now (not lead review); Send posts the closure note on the Jira issue and moves it to done.

**Backend:**
- Two stages, no migration (`pipeline_status` is a string): `fix_confirmed` (closure note open) and `needs_lead`.
- `services/fix.py`: the engineer's answer is a review of the Resolution run (agent `resolution`; action `worked`,
  `partly` or `wrong`, with a note for the last two). The latest answer on a run counts.
  - Worked or partly drafts the closure note into `resolution_notes` (cause, steps, what changed,
    `[engineer to add: check]`) and runs Closure Quality.
  - Wrong runs Resolution again for that ticket. Three wrong answers mean Needs the lead.
- Resolution reads the fixes that did not work and what happened (in the case text, so in the fingerprint). Rule R4 is in
  `resolution_react@2`; the version change re-resolves every reviewed ticket once on the next agents pass.
- Endpoints:
  - `POST /tickets/{id}/fix-outcome`
  - `PUT /tickets/{id}/closure-note`: saves and checks again.
  - `POST /tickets/{id}/close`: posts the note, moves the issue to a done status (it checks for the move first), closes the
    ticket, and keeps a copy under Updates. It is refused while `[engineer to add: …]` gaps remain. `JIRA_WRITE_BACK` is
    still the master switch.
  - The closure check endpoint also takes `fix_confirmed` tickets.
- Other changes:
  - A Jira sync keeps the console's note while the issue is open.
  - The SLA, dashboard and personas lists count the new stages as open.
  - Closure Quality ignores `[engineer to add: …]` marks, so a gap counts as missing.
- 12 new tests; 317 pass.

**Frontend:** the Suggested fix card asks "Did it work?":
- Yes, Partly (what changed), or No (what happened, then "Get a new suggestion", with the count left before the lead).
- With no runbook match, the card offers "I fixed it another way".
- It shows Fix vN, earlier fixes with the engineer's answers, Change answer, and the Needs-the-lead alert.

The Close notes card, once the fix is confirmed:
- What the note still needs, and the note to edit.
- Save and check again, and Use the agent's draft.
- Send the closure note to Jira. It is disabled until the note is saved, has no gaps, and write-back is on, and says why.

Step bar and Now follow it. Overview stage words cover the two new stages.

**Checked live on AMS-14** (write-back off):
- No, with a note: the placeholder showed while Resolution looked again. Fix v2 said no runbook covers it rather than
  repeat the rollback.
- I fixed it another way: Now moved to the closure note, drafted with gaps. Before the gap fix, Closure Quality called
  that draft good; fixed.
- Filled in, saved: 6 of 6, Ready to send.
- Send itself is tested with a fake Jira only.

## Not in Phase 1

Lead review and its setting, the backend write-back switches (Phase 3 of the design). Task 15 brought the rest of
Phase 2 and 3 forward.

---

## Task 16: Review only when lowered, card motion

**Why:** asked for on 2026-11-23. **Decisions (user):** a person reviews only a priority Triage lowered; a ticket the
reporter gave no priority is approved by the agents too (this changes Task 14's rule). The ticket page always moves,
even when the computer asks for reduced motion (this laptop has Windows animation effects off, so nothing moved before).

**Backend:** `services/triage/run.py` `_triaged()` waits for a person only when the priority went down. Tests updated:
`test_triage.py` (MBX-00006, no reported priority, is now `reviewed`) and `test_triage_review.py` (rule, and the queue
limit check, since the fixture now has one waiting ticket). 317 pass; ruff clean in the touched files.

**Frontend (`tickets/[id]/page.tsx`):** the Review by a person step says "Not needed" for an agents' approval, why a
person is needed when Triage lowered it, and "Only if lowered" before Triage. Clicking a card opens it and scrolls to it;
"Open the section" and a new Now step scroll the same way, eased by hand (`glideTo`), because Chrome makes
`behavior: "smooth"` instant under reduced motion. Cards glide to their new place when they move (Now, Just finished,
Coming up, Done) or when a card above opens; a card that appears fades up. `globals.css` exempts `.keep-motion` (the
ticket page) from the reduced-motion rule. Checked in Chrome on AMS-14 with reduced motion on.

Not seen live: a ticket moving through the agents with the new rule (tickets already waiting keep waiting until triaged again).


**Knowledge Builder after Send (2026-11-23):** it ran only at the end of the agents' pass after a Jira sync, so a ticket
closed with Send waited for the next sync. `POST /tickets/{id}/close` now calls `jira.start_knowledge()`, which runs
Knowledge Builder in the background under the agents' lock (in its own thread and engine, like the pass). The ticket page
shows "Knowledge Builder is learning from the close notes…" meanwhile, when the notes passed Closure Quality. Test:
`test_send_posts_the_closure_note_and_closes_the_issue` checks it starts; `conftest.py` stubs it. Checked on AMS-14
(closed, notes good, no case yet): `learn_now()` matched it to KB-ORD-006. Send itself not retried (it writes to Jira).
