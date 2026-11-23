# SalesConnect CRM — Application Support Knowledge Base

| Field | Value |
|---|---|
| Application ID | APP-CRM |
| Business function | Leads, opportunities, accounts, customer cases, sales reporting |
| Business owner | VP Sales Operations |
| Support group | AMS-CRM |
| Criticality tier | **Tier 2** (important, workarounds usually available) |
| Support hours | Business hours (08:00–20:00 local), on-call for P1 |
| Users | ~600 sales and customer-support users |
| Tech stack | SaaS CRM platform with custom Apex-style extensions, integration middleware (MuleSoft-like) |
| Upstream | Website lead forms, marketing automation, support mailbox (email-to-case) |
| Downstream | InsightBI (sales dashboards), BillingEngine (customer accounts) |

> **Info:** Quarter-end (last 5 business days of a quarter) raises any issue blocking opportunity updates by one priority level.

---

## Known issues and resolutions

### KB-CRM-001 — User account locked / cannot log in

**Symptoms**
- Login page shows "Your account has been locked. Contact your administrator."
- Usually after 5 failed login attempts or after a password reset in another system.

**Root cause**
Platform lockout policy (5 attempts, 30-minute lock).

**Resolution steps**
1. Verify the user's identity (employee ID + manager name).
2. Admin console → *Users → <user> → Unlock*.
3. If the user forgot the password, click *Reset password* — reset link is sent to the corporate email.
4. Ask the user to log in via the SSO tile on EmployeePortal going forward.

**Escalation:** None. P4 (single user). P3 if user is on a customer call/deadline.

---

### KB-CRM-002 — Website leads not syncing into CRM

**Symptoms**
- Marketing reports that leads submitted on the website are not visible in CRM.
- Integration logs: `401 INVALID_SESSION_ID` or `Session expired or invalid`.

**Root cause**
The OAuth refresh token of the integration user expired or was revoked after a password change.

**Resolution steps**
1. Check integration middleware → flow `web-leads-to-crm` → error queue.
2. Re-authorise the connected app using the integration user (credentials in vault `crm/integration`).
3. Replay messages from the error queue (*Retry all*).
4. Confirm the count of leads in CRM matches the form submissions for the period.

**Escalation:** P2 (lost sales leads). Inform Marketing Ops when fixed.

---

### KB-CRM-003 — Dashboards / reports showing stale data

**Symptoms**
- Sales dashboard "last refreshed" timestamp is more than 24 hours old.
- Numbers do not include today's closed deals.

**Root cause**
Scheduled dashboard refresh failed because the running user was deactivated or hit a row limit.

**Resolution steps**
1. Open the dashboard → *Properties* → check the running user is active.
2. Change the running user to the service account `svc_crm_reports` if needed.
3. Click *Refresh* manually and confirm the timestamp updates.

**Escalation:** None. P4 normally (data is still available in list views).

---

### KB-CRM-004 — "Insufficient privileges" when editing an opportunity

**Symptoms**
- User can view but not edit opportunities/accounts; error "Insufficient privileges".
- Typically after a role change, transfer, or new joiner setup.

**Root cause**
Permission set `Sales_User_Edit` not assigned after role change.

**Resolution steps**
1. Confirm the user's new role with their manager (approval required — attach to ticket).
2. Admin console → *Users → <user> → Permission set assignments → Add `Sales_User_Edit`*.
3. Ask the user to log out and back in.

**Escalation:** None. P3 (P2 at quarter-end).

---

### KB-CRM-005 — Support emails not creating cases (email-to-case)

**Symptoms**
- Customers email support@ but no case appears in CRM.
- Support team notices case volume dropped to zero.

**Root cause**
The forwarding rule on the support mailbox was disabled (mailbox migration / policy change), so emails never reach the CRM routing address.

**Resolution steps**
1. Check the shared mailbox forwarding rule to the CRM email-to-case routing address.
2. Re-enable the rule (Exchange admin) — requires Messaging team.
3. Forward the emails received during the outage window to the routing address to create cases.
4. Confirm new cases appear with correct origin = Email.

**Escalation:** P2 (customer cases being missed). Messaging team for mailbox rules.

---

### KB-CRM-006 — Duplicate leads from website forms

**Symptoms**
- Sales reps see the same lead two or three times with the same email.
- The integration middleware log shows the same form submission posted more than once.

**Root cause**
The middleware retried lead creation after a timeout, and the duplicate rule on email is set to alert only, so duplicates are saved.

**Resolution steps**
1. Merge the duplicates: CRM → *Leads → Find duplicates* by email, then *Merge*.
2. Set the lead duplicate rule on email to *Block* (CRM admin).
3. Ask the CRM Dev team to make the middleware send an idempotency key with each submission.

**Escalation:** P3; P2 at quarter end or during a campaign.

---

### KB-CRM-007 — Quote PDF not generated

**Symptoms**
- *Generate quote* spins and no PDF is attached to the opportunity.
- Error `TEMPLATE_RENDER_ERROR` in the quote log.

**Root cause**
The quote template refers to a field that was renamed or removed, or a product has no list price in the price book used by the quote.

**Resolution steps**
1. Open the quote log for the opportunity and note the field or product in the error.
2. Add the missing price to the price book, or update the template field mapping (CRM admin).
3. Generate the quote again and check the PDF.

**Escalation:** P3; P2 when a deal must be quoted the same day.

---

## Escalation contacts

| Level | Team | When |
|---|---|---|
| L2 | AMS-CRM | All issues in this page |
| L3 | CRM Dev team | Custom code / integration defects |
| Partner | Messaging team | Mailbox / forwarding rules |
| Business | VP Sales Operations | P1, quarter-end blockers |
