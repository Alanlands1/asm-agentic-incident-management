# AMS Console: demo script

For `ams-console-deck.html`. About 8 minutes. Lines in **[brackets]** are actions, not spoken.

---

## Slide 1 · Cold open

**[Cover on screen. Wait two seconds.]**

Six.

That is how many places an engineer may have to look before starting to fix one ticket. Jira. ServiceNow. The mailbox. The runbooks. Old tickets. And that one colleague who "has seen this before".

The answer is usually somewhere. That's the frustrating part. We *know* it. We just can't *find* it fast enough.

So we got curious and asked: what if the ticket arrived with the homework already done?

This is the story of one ticket. Of how it gets checked, prioritised and solved, how it teaches the system something on the way out, and why a person still has the final say.

And at the very end, I have one question for you.

This is the AMS Console.

**[Click]**

## Slide 2 · The problem

Okay, let's start with what actually goes wrong. Four things.

One: **knowledge is scattered.** The fix is split across runbooks, past tickets, emails and people.

Two: **data quality.** A ticket says "I can't log in". That's it. So work stops while someone writes back to ask for the basics.

Three: **triage is inconsistent.** Priority is the requester's guess. First steps depend on who is on shift and what they remember.

Four: **communication.** Closure notes and updates are written by hand, in different styles, often late.

None of these is dramatic on its own. But they repeat on ticket after ticket.

**[Click]**

## Slide 3 · Before and after

Here is a normal day. An incident arrives, and the engineer becomes a detective. Six sources, searched by hand, joined up in their head, while the clock runs.

Now the other side. The incident arrives, goes through one pipeline, and reaches the engineer already checked, prioritised and with a suggested fix and its sources.

From six places to one.

But the obvious question is: who is doing all that work in the middle?

**[Click]**

## Slide 4 · The five agents

Five agents. Think of them as five specialists who each do one job and hand it on.

**Data Quality** asks: is there enough here to start?
**Triage** asks: how urgent is this, really?
**Resolution** asks: have we solved this before?
**Closure Quality** asks: did we write down what we did?
**Knowledge Builder** asks: will the next person find it?

Around them sit the Lead desk, incidents and SLA, and an AI assistant on the ticket.

A list of agents is easy to forget, though. So let's follow one ticket.

**[Click]**

## Slide 5 · One ticket

**[Overview]**
Our example: a payroll run is blocked. The requester has marked it **Medium**. Remember that word.

**[Click 1 · Ticket arrives]**
It can come from three places: Jira, which is connected live, a ServiceNow spreadsheet, or support mailbox emails, which in this build are samples.

**[Click 2 · Data Quality]**
First check: can anyone act on this? If not, it stops here, says why, and drafts the email asking for what's missing. Ours has enough. It moves on.

**[Click 3 · Triage]**
Now, that word. Medium. But a payroll run is blocked, and the rulebook says this is higher. The console doesn't take the requester's guess. It applies the business rules, names the application and starts the SLA clock.

**[Click 4 · Resolution]**
This is where the detective work used to happen. It searches the runbooks and similar closed tickets, and proposes steps. Every step shows where it came from, so you can check it.

**[Click 5 · Lead and engineer]**
And here a human takes over. The lead assigns, helped by a suggestion that knows shift hours, leave and workload. The engineer applies the fix and records whether it actually worked.

**[Click 6 · Closure Quality]**
Fixed. Except nobody loves writing closure notes. So the console drafts it and marks what is missing. The engineer completes it, a lead approves P1 and P2, and the engineer sends it.

**[Click 7 · Knowledge Builder]**
Most ticket stories end here. This one doesn't. The fix is matched to an article. If none covers it, a new one is drafted for an expert to review. If the same issue keeps coming back, it suggests a problem record.

**[Click 8 · All connected]**
And that is the loop. Today's reviewed fix becomes something tomorrow's search can find. The system gets more useful because people did their work.

**[Click]**

## Slide 6 · Under the hood

How does it hold together? Twelve capabilities. I won't read all twelve. Here are the three that matter most.

**Rules first, model second.** What rules can settle, rules settle. The model is only asked for the rest. That helps speed and cost.

**The quote check.** If the model reports a finding, it has to point to the exact words in the ticket. No quote, it doesn't count.

**Hybrid search.** It looks by meaning and by keyword, so it can catch both "salary didn't go out" and a precise error code.

**[Click]**

## Slide 7 · Does it work?

Fair question. Show me.

Three of the five agents have recorded scores, and they passed every scored case. Data Quality: 35 of 35 sample tickets, 16 of 16 borderline ones. Closure Quality: 33 of 33 real notes, 21 of 21 labelled cases. Knowledge Builder: 33 of 33 matched to the right article, 10 of 10 gaps found.

And 412 automated tests passing on this build.

Now, there's a catch, and I'd rather you hear it from me. These case sets are small, we wrote them, and the support lead still has to confirm the labels. Resolution isn't scored yet. So read this as a strong start, not a finished proof.

**[Click]**

## Slide 8 · Control

Which brings up the question every client asks: what stops the AI doing something it shouldn't?

Three layers. First, **data**: personal data is masked before any model call. Second, **access**: sign-in, three roles, a role check on every route, and a history of settings changes. Third, **people**: engineers accept, edit or reject. Nothing goes to Jira unless a person sends it. And there is a kill switch for the model.

The agents prepare. People decide.

**[Click]**

## Slide 9 · Three roles

Same console, three views.

The **engineer** opens a worklist ordered by SLA time left, and always sees the next action.

The **lead** runs the team: assignments, shifts and leave, reviews and incidents.

The **admin** owns the rules and reports, and can view the console as any person sees it.

**[Click]**

## Slide 10 · Where we are

So where does this stand? Sixteen capabilities.

**Eight** are working in this demo. **Four** are built but running on sample or provisional data, like the ServiceNow and mailbox connections and the SLA targets. **Four** are planned: ask a question, log analyzer, problem records and a major-incident agent.

We're not calling it finished. We're showing you what works, what's half way, and what's next.

## Close

**[Pause. Look at the room, not the screen.]**

We started with six places to look.

Every team already has the knowledge. It sits in a closed ticket, an old runbook, or someone's memory. The AMS Console is our attempt to put it in front of the engineer at the moment it's needed, and to keep what they learn when they're done.

So here's my question.

When your best engineer is on leave, and payroll is blocked... **where does the fix live?**

**[Pause three seconds.]**

Thank you. Happy to take questions.
