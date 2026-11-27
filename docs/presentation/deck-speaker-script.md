# AMS Console: speaker script

Ten slides, about 8 minutes. Read at a calm pace.

- [pause] means stop for two seconds. Let it land.
- [click] means press the arrow once and wait for the slide to change.
- Other lines in [brackets] are what to do, not what to say.
- Words in **bold** get a little extra weight.

---

**Slide 1: Opening**

[do not look at the slide yet]

We asked one of our AMS support engineers a simple question.

Where does your time actually go on an incident?

[pause]

The answer was not "fixing it".

It was everything **before** the fix, and everything **after** it.

[pause]

Take two tickets from the same morning.

The first is marked **Priority 1**. The problem is a spelling mistake on the claim form page.

The second is marked **Medium**. It says: insurance payment did not go through for deal 11111.

[pause]

Nobody did anything wrong. The requester picked a priority, because the form asks for one.

So the engineer has three questions before any real work starts.

Is this ticket complete?

Is the priority right?

Has someone solved this before?

[pause, then turn to the slide]

That is what the AMS Console is for.

Every ticket reaches the engineer checked, prioritised, and with a suggested fix.

**The engineer still decides.**

---

**Slide 2: Six gaps**

[click once for each gap as you name it]

We see the same six gaps on every incident.

One. Tickets arrive incomplete, so the work waits.

Two. The priority is the requester's guess.

Three. Finding a free engineer takes a round of messages.

Four. The knowledge is scattered across runbooks, old tickets, emails and people.

Five. One outage arrives as twenty tickets, and deadlines slip unseen.

Six. Closure notes are written by hand, and often late.

[pause]

None of these is a hard problem on its own.

They all happen to the **same ticket**.

---

**Slide 3: The knowledge exists**

[point to the left side: the three sources]

Look at the picture on the left. This is today.

The request can come from **three different places**. Jira, ServiceNow, or the support mailbox.

So the engineer has to keep switching between all three.

[pause]

[point to the lower part of the left side]

And once the ticket is ready to work on, the searching starts.

Past tickets. The runbooks. The Confluence pages. And the people who solved it before.

The engineer goes through each one, **by hand**.

[pause]

[click, point to the right side]

Now add the console.

Jira, ServiceNow, the mailbox, or any other source: they all come into **one place**.

The console goes through every runbook, every past ticket, and every published knowledge article.

[pause]

So the engineer no longer does the searching.

The console brings a **suggested fix**, with the source of each step beside it.

The engineer checks the facts, and **confirms**.

---

**Slide 4: Five agents**

[point to each agent as you name it]

The console is five agents. Each has one job.

**Data Quality** checks the ticket before work starts.

**Triage** sets the priority from the business rulebook.

**Resolution** suggests a fix, with its sources.

**Closure Quality** drafts the closure note and marks the gaps.

**Knowledge Builder** turns a good fix into an article.

[pause, point to the row below]

Around them: the Lead desk assigns the ticket. Incidents and SLA groups twenty tickets into one. And the assistant answers questions on the ticket.

---

**Slide 5: One ticket, start to finish**

[go slowly here. One click per step. Wait for each step to appear before you speak.]

Let me walk you through how the console works, with one ticket.

[point to the top row]

At the top, you can see where tickets come from. The support mailbox, Jira, and ServiceNow.

For this example, I will take the mailbox.

[click]

An email arrives. It says: **insurance payment failed**.

[pause]

[click]

First, the **Data Quality** agent. It checks whether the ticket has everything we need.

This one has the deal number. So the ticket is complete.

If the deal number was missing, it would stop here, and draft an email asking for it.

[click]

Next, **Triage**.

The requester asked for Medium.

The agent checks the rulebook. An insurance payment is involved, so the priority should be **higher**.

[pause]

It raises the priority, and the SLA clock starts.

[click]

Then, **Resolution**.

The agent goes through the runbooks, the Confluence pages, and the past tickets.

It finds the fix for the engineer.

[click]

Now the ticket is assigned to an engineer.

[pause]

Look at what is already on the screen when they open it.

Data quality: checked. Priority: set. Suggested fix: ready.

The engineer reads the fix, applies it, and confirms that it worked.

[click]

Then, **Closure Quality**. It drafts the closure note.

The engineer only has to complete it and send it.

[click]

Last, **Knowledge Builder**.

If this was a new problem, with no fix on record, it writes the fix up as a draft article.

[pause]

And that is the loop. The article goes back into Resolution.

So the next time this problem comes in, the answer is **already there**.

[point to the strip at the bottom]

Around the pipeline, on every ticket: personal data is masked, the SLA time left is in view, and there is feedback and reports.

---

**Slide 6: Twelve capabilities**

[do not read the cards. Point to each column as you reach it.]

You just saw the flow. Now let me show you what makes it work.

There are twelve capabilities. They sit in three groups.

Accurate answers. Faster handling. And control.

[pause]

[point to the first column]

First, **accurate answers**. How does the console find the right fix?

The agent does not search once. It searches, reads what it found, and searches again. Up to five times.

It searches by **meaning**, and by **keyword**. So it finds the runbook even when the wording is different.

It also looks at similar tickets we have already closed, with the names masked.

And there is a quote check. If the model says something about a ticket, it must show the **exact words** from the ticket. No quote, and we do not count it.

[pause]

[point to the second column]

Second, **faster handling**. Where do we save the waiting?

Rules go first. They settle what is certain. The model is asked only once, for what is left.

If twenty tickets come in for the same problem, the console groups them into **one incident**.

Every ticket shows its SLA time left, with a warning at the halfway mark.

