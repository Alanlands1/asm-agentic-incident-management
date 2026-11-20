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
| 12 Check end to end | Next | | |

**Outside the plan, found while testing**
- `b03538c` backend fix: `decided` on `GET /tickets/{id}` took the newest review of any agent, so saving close notes
  hid the decided priority. Now Triage reviews only. Test added; 301 then 302 backend tests pass.
- `657a789` backend: `GET /tickets/{id}` also returns `closure_decision`, so the page knows a check is decided.
  (Planned for Phase 2, done early at the user's request.)
- Loading crash on the ticket page (lists built before the ticket loaded) fixed before `c0817f9`.
- On a closed ticket, unfinished cards are listed under "Needs a look" instead of "Coming up".

**Left behind by testing:** a close-notes decision on AMS-3 and an internal note on AMS-6 in the local database, both marked "TEST (Claude)".

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

---

## Not in Phase 1

"Did it work?", new suggestions from a note, fix versions, the closure-note lock, Closure Quality in the console,
lead review, sending the closure note, the backend write-back switches (Phase 2 and 3 of the design).
