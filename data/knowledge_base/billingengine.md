# BillingEngine — Application Support Knowledge Base

| Field | Value |
|---|---|
| Application ID | APP-BIL |
| Business function | Customer invoicing, credit notes, tax calculation, payment application |
| Business owner | Finance Controller |
| Support group | AMS-Finance |
| Criticality tier | **Tier 1** (revenue recognition, statutory tax compliance) |
| Support hours | Business hours 09:00–19:00, 24x7 on-call during month-end close (last 3 and first 3 business days) |
| Users | 40 finance users, B2B customers receive invoices by email |
| Tech stack | Python (Django), PostgreSQL 15, Celery workers, external tax calculation API, SAP FI interface |
| Upstream | OrderHub (orders), StockSense (shipments), SalesConnect CRM (customer accounts) |
| Downstream | SAP FI (AR postings), customer email (invoice PDFs) |

> **Info:** Month-end close issues that block invoice runs or postings are **P1/P2**. Issues affecting a single invoice are usually P3.

---

## Known issues and resolutions

### KB-BIL-001 — Monthly invoice run fails / invoices not generated

**Symptoms**
- Job `INV_MONTHLY_RUN` ends with status `FAILED`; invoices for the period are missing.
- Celery logs: `TaxServiceTimeout: tax API did not respond in 30s`.

**Root cause**
The external tax calculation API throttles requests during month-end peak; the run aborts after repeated timeouts.

**Resolution steps**
1. Check the tax provider status page.
2. Re-run in resume mode: `manage.py invoice_run --period <YYYY-MM> --resume --batch-size 200`.
3. If the tax API is down, enable cached tax rates (`TAX_FALLBACK=cached`) — requires Finance Controller approval.
4. Reconcile: invoice count = shipped orders count for the period (report *Billing → Run summary*).

**Escalation:** P1 during month-end close. Inform the Finance Controller.

---

### KB-BIL-002 — Invoice shows wrong tax amount

**Symptoms**
- Customer or finance user reports GST/VAT on the invoice is incorrect (0% or old rate).

**Root cause**
Customer tax code missing in the customer master (synced from CRM), or the tax rate table was not updated after a statutory change.

**Resolution steps**
1. Open the invoice and check the tax code applied.
2. If the customer tax code is missing, update the account in CRM and run `CUST_SYNC`.
3. If the rate is outdated, raise a change to update the tax rate table (Finance approval).
4. Cancel the incorrect invoice with a credit note and re-issue.

**Escalation:** P3 single invoice; P2 if the rate table is wrong for all customers.

---

### KB-BIL-003 — Invoice email bounced / customer did not receive invoice

**Symptoms**
- Delivery report shows `550 5.1.1 recipient address rejected`.
- Customer says invoice never arrived.

**Root cause**
Customer billing email in the customer master is incorrect or the mailbox no longer exists.

**Resolution steps**
1. Check *Billing → Invoice → Delivery log*.
2. Confirm the correct billing email with the account manager.
3. Update the billing contact in CRM, run `CUST_SYNC`, then click *Resend invoice*.

**Escalation:** None. P4.

---

### KB-BIL-004 — Credit note cannot be created (BIL-CN-403)

**Symptoms**
- Error `BIL-CN-403: approval required — amount above threshold` when creating a credit note.

**Root cause**
Credit notes above **INR 5,00,000** require Finance Controller approval by design. This is expected behaviour, not a defect.

**Resolution steps**
1. Explain the approval policy to the user.
2. User submits the credit note via *Request approval*; the Finance Controller approves in the approvals queue.
3. Once approved, the credit note is created automatically.

**Escalation:** None. P4 (working as designed).

---

### KB-BIL-005 — Customer payment not applied to invoice

**Symptoms**
- Customer has paid but the invoice still shows `OPEN`; dunning reminders sent to the customer.
- Payment sits in *Unapplied cash*.

**Root cause**
The bank remittance reference did not match the invoice number format (e.g. customer used their PO number).

**Resolution steps**
1. Search *Unapplied cash* by amount and date.
2. Manually match the payment to the invoice (*Apply payment*).
3. Pause dunning for the customer for 7 days.
4. Ask the account manager to remind the customer to quote the invoice number.

**Escalation:** None. P3 (P2 if a key account was sent a dunning letter).

---

### KB-BIL-006 — Invoice generated twice for the same order

**Symptoms**
- A customer receives two invoices with different numbers for one order.
- Celery logs show the `generate_invoice` task ran twice for the same order id.

**Root cause**
A Celery worker restarted during the run and the task was retried without the idempotency check on the order id, so a second invoice was created.

**Resolution steps**
1. Find duplicates: BillingEngine Admin → *Reports → Duplicate invoices* for the run date.
2. Cancel the later invoice of each pair with a credit note (KB-BIL-004 if credit notes fail).
3. Make sure only one AR posting per order reached SAP FI; reverse the extra posting with Finance.
4. Raise a defect for the Billing Dev team to enforce one invoice per order.

**Escalation:** P2 near month-end or above 50 duplicates, otherwise P3. Finance Controller approves reversals.

---

### KB-BIL-007 — Rounding differences on multi-currency invoices

**Symptoms**
- Invoice totals differ by 0.01 from the sum of the lines for non-INR invoices.
- SAP FI rejects postings with `BALANCE_NOT_ZERO`.

**Root cause**
Lines are converted and rounded one by one, while the total is converted once, so rounding differs; the exchange-rate table for the day may also have too few decimals.

**Resolution steps**
1. Check the day's rate in BillingEngine Admin → *Exchange rates* has 6 decimals.
2. Correct the rate if needed and re-run *Recalculate totals* for the affected invoices.
3. Re-post rejected entries to SAP FI from *Interfaces → Failed postings → Retry*.
4. If differences remain, book them to the rounding account agreed with Finance.

**Escalation:** P3; P2 if it blocks month-end close.

---

## Escalation contacts

| Level | Team | When |
|---|---|---|
| L2 | AMS-Finance | All issues in this page |
| L3 | Billing Dev team | Code defects, failed runs not fixed by resume |
| Vendor | Tax API provider | Tax service outage |
| Business | Finance Controller | P1, approvals, month-end issues |