And the ticket is assigned automatically, by shift, leave, and how much each engineer already has.

[pause]

[point to the third column]

Third, **control**. Who is in charge of all this?

The team is. The team writes the rules, and can see every run, and **undo** it.

Personal data is masked before any model sees it. Names, emails, phone numbers, IDs.

Every model call is traced. Every settings change is recorded, with who and when.

And there are reports, by application, by agent and by engineer.

[pause]

So: the right fix, less waiting, and the team stays in control.

---

**Slide 7: What we have measured**

[point to the left panel]

At this point, a fair question is: does it actually work?

So we tested it, in two ways.

[pause]

First, we **scored the agents**.

We gave each agent tickets where we already know the right answer. Then we checked what it said.

All five agents are scored. **190 cases. All 190 passed.**

[pause]

Take Resolution as an example.

We gave it ten closed tickets. For all ten, it pointed to the **right runbook article**.

And we checked that its answer came from what it had read, not from guessing. It scored 0.93 out of 1.

[pause]

How did we score it? Each agent has its own scoring script, with an answer key our team wrote.

For Resolution we use **RAGAS**. It is a standard open-source method for rating this kind of search-and-answer system.

A second model acts as the judge. It reads the agent's answer, and what the agent had read, and checks that they match.

[pause]

[click, point to the middle panel]

Second, we tested **the build itself**.

There are **445** automated tests. All of them pass.

The backend tests run on **pytest**. There are 396 of them.

The browser tests run on **Playwright**. They click through the console the way a person would. There are 28.

The frontend tests run on **Vitest**. There are 21.

And our own script checks that no personal data leaks through.

[pause]

[click, point to the right panel]

Now, what is still open. I want to be just as clear about this.

The test cases are small, and our own team wrote them. The support lead still has to confirm them.

Resolution is scored on its first ten tickets. The full set is next.

The SLA targets are provisional.

And ServiceNow and the mailbox load from files today.

[pause]

None of this blocks the demo. All of it comes before wider use.

---

**Slide 8: Four checkpoints**

[the first checkpoint is already on screen. Click once for each of the next three.]

The question we hear most is this.

How much do you let the AI do?

[pause]

Our answer is four checkpoints. Every ticket passes all four.

For each one, I will also tell you **how** we do it. You can see it in the small box at the bottom of each card.

[point to the first card]

Checkpoint one is **before** the model.

Think of our insurance payment ticket. It has a customer's name, an email, maybe a bank account number.

All of that is masked first. The model only sees placeholders. The real values are put back on our side, afterwards.

How? We use **Presidio**, an open-source tool from Microsoft, plus our own list of terms.

[pause]

[click]

Checkpoint two is **around** the model.

Rules decide first. The model is asked only once, for what the rules cannot settle.

When the model says something about a ticket, it must show the exact words from the ticket.

And there is a switch that turns the model **off**.

How? The rules run in our own code. The quote is checked by an exact text match. And the switch is a setting only an admin can change.

[pause]

[click]

Checkpoint three is **after** the model. This is where a person decides.

The engineer can accept the recommendation, edit it, or reject it.

A lead approves every P1 and P2 closure.

And an expert reads every article before it is published.

How? Each of them has a review screen in the console, shown by role.

[pause]

[click]

Checkpoint four is **the record**.

We keep what the agent said, and why. Next to it, what the engineer decided.

Every settings change is recorded, with who made it, and when.

How? Every agent run and every change is saved in the database. And everyone signs in, with a password or their Atlassian account.

[pause]

[click, point to the two lists at the bottom]

So what does the console do on its own? Three things.

It assigns tickets. It groups incidents. And it sends stakeholder updates.

Everything else **always** needs a person.

Changing a priority. Applying the fix. Sending the closure note. Publishing an article.

---

**Slide 9: Three roles**

[point to each column]

Three roles, one console.

The **engineer** works the ticket.

The **lead** runs the team and approves high-priority closures.

The **admin** writes the rules and can turn the model off.

---

**Slide 10: Where it stands**

[point to the three columns, left to right]

Ten of eighteen capabilities work in the demo today.

Four are in progress. Four are planned.

[pause, point to the bottom strip]

To move from demo to pilot, we need three things.

The support lead to confirm the labelled cases.

Access to ServiceNow and the mailbox.

Agreed SLA targets.

---

**Close**

[look up from the slide]

One point I want to be clear on.

[pause]

The agents do not act alone where it matters. A person reviews and approves, and every step is on record.

[pause]

The agents do the groundwork.

**Our people make the decisions.**

[stop. Take questions, or move to the live demo.]

---

## If they ask

- **"Is this live?"** It is a demo build. Ten of eighteen capabilities work today, on a live Jira project.
- **"Has it saved time?"** We have not measured that yet. Slide 7 shows what we have measured.
- **"How good are the scores?"** 190 of 190, on small case sets our team wrote. The support lead still has to confirm them.
- **"Did anything fail?"** One. On 33 tickets Triage had not seen before, it got 32 right. That set is not on the slide.
- **"How did you test Resolution?"** Ten closed tickets with a known answer. All ten cited the right article. A second model checked the answer against what the agent had read: 0.93 out of 1. The full set is still to run.
- **"Which AI?"** Claude. Personal data is masked by Presidio before every call.
- **"Can it change a ticket alone?"** It assigns, groups and sends updates. Priority, fixes, closure notes and articles need a person.
- **"Do we move off Jira or ServiceNow?"** No. They stay the source and the destination.
- **"What if the model is wrong or down?"** Rules run first and do not need it. An admin can turn it off.
