# InsightBI — Application Support Knowledge Base

| Field | Value |
|---|---|
| Application ID | APP-BI |
| Business function | Management dashboards and reports (sales, finance, inventory, HR) |
| Business owner | Head of Data & Analytics |
| Support group | AMS-Data |
| Criticality tier | **Tier 3** (reporting only — no transactions are blocked) |
| Support hours | Business hours 09:00–18:00 |
| Users | ~800 report consumers, 30 report developers |
| Tech stack | Power BI-style reporting service, Snowflake data warehouse, Airflow ELT pipelines |
| Upstream | OrderHub, BillingEngine, StockSense, PayrollPro, SalesConnect CRM (nightly loads) |

> **Info:** Reporting issues are normally P3/P4. Raise to **P2** only when a statutory/board report is due within 24 hours.

---

## Known issues and resolutions

### KB-BI-001 — Dashboard error "Data source credentials expired"

**Symptoms**
- Dashboard tiles show "Couldn't load data — data source credentials expired".

**Root cause**
The service account password for the Snowflake gateway connection was rotated (90-day policy) and the gateway was not updated.

**Resolution steps**
1. Reporting admin portal → *Gateways → Snowflake-PROD → Data sources*.
2. Update credentials with the new service account password from vault `bi/snowflake-svc`.
3. Trigger *Refresh now* on affected datasets.

**Escalation:** None. P3 (all dashboards on that gateway affected).

---

### KB-BI-002 — Daily sales report not refreshed

**Symptoms**
- Daily sales report shows yesterday's (or older) date.
- Airflow DAG `daily_sales_load` failed at task `extract_orderhub`.

**Root cause**
Upstream extract failure — OrderHub read replica unavailable or schema change.

**Resolution steps**
1. Airflow UI → `daily_sales_load` → check the failed task log.
2. If a connection error, confirm the OrderHub replica is up and clear the task to retry.
3. If a schema change, raise to the Data Engineering team.
4. After the DAG succeeds, refresh the dataset and confirm the report date.

**Escalation:** P3. Data Engineering for schema issues.

---

### KB-BI-003 — User cannot see a report / "You don't have access"

**Symptoms**
- User gets "You don't have access to this report" or sees an empty report (no rows).

**Root cause**
User not in the workspace access group, or row-level security (RLS) role not assigned for their region.

**Resolution steps**
1. Get the report owner's approval (attach to ticket).
2. Add the user to the AD group `BI-<workspace>-Viewers`.
3. For empty reports, assign the RLS role for the user's region.
4. Access applies within 1 hour (group sync).

**Escalation:** None. P4.

---

### KB-BI-004 — Report numbers differ from the source system

**Symptoms**
- User says revenue/orders in the dashboard do not match OrderHub or BillingEngine.

**Root cause**
Usually not a defect: InsightBI uses UTC day boundaries and loads data nightly (cut-off 02:00 UTC); source systems show local time and real-time data.

**Resolution steps**
1. Ask for the exact report, filter and source-system figure.
2. Compare using the same UTC date range.
3. If it still differs after aligning cut-off, raise to Data Engineering with both figures.
4. Otherwise explain the cut-off and close as *Working as designed*.

**Escalation:** None. P4.

---

### KB-BI-005 — Scheduled report email subscription not delivered

**Symptoms**
- User did not receive the scheduled report email.

**Root cause**
Subscription owner left the company (subscription disabled) or attachment exceeded 25 MB.

**Resolution steps**
1. Reporting admin portal → *Subscriptions* → check status and owner.
2. Re-create the subscription under the user (or a shared mailbox) if the owner is inactive.
3. If the attachment is too large, switch the subscription to "link" instead of attachment.

**Escalation:** None. P4.

---

### KB-BI-006 — Dashboard totals doubled after a data model change

**Symptoms**
- Revenue or order totals on a dashboard are about twice the expected value.
- Started after a dataset or data model was published.

**Root cause**
A new relationship or join in the model made rows repeat (one-to-many joined as one-to-one), so measures count every row twice.

**Resolution steps**
1. Compare the dashboard total with the source system for one day (KB-BI-004 for small differences).
2. Open the dataset's version history and find the change published before the problem started.
3. Roll back to the previous version, or fix the relationship to the right cardinality and republish.
4. Refresh the dataset and confirm the totals match the source.

**Escalation:** P2 if a board or statutory report is due; otherwise P3. Data Engineering for model changes.

---

### KB-BI-007 — Export to Excel fails or is cut off

**Symptoms**
- "Export failed" or the downloaded file stops at 150,000 rows.
- Large report pages time out when exporting.

**Root cause**
The reporting service limits exports to 150,000 rows and 10 minutes; large exports hit the limit.

**Resolution steps**
1. Ask the user to filter the report (date range or region) to fewer rows and export again.
2. For a full extract, schedule a paginated report delivery to the user's mailbox instead.
3. If the user needs it regularly, ask Data Engineering for a Snowflake extract share.

**Escalation:** P4 (workaround available).

---

## Escalation contacts

| Level | Team | When |
|---|---|---|
| L2 | AMS-Data | All issues in this page |
| L3 | Data Engineering | Pipeline / schema defects |
| Business | Head of Data & Analytics | Board / statutory report at risk |
