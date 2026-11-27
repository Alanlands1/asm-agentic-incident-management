# AMS Console: the script, story style

Spoken script for `ams-console-deck.html`, written in the style of a narrated explainer: a cold open, one question held back for the end, short chapters, and a turn ("except...") in each one. About 9 minutes at a normal pace.

- **[Slide N]** is when to move to that slide. **[click]** is one build on the slide.
- **[CUT: ...]** is a short clip or quote to record with a real person. Each is optional; the script reads fine without them.
- Every number here is from the deck. If the deck changes, change it here too.

---

## Cold open

**[Slide 1]**

A ticket lands in the support queue. Priority: P1. The most urgent thing in the building.

The problem? A profile photo won't upload.

The same morning, another ticket comes in marked Medium. Nothing special. Except this one is blocking the payroll run.

So the photo is an emergency and the salaries can wait. That's a hell of a queue.

And nobody did anything wrong. The requester guessed, because guessing is all the form lets them do. Which is why we got curious and asked ourselves: okay, what actually happens to a ticket between the moment it arrives and the moment someone fixes it?

So we dug in. And we found a story of six gaps that slow every single incident. A story of knowledge that exists, all of it, and still takes far too long to find. And most of all, a story of five small agents that each do one job, and an engineer who still makes every decision that matters.

Now, there's a question I have for the support leads in the room. But I'm going to ask it at the very end.

First, let's start with where the time goes.

---

## Chapter 1: Six gaps

**[Slide 2]**

Follow one ticket and count the places it waits.

**[click]** One. It arrives with details missing, so the work waits while someone writes back to ask.

**[click]** Two. The priority is the requester's guess. That's our profile photo.

**[click]** Three. Finding a free engineer takes a round of messages.

**[click]** Four. The fix is out there, spread across runbooks, old tickets, emails and people's heads.

**[click]** Five. One outage arrives as twenty tickets, and the deadline slips while nobody is looking.

**[click]** Six. The closure note is written by hand, in a different style each time, and often late.

Six gaps. And here's the thing: not one of them is a hard problem. Each one is small. They just all happen to the same ticket.

**[CUT: an engineer, ten seconds: "Most of my morning is finding out what the ticket is actually about."]**

---

## Chapter 2: The knowledge exists

**[Slide 3]**

Now you'd think the hard part is knowing the answer. It isn't.

The answer almost always exists. It's in a runbook. Or in a ticket someone closed in March. Or in an email. Or in the one person who's on leave this week.

So the engineer does the joining by hand. Open this, search that, ask someone, wait.

**[click]** The console does the joining instead. It reads the same sources and puts the suggested fix on the ticket, with the source of each step right beside it.

Okay, look. That last part is the whole point. A fix without a source is a guess. A fix with its source is something an engineer can check in ten seconds.

---

## Chapter 3: Five agents, each with one job

**[Slide 4]**

So how does it work? Not with one big clever system. With five small ones.

Data Quality checks the ticket before any work starts. Triage sets priority from the business rulebook, not from the requester. Resolution suggests a fix with its sources. Closure Quality drafts the closure note and marks what's missing. And Knowledge Builder turns a good fix into an article, so the next search finds it.

Around them: a Lead desk that assigns by shift hours, leave and open load. Incidents and SLA, which turns twenty tickets into one incident. And an assistant on the ticket you can simply ask.

Each agent reads one thing and produces one thing. That's it. Let me show you.

---

## Chapter 4: One ticket, start to finish

**[Slide 5]**

Remember the Medium ticket? "Payroll run blocked." Let's follow it.

**[click]** It comes in. Mailbox, Jira or ServiceNow, it doesn't matter which.

**[click]** Data Quality goes first. Rules check, then a model check. Is there enough here to act on? If not, it stops and drafts the email to the requester. This one is complete.

**[click]** Triage. The requester said Medium. The rulebook says a blocked payroll run is higher. Priority set, and the SLA clock starts.

**[click]** Resolution. It searches the runbooks and the closed tickets, reads what it finds, and searches again. Then it proposes the steps, each with where it came from.

**[click]** Assignment. Shift, leave, load. The ticket goes to an engineer without a single message. And the engineer applies the fix. Not the console. The engineer.

**[click]** Closure Quality drafts the note. The engineer completes it. Because this is a high priority, a lead approves it. Then it closes in Jira.

**[click]** And Knowledge Builder writes up the fix as a draft article, for an expert to review. Which feeds the next search.

You see the loop? The ticket that was fixed today is the reason tomorrow's is faster.

---

## Chapter 5: What's underneath

**[Slide 6]**

Twelve things sit behind that walk. I'll give you one from each group.

For accuracy: the quote check. When the model says something about a ticket, it only counts if the exact quote is in the ticket. No quote, no finding.

For speed: rules first, then the model. Rules settle what is certain. The model is asked once, for the rest.

For control: the team owns the rules. Ten operators, a run history, and a revert button.

---

## Chapter 6: Does it actually work?

**[Slide 7]**

Fair question. So we scored it.

All five agents, against cases the team labelled. 222 of 223 passed. And the whole build sits on 445 automated tests, all passing.

Sounds great, right? Except there's a catch. I guess there's always a catch.

These are small case sets, and we wrote them ourselves. The support lead still has to confirm the labels. Resolution is scored on its first ten tickets, not the full set. The SLA targets are provisional. And ServiceNow and the mailbox load from files today, not live.

Five open items. None of them blocks this demo. All of them matter before anyone relies on it.

**[CUT: the support lead, ten seconds, on what they would want to see before trusting a score.]**

---

## Chapter 7: Where the model stops

**[Slide 8]**

Now, the question everyone is really asking. How much do you let it do?

Four checkpoints.

**[click]** Before the model: personal data is masked. Names, emails, phones, IDs, bank and card numbers. The model sees placeholders, and the real values are put back locally.

**[click]** Around the model: rules decide first, findings need a quote, and there's a switch that turns the model off.

**[click]** After the model: a person decides. Engineers accept, edit or reject. A lead approves P1 and P2 closures. An expert reviews every article.

**[click]** And on record: each agent's verdict and reason, next to what the engineer actually did.

So what does the console do alone? It assigns tickets, groups incidents and sends stakeholder updates. That's the list.

Accepting a priority change, applying the fix, sending the closure note, publishing an article: those always need a person.

---

## Chapter 8: Three roles, one console

**[Slide 9]**

Three people use it, and each sees a different console.

The engineer sees a worklist ordered by SLA time left, and the ticket with its next action.

The lead sees the team: load, hours, leave, the review queue.

The admin sees the rules, the reports, and the off switch.

Same console. The menu follows the role.

---

## Close

**[Slide 10]**

So where does it stand? Ten of eighteen capabilities working in this demo. Four in progress. Four planned.

And to go from demo to pilot, we need three things. The support lead to confirm the labelled cases. Access to ServiceNow and the mailbox. And agreed SLA targets.

Look, it's hard to fit the story of a support team into ten slides. But here's the strand I'd keep.

The profile photo was never the problem. The payroll ticket was never the problem. The problem was the waiting in between: for details, for a priority, for a person, for an answer, for a note.

The console takes the waiting. The engineer keeps the decision. And that, to me, is the real story of this console.

Before we go, I had a question for the support leads. And I really want to get this right.

Which ticket would you give it first?
