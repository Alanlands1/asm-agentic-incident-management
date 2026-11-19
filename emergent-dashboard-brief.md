# AMS Agents: dashboard brief

Build a dashboard called **AMS Agents**: the overview page of an incident management console for an application support team.

Tickets come from Jira. Two AI agents work on every ticket:

- **Data Quality agent**: checks that the ticket has enough detail to act on.
- **Triage agent**: recommends a priority (P1 to P5).

People review the recommendation and then work the ticket in Jira.

## Layout

### Left sidebar

- App name "AMS Agents".
- Links: Overview, My worklist, Incidents.
- A "Tickets" group: Review queue (with a count badge) and All tickets.
- At the bottom: the user's name, a "Viewing as" selector (Lead / Engineer / Admin), an API docs link and a dark mode switch.

### Top banner

A red banner across the top when something needs a person now, for example "3 need attention: 3 P1/P2s without a first message", with a link "Open incidents".

## Main page, top to bottom

1. **Greeting** with the user's name, one status line, and a "Run agents" button (lead only).
2. **Highlight card** for the most urgent ticket that is ready to work: priority chip, title, ticket ID, application, short description, time left on its SLA, and a button to open its runbook.
3. **Three number tiles**: "Ready to work", "Waiting for a priority review", "Waiting on the reporter". Each has a number and one line of detail.
4. **"What the agents did" strip**: how many tickets Data Quality checked today (complete / need details) and how many Triage gave a priority today.
5. **"Up next · 14" table** with a search box and an application filter, 5 rows per page. Columns:

   | Column | Content |
   |---|---|
   | Priority | Coloured chip, P1 to P5 |
   | Ticket | Title, ticket ID, application |
   | Engineer | Who it is assigned to |
   | What Triage found | One sentence, and whether the priority was raised or is the same as reported |
   | Runbook | A link like KB-ORD-001 that opens the runbook in a dialog |
   | SLA | Time left, a progress bar, "On track · 32% of SLA used · due today 20:35" |
   | Next step | A short instruction and a button: "Review" or "Assign" |

6. **"Waiting on the reporter" list**: tickets with missing details, what is missing, and whether a reply to the reporter is drafted.
7. **"Workload by engineer" table**: Engineer, Open, P1 and P2, SLA breached, Waiting for review.
8. **"Recent activity · today" card**: a short timeline of what the agents and people did.

## Runbook dialog

Opens over the page from a runbook link. Shows the runbook title, its ID and application, then formatted text: Symptoms (bullets), Root cause (paragraph), Resolution steps (numbered, with commands shown as code) and Escalation.

## Personas

- **Lead**: sees every ticket and all sections above.
- **Engineer**: sees the same page with only their own tickets, without the lead-only parts (Engineer column, Workload table, Run agents button).

## Style

- Calm and light: warm off-white background, white cards with thin borders.
- Dark red accent for P1 and for the active sidebar item; outlined chips for lower priorities.
- Plain sans-serif type, generous spacing.
- Dark mode supported.

## Sample data

Use realistic sample data: about 18 open tickets across applications such as BillingEngine, OrderHub, PayrollPro, SalesConnect CRM, InsightBI and EmployeePortal.
