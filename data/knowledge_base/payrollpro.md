# PayrollPro — Application Support Knowledge Base

| Field | Value |
|---|---|
| Application ID | APP-PAY |
| Business function | Monthly payroll, payslips, tax declarations, bank salary transfers |
| Business owner | HR Operations (Head of Payroll) |
| Support group | AMS-HR-Apps |
| Criticality tier | **Tier 1** (business critical during payroll window: 20th–last working day of month) |
| Support hours | 24x7 for P1/P2, business hours (09:00–18:00 IST) for P3–P5 |
| Users | ~4,500 employees (self-service), 25 payroll admins |
| Tech stack | Java 17 / Spring Boot, Oracle 19c, Control-M batch scheduling, payslip-renderer (PDF microservice) |
| Upstream | TimeTrack (timesheets/overtime), EmployeePortal (employee master via SSO) |
| Downstream | SAP FI (GL postings), Bank SFTP gateway (salary transfer files) |

> **Info:** During the payroll window any failure that delays salary processing is treated as **P1** regardless of how many users report it.

---

## Architecture overview

- **payroll-core** — calculation engine, runs as Control-M jobs (`PAY_CALC_MONTHLY`, `PAY_PDF_GEN`, `PAY_BANK_FILE`, `TT_SYNC`).
- **payroll-web** — admin UI and employee self-service (payslips, tax declarations).
- **payslip-renderer** — stateless PDF generation service consuming from the `payslip-render` queue.
- **bank-connector** — builds the salary transfer file and pushes it to the bank over SFTP.

---

## Known issues and resolutions

### KB-PAY-001 — Payslip PDF is blank or not generated

**Symptoms**
- Employees see "Payslip not available" or download a blank / 0 KB PDF from self-service.
- Admin UI shows payslip status `QUEUED` for many employees long after `PAY_PDF_GEN` finished.
- Log message: `PDF-GEN-500: renderer timeout while processing batch`.

**Root cause**
The payslip-renderer consumer stops acknowledging messages after a memory spike; the `payslip-render` queue backs up.

**Resolution steps**
1. Check queue depth: `payroll-admin queue-stats payslip-render` (healthy < 100).
2. Restart the renderer: `kubectl rollout restart deploy/payslip-renderer -n payroll`.
3. Wait for queue depth to drain (approx. 2 min per 1,000 payslips).
4. For employees still in `QUEUED`/`FAILED`, re-trigger generation from Admin UI → *Payslips → Regenerate* for the affected period.
5. Ask one affected employee to download the payslip again to confirm.

**Escalation:** If the queue does not drain after restart, escalate to the Payroll Dev team (L3).

---

### KB-PAY-002 — Monthly payroll batch PAY_CALC_MONTHLY fails

**Symptoms**
- Control-M shows job `PAY_CALC_MONTHLY` in status *Ended Not OK*.
- Job log contains `ORA-01555: snapshot too old: rollback segment number ... too small`.
- Payroll admins cannot lock the payroll period.

**Root cause**
The calculation runs as a single long transaction; on large months (bonus/arrears) it exceeds Oracle undo retention.

**Resolution steps**
1. Do **not** re-run the job blindly — check the last successfully committed chunk in table `PAY_RUN_LOG`.
2. Re-run with chunking: set job parameter `CHUNK_SIZE=500` and `RESUME_FROM=<last chunk id>`.
3. Raise a DBA request to increase `UNDO_RETENTION` to 10800 for the payroll window.
4. After success, run `PAY_RECON_CHECK` and share the variance report with the payroll admin.

**Escalation:** P1 during payroll window. Inform the Head of Payroll immediately; DBA on-call if ORA errors persist.

---

### KB-PAY-003 — Tax declaration cannot be saved

**Symptoms**
- Employee clicks *Save* on the tax declaration form and receives `TAXDEC-VAL-02: upload failed` or "Session expired".
- Typically happens when attaching proof documents (rent receipts, insurance).

**Root cause**
Attachments larger than **5 MB** or in unsupported formats (HEIC, ZIP) are rejected; the generic error is shown as session expiry.

