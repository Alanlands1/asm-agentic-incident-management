# AMS Console: live demo guide

Step by step, about 10 minutes. Do this after slide 10, or in place of slide 5.

- **Do** is what to click. **Say** is what to say. **Show** is what the room should notice.
- [pause] means stop for two seconds.
- Never switch to Jira during the demo. Everything happens in the console.
- The demo uses the five insurance tickets, AMS-27 to AMS-31 (application: CreditorProtect). Rehearse once and adjust anything that differs.

## Before the demo (30 minutes before)

- Start the backend on port 8010 and the console on port 3010. Open the console in the browser, full screen.
- Check that you can sign in as all three people: an admin, a lead and an engineer.
- Do **not** press Reset demo unless you have rehearsed it: it has not been tried since the insurance tickets were added.
- Open these three tickets once, so they load fast later: AMS-28 "Insurance payment didn't go through", AMS-29 "Spelling mistake on the claim form page", and AMS-27 "Insurance payment didn't go through for deal 11111".
- Check that the checkout tickets show as **one** incident on the Incidents page.
- Close Jira, email and chat. Turn notifications off.
- Keep the deck open in a second tab, on slide 5, in case the console fails.

## Step 1: Sign in and the home page

**Do:** Sign in as the admin. Stay on Home.

**Say:** This is the console. I am signed in as an admin, so I see everything.

**Show:** The tiles at the top: how many tickets are open, and how many need a person.

**Say:** These tickets came in from Jira. ServiceNow and the mailbox come in the same way.

[pause]

## Step 2: Data Quality stops a bad ticket

**Do:** Open All tickets. Open AMS-28, "Insurance payment didn't go through".

**Say:** Look at this ticket. "Insurance payment failed. Please fix asap." Which deal? Which customer? Nobody can work on that.

**Show:** The Data Quality step: flagged, with the reason and what is missing.

**Say:** The agent has stopped it, said why, and written the email asking for the missing details.

**Show:** The drafted email to the requester.

**Say:** The engineer has not spent a minute on it.

[pause]

## Step 3: Triage corrects the priority

**Do:** Go back. Open AMS-29, "Spelling mistake on the claim form page".

**Say:** The requester marked this one as the highest priority. It is a spelling mistake. Customers can still submit the form.

**Show:** The priority the agent set, P5, and the reason beside it.

**Say:** The agent used the rulebook, not the requester's guess. And because that is a big change, it waits for a person to agree.

**Do:** Accept the priority.

**Do:** Go back. Open AMS-27, "Insurance payment didn't go through for deal 11111".

**Say:** This is the opposite case. It was raised as Medium. But a customer's insurance payment has failed, and their cover is at risk.

**Show:** The priority P2, the reason, and the SLA time left.

**Say:** The agent raised it, and it tells you why. The SLA clock is already running.

[pause]

## Step 4: Resolution suggests the fix

**Do:** Stay on AMS-27. Scroll to the Suggested fix.

**Say:** Now the part that used to take the longest. Finding the answer.

**Show:** The three steps, and the source next to them: KB-CRD-001.

**Say:** The ticket had a return code in it. The agent found the runbook article for that code, and picked the steps that apply.

**Say:** Every step shows where it came from. So the engineer can check it, not just trust it.

**Do:** Type one question into the AI assistant on the ticket, for example: "What if the retry fails again?"

**Say:** And if something is unclear, the engineer can ask, right here on the ticket.

[pause]

## Step 5: The lead's view

**Do:** Use "View as" to become the lead. Open the Lead desk.

**Say:** Now I am the team lead.

**Show:** Each engineer's open tickets, hours and leave.

**Say:** Tickets are assigned by shift, leave and load. I only step in when everyone is at their limit.

**Do:** If AMS-27 has no engineer yet, assign it here to the engineer you will sign in as.

**Do:** Open Incidents.

**Say:** This morning several people reported that checkout is failing.

**Show:** One incident card, with the linked tickets inside it.

**Say:** The console grouped them into one incident. We work it once, not ten times. And the stakeholder update goes out on its own.

[pause]

## Step 6: The engineer fixes and closes

**Do:** Use "View as" to become the engineer. Open My worklist.

**Say:** Now I am the engineer. My list is ordered by SLA time left. The most urgent is on top.

**Do:** Open AMS-27. Mark the fix as applied and working.

**Say:** I retried the payment, and it settled. The customer's cover is still active.

**Show:** The drafted closure note, with the gaps marked.

**Say:** The console has written the closure note. I only complete it.

**Do:** Complete the note and send it.

**Say:** Because this is a high-priority ticket, it goes to the lead for approval before it closes.

[pause]

## Step 7: Knowledge Builder closes the loop

**Do:** Go back to the admin. Open Agents, then Knowledge Builder.

**Say:** The ticket is closed. But the story does not end there.

**Show:** The drafts, the repeat issues, and the coverage per application.

**Say:** A fix that had no article becomes a draft article. An expert reviews it. Then the next search finds it.

[pause]

## Step 8: The team is in control

**Do:** Open Rule builder.

**Say:** The team writes the rules. Not us, and not the model.

**Show:** One rule, then the Runs page with the revert button.

**Do:** Open Reports.

**Say:** And everything is reported: by application, by agent, by engineer.

**Do:** Open Settings, then Change history.

**Say:** Every change to a setting is recorded here, with who and when.

[pause]

## Step 9: Close

**Do:** Go back to Home. Take your hands off the keyboard.

**Say:** So that is one ticket, from arrival to closure, in one place.

**Say:** The agents did the groundwork. A person made every decision.

[pause]

**Say:** Happy to take questions.

## If something goes wrong

- **A page is slow or blank:** say "let me show you the same thing on the slide", and go to slide 5 in the deck.
- **The suggested fix is missing:** open another ticket that has one; say that the agent answers "no match" when no runbook covers the problem.
- **Sign-in fails:** use the admin and "View as" for the other two roles.
- **Someone asks to see Jira:** say that Jira is only the source and the destination, and the closure note is written back there.

## After the demo

- Note which tickets you changed (AMS-27 and AMS-29), so the next run can use AMS-30 and AMS-31 in their place.
