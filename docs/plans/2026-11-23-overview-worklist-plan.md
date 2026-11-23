# Overview and My worklist: plan

**Date:** 2026-11-23 · **Status:** done (user's choices: cards, assigning later, keep the Soon placeholders)
**Sources:** `meetings/2026-11-19-takeaways.md` (19 Nov review), the design canvas
(https://claude.ai/artifact/As1zg3Wnnm9pwHWy7HXCTy, boards Overview and My work), the console as it runs today.

## Where the pages are today

Both pages are one component (`components/console/persona-overview.tsx`) with small differences, so today they look
almost the same: greeting, SLA line, priority tiles (P1, P2, P3–P5, Not triaged), a "Work on this now" card, three
count tiles, an "Up next" table with an application filter, "Waiting on the reporter", and activity. The Lead also sees
"What the agents did" (Data Quality and Triage only) and Workload by engineer.

What is wrong against the notes and the canvas:

| # | Today | Should be |
|---|---|---|
| G1 | Next steps say "Priority decided. Work it in Jira", "Agree… then work the ticket in Jira" | The work happens in the console (19 Nov ask 1): open the ticket, try the fix, write the note, submit it |
| G2 | Tiles count priorities | Tiles count **work statuses**: Needs details, Triage, Fixing, In review, Closed today (canvas) |
| G3 | No stage on a ticket row | Each row shows its stage as a pill |
| G4 | "What the agents did": 2 agents, Lead only | All five agents: Data Quality, Triage, Resolution, Closure Quality, Knowledge Builder |
| G5 | Application filter only | Search, application and **age** (< 1 day, 1–7 days, > 7 days) |
| G6 | Overview and My worklist are the same page | Overview = the whole queue (all open tickets). My worklist = my tickets, my tasks, what I closed |
| G7 | No "My tasks" | Tasks from the agents and the lead: answer a fix, finish or submit a note, answer a lead's comment, rate a fix |
| G8 | No "Closed by you this week" | The tickets I closed, each with "Note sent" / "KB updated" |
| G9 | Activity says "The agents commented on … in Jira" and lists the lead's review steps as **"rejected the recommendation"** (bug) | The new steps by name (fix worked, submitted, approved, sent back, closed); nothing about Jira comments now that the agents don't write there |
| G10 | Data Quality line "has already asked the reporters in Jira" (canvas) | Since D8 the agent only **drafts** the question; the engineer sends it. Say that |

## Proposed: Phase 4 (this week, before the demo)

### Overview (`/team`, every role)
1. **Status tiles** (G2): All open · Needs details · Triage · Fixing · Closure note · In review · Closed today. Pressing a
   tile filters the list. Priority counts move into the list's section headers ("P1 and P2 · 5").
2. **What the agents did today** (G4), for every role: five agents, one number and one line each (from today's agent
   runs and reviews). Backend: extend the dashboard summary with Resolution, Closure Quality and Knowledge Builder.
3. **Filter row** (G5): search, application, age.
4. **Data Quality banner** (G10): "N tickets need details. Data Quality drafted the questions." → Show them.
5. **Ticket cards** grouped "P1 and P2" / "P3 to P5" (canvas): id, priority, two-line summary, application, stage
   pill, age and engineer. The table moves to My worklist.
6. **Recent activity** (G9): fix the bug; name the new steps.

### My worklist (`/my-tickets`)
1. **Work on this now** (canvas): the agents' chain as chips (Data Quality passed · Triage P2 · Resolution fix used ·
   Closure Quality 6/6) and one sentence for the next action ("Closure Quality passed your note. Submit it to the lead.").
2. **My status tiles**: Needs details · Triage · Fixing · In review.
3. **Up next** table with a **Stage** column (G3) and console next steps (G1).
4. **My tasks** (G7), worked out from the data, newest first, each a link into the ticket:
   priority to agree · fix to answer · closure note to finish or submit · sent back by the lead · approved, ready to
   send · unrated fix. For the Lead: closure notes to review.
5. **Closed by you this week** (G8): tickets closed with Send by this person, with "Note sent" and "KB updated" when
   Knowledge Builder matched or drafted from it.

### Backend
- Dashboard summary: today's counts for Resolution, Closure Quality, Knowledge Builder; tickets closed today.
- Persona endpoint: stage and age per ticket (if missing), my tasks, closed by me this week.
- Activity: lead review steps, fix answers and closes as their own kinds.

**Done when:** both pages match the canvas within the decisions above; no "in Jira" next step except assigning; tests,
ruff and `npm run build` pass; checked in Chrome as Engineer and Lead.

## Later phases (not this week)

| Item | Why later |
|---|---|
| Major incident banner with bridge on the Overview | Design D10: incidents stay on their own page |
| "On hold" status (vendor, change window) | Left out in the design; no field for it yet |
| Assign an engineer in the console | Engineers are assigned in Jira today; needs a people list and a write to Jira |
| Ask a question, Log analyzer, Problem records (menu items marked Soon) | 19 Nov notes: "later, beyond the three agents" |
| Status pills like "Processed External", age buckets past 7 days, 5-column card grid | Reference app's data; ours has none of these |
| Realistic demo tickets (19 Nov ask 3) | Separate task; changes the data, not the pages |
| Login with a role and PIN | No sign-in yet; the role switch stays for the demo |

## Questions

1. Overview tickets as **cards** (canvas) or keep the **table**?
2. Should assigning an engineer move into the console now (the last Jira jump), or stay in Jira?
3. Keep the menu's "Soon" items (Ask a question, Log analyzer, Problem records) visible as placeholders for the demo?

## Result (2026-11-23)

Built as planned, with these choices: Overview tickets as cards; assigning stays in Jira; the menu shows Ask a question,
Log analyzer and Problem records under Tools, marked Soon (not pages).
- Overview (`persona-overview.tsx`) is the same for every role: status tiles, the five agents' day, a Needs details
  banner, search, application and age filters, cards in P1–P2 / P3–P5 / Not triaged. The lead keeps Run agents and the
  workload table.
- My worklist (`my-worklist.tsx`): Work on this now with each agent's result in a row and the next action, my status
  tiles, Up next with a Stage column, My tasks (the Lead also gets closure notes to review), Closed by you this week.
- Shared parts in `persona-parts.tsx`. Backend: board progress fields, `/personas/today`, `/personas/closed`, Send
  records who closed, activity names each step (the "rejected the recommendation" bug).
- Checked in Chrome as Engineer and Lead at desktop width; 333 backend tests; `npm run build` passes. Phone width not
  checked (the window would not resize). Activity from before today's change still says "The agents commented … in
  Jira": those comments were really posted then.