**Resolution steps**
1. Ask the user for file size and format.
2. Advise compressing the file to under 5 MB and using PDF/JPG/PNG.
3. Ask the user to clear browser cache and re-login via EmployeePortal SSO.
4. If the declaration deadline is within 48 hours, payroll admin can upload on behalf of the employee (*Admin → Tax → Upload proof*).

**Escalation:** Not normally required. P4 unless the declaration deadline is today.

---

### KB-PAY-004 — Salary bank transfer file not delivered to bank

**Symptoms**
- Job `PAY_BANK_FILE` completes but bank-connector logs show `SFTP auth failed: publickey denied`.
- Bank relationship manager reports file not received.
- Employees report salary not credited on payday.

**Root cause**
The SSH key used for the bank SFTP gateway expires every 12 months and was not rotated.

**Resolution steps**
1. Confirm the error in `bank-connector` logs.
2. Generate a new key pair via the secrets vault (`vault write payroll/bank-sftp rotate=true`).
3. Share the new public key with the bank's integration desk (contact in vault metadata) — requires change approval (emergency CAB if on payday).
4. Re-send the file: `payroll-admin bank-file resend --period <YYYY-MM>`.
5. Get written confirmation of receipt from the bank.

**Escalation:** Always **P1** if salary date is today or tomorrow. Notify Head of Payroll and Treasury.

---

### KB-PAY-005 — Overtime / allowance calculated incorrectly

**Symptoms**
- Employee reports overtime missing or lower than approved timesheet hours.
- Payroll shows overtime hours = 0 while TimeTrack shows approved hours.

**Root cause**
The `TT_SYNC` integration job that pulls approved timesheets from TimeTrack ran before the manager approval cut-off, or failed silently.

**Resolution steps**
1. Compare hours in TimeTrack vs PayrollPro for the employee and period.
2. Check `TT_SYNC` job history in Control-M.
3. Run `TT_SYNC` manually for the period, then recalculate the employee (*Admin → Employee → Recalculate*).
4. If payroll is already locked, raise an off-cycle adjustment for the next run.

**Escalation:** P3 for individuals; P2 if a whole department is affected during payroll window.

---

### KB-PAY-006 — Employee missing from the monthly payroll run

**Symptoms**
- An employee has no payslip after `PAY_CALC_MONTHLY` finished.
- The employee is active in EmployeePortal but not in the payroll population report.

**Root cause**
The employee's payroll record was not created: missing bank details or tax id stopped the employee master load, or the joining date is after the payroll cut-off.

**Resolution steps**
1. Check the employee in payroll-web → *Population report* for the month and the load error log.
2. Ask HR to add the missing bank details or tax id.
3. Run an off-cycle calculation for the employee: Control-M job `PAY_CALC_OFFCYCLE` with the employee id.
4. Generate the payslip (`PAY_PDF_GEN`) and add the payment to the next bank file or a manual transfer.

**Escalation:** P2 inside the payroll window (salary date at risk), otherwise P3. Head of Payroll approves off-cycle payments.

---

### KB-PAY-007 — Payslip shows last month's figures

**Symptoms**
- Employees open this month's payslip and see last month's amounts.
- payslip-renderer logs show cache hits for the new period.

**Root cause**
The renderer cache was not cleared after the new period was published, so it served the previous PDFs.

**Resolution steps**
1. Confirm the figures in payroll-web are correct for the new month.
2. Clear the renderer cache: payroll-web Admin → *Payslips → Clear cache* (or restart payslip-renderer).
3. Re-run `PAY_PDF_GEN` for the period.
4. Spot-check five payslips, then tell the Service Desk the issue is fixed.

**Escalation:** P3; P2 on salary day.

---

## Escalation contacts

| Level | Team | When |
|---|---|---|
| L1 | Service Desk | Password/SSO issues, how-to questions |
| L2 | AMS-HR-Apps | All issues in this page |
| L3 | Payroll Dev team | Code defects, renderer failures not fixed by restart |
| Business | Head of Payroll | Any P1, any delay to salary date |
