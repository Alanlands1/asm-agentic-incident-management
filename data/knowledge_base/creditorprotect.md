# CreditorProtect — Application Support Knowledge Base

| Field | Value |
|---|---|
| Application ID | APP-CRD |
| Business function | Creditor insurance on mortgages and loans: enrolment, premium collection, claims, benefit payments to lenders |
| Business owner | Creditor Insurance Operations Manager |
| Support group | AMS-Insurance |
| Criticality tier | **Tier 1** (customer coverage, payments to lenders, regulatory reporting) |
| Support hours | Business hours 08:00–20:00, 24x7 on-call for payment batches |
| Users | 120 operations and claims users, lender partners through the partner portal |
| Tech stack | Java (Spring Boot), Oracle 19c, Control-M batch, payment gateway (pre-authorized debit), lender file exchange over SFTP |
| Upstream | Lender loan systems (deal and balance data), payment gateway (debit results) |
| Downstream | Lender partners (benefit payment files), General Ledger, customer letters |

> **Info:** A deal is one insured mortgage or loan. A failed payment that can lapse a customer's cover, or a benefit payment that does not reach the lender, is **P2**; the same failure across many deals is **P1**. Text or layout issues are P5.

---

## Known issues and resolutions

### KB-CRD-001 — Insurance payment did not go through for a deal

**Symptoms**
- The user reports "insurance payment didn't go through"; the premium shows `RETURNED` in *Payments → Deal history*.
- Gateway return code `PAD-RET-901` (insufficient funds) or `PAD-RET-905` (account closed or changed).

**Root cause**
The customer's bank returned the pre-authorized debit, or the banking details on the deal are out of date.

**Resolution steps**
1. Open *Payments → Deal history* for the deal and note the return code.
2. For `PAD-RET-901`, retry: *Actions → Retry premium* (at most two retries).
3. For `PAD-RET-905`, get the current account from the lender, update *Deal → Banking details*, then retry.
4. Confirm the payment shows `SETTLED` and the coverage is still `ACTIVE`.

**Escalation:** P2 (the customer's cover is at risk). Many deals on one day: see KB-CRD-002.

---

### KB-CRD-002 — Daily premium collection batch failed

**Symptoms**
- Job `PREM_COLLECT_DAILY` ends with status `FAILED`; no premiums are collected for the day.
- Batch log: `GatewayAuthError: token expired` or `ORA-00060: deadlock detected`.

**Root cause**
The payment gateway token expired (it is renewed every 90 days), or the batch ran at the same time as the month-end balance refresh and deadlocked.

**Resolution steps**
1. Check the batch log for the error.
2. For `GatewayAuthError`, renew the token in *Admin → Integrations → Payment gateway*.
3. For a deadlock, wait until `BAL_REFRESH` has finished.
4. Re-run in resume mode: `prem_collect --date <YYYY-MM-DD> --resume`.
5. Reconcile: collected count = due count for the day (report *Payments → Collection summary*).

**Escalation:** P1. Inform the Creditor Insurance Operations Manager.

---

### KB-CRD-003 — Claim payment not received by the lender

**Symptoms**
- A lender reports that the monthly disability or life benefit for a deal did not arrive.
- Job `CLM_PAY_FILE` shows `COMPLETED WITH WARNINGS`; the deal is listed in the reject report with `LND-REJ-014`.

**Root cause**
The lender's reference number on the deal no longer matches the lender's loan system (for example after a mortgage renewal), so the lender's side rejected the payment line.

**Resolution steps**
1. Open *Claims → Payment files → Reject report* for the payment date and find the deal.
2. Confirm the lender's current reference with the lender partner desk.
3. Update it in *Deal → Lender reference*.
4. Release the payment again: *Claims → Payments → Reissue* (needs a claims supervisor to approve).
5. Confirm with the lender that the payment arrived, and note it on the claim.

**Escalation:** P2 (the customer's loan payment is missed). P1 if a whole payment file was rejected.

---

### KB-CRD-004 — Certificate of insurance not generated

**Symptoms**
- After enrolment the certificate of insurance is missing from *Deal → Documents*.
- Document service log: `DOC-GEN-417: template not found`.

**Root cause**
The lender's product code is new and has no certificate template mapped yet.

**Resolution steps**
1. Check the product code on the deal.
2. Map the code to the lender's template in *Admin → Documents → Template mapping*.
3. Regenerate: *Deal → Documents → Regenerate certificate*.
4. Confirm the certificate opens and shows the right lender and coverage.

**Escalation:** None. P3 (P2 if a whole lender's enrolments are affected).

---

### KB-CRD-005 — Text or layout mistake on a form or page

**Symptoms**
- A spelling mistake, wrong label or misaligned field on the claim form page, the enrolment page or a letter.
- Nothing is blocked; users can still submit.

**Root cause**
A content change went live without a proofread.

**Resolution steps**
1. Take a screenshot and note the page and language (English or French).
2. Raise a content change for the Creditor Dev team; it goes out with the next weekly release.
3. If the mistake changes the legal meaning of a form, tell Compliance the same day.

**Escalation:** None. P5 (cosmetic), whatever priority the reporter chose.

---

## Escalation contacts

| Level | Team | When |
|---|---|---|
| L2 | AMS-Insurance | All issues in this page |
| L3 | Creditor Dev team | Code defects, failed batches not fixed by resume |
| Vendor | Payment gateway provider | Gateway outage, token problems |
| Business | Creditor Insurance Operations Manager | P1, coverage at risk, approvals |
