# Data Quality agent: Plan v0.2

Scope: the first agent only. It decides whether an engineer can act on a ticket, names what is missing, and produces the "missing information" email that a person sends. Triage and Resolution are out of scope except for the hand-off fields at the end of section 4.

Numbers marked *measured* were run against the 100 tickets in `data/tickets/ams_tickets.xlsx` and the answer key in `evaluation/ground_truth.xlsx` on 2026-10-27, and re-run independently by the review. Numbers marked *guess* say how they will be firmed up.

## Changes from v0.1

v0.1 was reviewed with the ai-architect skill (`docs/review-data-quality.md`). Verdict: build it with these changes. Every major and minor finding is folded in below.

| Finding | What changed |
|---|---|
| 1 Email validation rejected the plan's own template; the model should not write the email | The model returns one question per missing item. Code assembles the email. The ticket number and the requester's name never pass through the model. |
| 2 Idempotency key broke on prompt bumps and on reply re-check | Key is now (ticket, agent, input hash, prompt version). A ticket with a human decision is skipped unless its input changed. |
| 3 PII scope narrower than the project rule; phone regex ate invoice numbers | PII class list is an open question for the client's privacy owner. Identifiers become typed reversible tokens. Phone regex anchored. Redaction eval asserts identifiers survive. |
| 4 Eval was a training-set score with holes | Application accuracy added. Coverage is F1 with a spurious-ask count. The 15 are named as the tuning set; the real-ticket slice is the only holdout. Rater named. Borderline rows acknowledged. |
| 5 LangGraph justified by a feature that is deferred | v0.1 runs the nodes in a plain function. The gate is a status on the run row. LangGraph is re-decided at v0.2 with the reply path in hand, and the decision is written down either way. |
| 6 Residency is more than a class swap | Stack names the Bedrock client in a Canadian region, refusal fallback via SDK middleware, with a verification line to fill in. |
| 7 Taxonomy and verdict holes | `location` and `requested_access` added. `service_request` is its own verdict with no chase. |
| 8 Reject meant two things | Reject takes a reason; each reason maps to a status. |
| 9 Unreachable rule, one-character margins, a number that did not reproduce | Signals first, verdict second. Thresholds marked provisional. Count corrected. |
| 10 Urgent tickets had no mechanism | Triage's selection query is written down. |
| 11 Latency guess optimistic; rollback trigger wrong-headed | p95 target 60 s, dashboard line, not a rollback trigger. |
| 12 Gate under-specified | One HTMX page in milestone 3. |
| 13 No URL or token checks on model text | Added to question validation. |
| Nits | Checklist moved out of the cached prefix. Kill switch read per run, global plus per-agent. Breaker is per run. `confidence` dropped. Volume stated as a ceiling. Retention covers output and edited text. |

**Added after the review:** redaction is Microsoft Presidio with spaCy NER rather than hand-written regexes. It covers the third-party names the regex could not, runs in process so it does not touch residency, and moves the named-entity pass from milestone 4 into milestone 2. Details in the prepare step and the stack table.

One change is a reversal of the original request: LangGraph is out of v0.1. The reason is the review's, and it is honest: five nodes and one gate are sixty lines of Python, and the only thing the framework buys, resume on requester reply, does not exist until a mailbox poll does. It comes back at v0.2 if the engineers want it then. See open question 3.

---

## 1. The job

The person on the AMS support rota opens every new ticket from ServiceNow, JIRA and the support mailbox and decides whether it can be worked. In the sample, 15 of 100 cannot: "System not working. Please fix ASAP.", "cant login", a forwarded email with only a screenshot. The rota person reads it, guesses the application, writes a chasing email by hand, and the ticket sits until the requester answers. This agent produces one verdict per ticket (`pass`, `needs_info`, `not_an_incident`, `service_request`, or `needs_review` when the model is unavailable), a list of the specific items missing for that application with one plain question each, and an assembled email a person accepts, edits or rejects and sends from their own mail client.

What must never happen:

- No email is sent and no ServiceNow or JIRA record is changed by the agent. It writes to this service's database only.
- Nothing on the client's PII class list reaches the model. Redaction runs before every call. The model never sees the ticket number or the requester's name, and never writes the email.
- A P1 or P2 ticket is never held up: it gets the same verdict and draft, and Triage selects it regardless of the data-quality outcome (section 4, record).
- The model endpoint is in a Canadian region. Unverified for the models named below; see open question 1. Until it is verified, only the synthetic tickets in this repo are processed.

Assumptions I am making because the brief did not say:

- The trigger is ingestion: any ticket with `pipeline_status = pending` whose latest `data_quality` run, if any, has no human decision or a different input hash.
- The per-application checklist is derived from the seven knowledge-base pages. The support lead corrects it; the agent does not invent it.
- The human gate is the decision endpoint from the code review plus one HTMX page served by this app.
- Production volume is unknown. The sample has 67 open tickets over 8 days, so 8 to 10 a day; 40 a day is the planning ceiling (*guess*; open question 8).

## 2. What "working" means

**The eval set**

| Slice | Size | Where it comes from | Role |
|---|---|---|---|
| Should-fail tickets | 15 | `ground_truth.xlsx`, `scenario = incomplete`; 3 are marked borderline in the key | Tuning set |
| Should-pass tickets | 85 | all other scenarios, every one with `expected_application` | Tuning set for false fails; scores application accuracy |
| Real incomplete tickets | 7–14, one or two per app | support lead, before milestone 2 ends | The only holdout. Nothing is tuned on it |
| Reply re-check | 0 in v0.1 | synthetic: original plus reply appended | Deferred with the reply path |

The thresholds in section 4 were chosen on the 100 synthetic tickets. The ship bars below are therefore met on the tuning set by construction and are only meaningful once the holdout exists. The plan says "not yet met" until at least 7 held-out tickets are scored.

The `missing_information` column is free text. Day 1 maps it to a fixed taxonomy so coverage can be scored in code:

```
application, symptom, error_text, since_when, impact_scope, identifier,
period, environment, location, attachment_content, previous_ticket_ref,
approval, requested_access, expected_vs_actual, not_an_incident
```

**Metrics and bars**

| Metric | Definition | Bar to ship | Rollback trigger |
|---|---|---|---|
| Fail recall | should-fail tickets with verdict `needs_info`, `not_an_incident` or `service_request` | 15 / 15 on the tuning set; ≥ 90% on the holdout | < 13 / 15, or < 80% on the holdout |
| False-fail rate | should-pass tickets with verdict other than `pass` | ≤ 2 / 85 (2.4%) | > 4 / 85, or > 5% of production tickets in a week |
| Missing-item F1 | precision and recall of `missing[].item` against the taxonomy-mapped ground truth, averaged over the 15 | F1 ≥ 0.75 | < 0.65 |
| Spurious asks | items in `missing[]` the ticket already answers, counted by the rater | ≤ 0.3 per ticket | > 1 per ticket |
| Application accuracy | `application` equals `expected_application` on the 85 should-pass tickets | ≥ 0.90 | < 0.80 |
| Draft accept rate | drafts accepted or lightly edited (< 20% of characters changed) by the named rater | ≥ 10 / 15 before ship; ≥ 60% in production | < 40% over a week |
| LLM skip rate | tickets decided by rules alone | reported (*measured* baseline 51%) | none |
| p95 latency per ticket | ingest to verdict stored | ≤ 60 s, dashboard line | none; it is a background job |

**Rater.** The support lead, or a rota engineer who did not write the prompt, rates drafts and counts spurious asks. The author of the prompt does not rate.

**Borderline rows.** Three of the 15 are marked "application can be inferred but key details missing". They must not `pass`; `needs_info` or `needs_review` both count as caught.

**Feedback loop.** Every accept, edit or reject lands in `agent_runs.decision`, `reject_reason` and `edited_value`. Weekly, a script pulls rejected and heavily edited runs into `evaluation/dq_review.xlsx` for the support lead to label; labelled rows join the holdout. Nothing is auto-promoted.

## 3. Shape of the system

```
ingest (exists) ──► tickets.pipeline_status = pending
                              │
                              ▼
         run_ticket()  (plain function, nodes in order)
          prepare ─► rules ─┬─ pass ─────────────────► record ─► dq_passed
           (code)   (code)  ├─ not_an_incident ──────► record ─► not_an_incident
                            ├─ service_request ──────► record ─► service_request
                            └─ needs_info / uncertain
                                      ▼
                                   assess (one model call: verdict + questions)
                                      ▼
                                compose (code: email from questions + template)
                                      ▼
                                   record ─► agent_runs row, status = proposed
                                      │
              human on the review page: accept / edit / reject(reason)
                                      ▼
                                 pipeline_status = needs_info | dq_passed | ...

      requester replies (v0.2) ─ re-ingest ─► input hash changes ─► run_ticket() again
```

| Capability | Shape | Reason |
|---|---|---|
| Load, redact, guess application | code | Deterministic, auditable, runs when AI is off |
| Signals and rules | code | *Measured*: 14 of 15 bad tickets caught, 37 of 85 good ones cleared, zero errors, for free |
| Assess: verdict, missing items, one question each | workflow step: one structured model call | Needs language understanding of a 70-character email and app-specific questions |
| Compose the email | code | A template with numbered questions. No reason for a model to write a letter |
| Human accept / edit / reject | gate, status on the run row | Advisory only, by project rule |
| Record and hand off | code | One row per (ticket, agent, input hash, prompt version) |
| Reply re-check (v0.2) | same function, new input hash | Needs a mailbox or ServiceNow poll first |

Nothing runs in parallel. Nothing runs on its own clock in v0.1; the two-day reminder from the design repo is deferred.

**On LangGraph.** The original request asked for it, the design repo bans it, and the review found the v0.1 justification did not hold: the only thing it buys is resume on reply, which is v0.2. So v0.1 is `run_ticket()` calling five plain functions, and the gate is `agent_runs.status = proposed`. When the reply path is built, the engineers evaluate LangGraph against "call the same function with the new text" and adopt it only if the resume semantics are worth a dependency and a second state store. Either way the decision is dated and written in `docs/adr/0001-orchestration.md`, and ARCHITECTURE.md in the design repo is updated to match. The nodes do not change under either answer.

## 4. Each step in detail

### prepare (code, Presidio + spaCy)

Decides: the redacted text the model may see, and the application guess.
On what: the client's PII class list (open question 2; assumed to include at least names, contact details and employee IDs), applied with Microsoft Presidio running in process. Nothing leaves the service, so this step does not touch the residency question.

- **Analyzer.** Presidio Analyzer with the spaCy large English model (`en_core_web_lg`) for `PERSON` and `LOCATION`, the built-in `EMAIL_ADDRESS` and `PHONE_NUMBER` recognisers (the phone recogniser uses the phonenumbers library with context scoring, so `INV-2026-91226` scores low instead of being swallowed), and custom `PatternRecognizer`s with context words for `EMPLOYEE_ID` and `CUSTOMER_NAME`. `ORG` is not in the entity list: spaCy tags PayrollPro, OrderHub and StockSense as organisations, and redacting them breaks the application guess. Every name in `apps.yaml` and every KB page title is on the allow-list.
- **Keep-list recognisers.** Order, invoice, SKU, PO, device and job identifiers (`ORD-`, `INV-`, `SKU-`, `PO-`, `HHD-`, `PAY_CALC_*` and the like) are registered as their own entity types with a higher score than the generic recognisers, so Presidio's overlap resolution keeps them. They survive intact; they are not PII.
- **Anonymizer.** Presidio Anonymizer operators per entity: `replace` for `PERSON` → `[REPORTER]` when it matches the reporter, `[PERSON_n]` otherwise; `replace` for email and phone; `[SIGNATURE]` for the sign-off block (a small custom recogniser on "Thanks & Regards" and similar); and a custom reversible operator for `EMPLOYEE_ID`, `CUSTOMER_NAME` and `LOCATION` that emits `[EMP_ID_1]`, `[CUSTOMER_1]`, `[LOCATION_1]` and writes the mapping to `redaction_tokens`. Location is tokenised rather than deleted because `location` is a taxonomy item: the model must be able to see that one is present.
- **Threshold.** Presidio returns a score per finding. The threshold is chosen on the 100 tickets in milestone 2 and re-checked on the first real batch, the same way the rules thresholds are handled.
- **Why the large model.** The sample names are South Asian (Priya Nair, Rajesh Iyengar); the small and medium English models miss more of these. The transformer model is the fallback only if the redaction eval shows the large one missing names, because it needs torch and roughly doubles the image.

Application comes from `cmdb_ci` or `components` when present, else the first keyword hit in `data/registry/apps.yaml`. Attachments: names only.

Redaction eval, run on all 100 tickets in milestone 2 and on every change to recognisers, allow-list or threshold: no reporter name, email or third-party name from the workbook survives into the stored model input; every registry application name survives untouched; and every `INV-`, `ORD-`, `SKU-`, `PO-`, device and employee identifier survives intact or as a typed token. Presidio decides how to redact; the privacy owner decides what counts (open question 2).

### rules (code)

Decides: `pass`, `not_an_incident`, `service_request`, `needs_info`, or `uncertain`.
On what: five signals computed on every ticket first, then the verdict.

Signals: `body_length` after signature stripping; `app_found`; `identifier_found` (ticket, order, invoice, device or job identifier, or an error pattern); `attachment_only` (empty body with an attachment); `summary_equals_body`; `mentions_previous_ticket` ("same issue", "again", "last week").

Verdict, in order:

1. Test blocklist (`test ticket`, `please ignore`, summary equals `Test`) → `not_an_incident`. No email; flag for a person to close.
2. Access or new-user request with nothing broken (`need access`, `grant`, `new user`, `role`) → `service_request`. No chase; routed to the request path; a person confirms.
3. `body_length` < 50 → `needs_info`. *Measured*: every should-pass ticket has at least 63; 13 of the 15 should-fail are under 50 raw, 14 after signature stripping. One of them, "The same problem as last week is happening again.", is 49 characters. The thresholds are provisional: chosen on the synthetic set, re-tuned on the first 50 real tickets.
4. `body_length` ≥ 60, `app_found`, `identifier_found` → `pass`, no model call.
5. Otherwise `uncertain` → model call.

*Measured* on 100 tickets: 37 pass, 14 fail, 49 uncertain (48 should pass, 1 should fail). Zero wrong verdicts. All signals, including `attachment_only`, reach the model as input regardless of which rule fired.

### assess (model call)

```
Step name:        assess
Trigger:          rules returned needs_info or uncertain
Rules first:      see above; 51% of tickets never reach this step (measured)
Inputs:           source, channel, application guess (or null) and whether it came from a
                  system field, redacted summary (≤ 200 chars), redacted body (≤ 2,000 chars,
                  truncated with a marker), attachment names, the six signals, the per-app
                  checklist (≤ 300 tokens) or the generic one when app is null, urgent flag
Model tier:       claude-opus-5-5, effort low (set explicitly; the model's default is medium),
                  adaptive thinking, no streaming (output ≤ 500 tokens). Reason: quality on
                  70-character tickets is the whole job and cost is irrelevant at this volume
                  (section 8). Haiku 5.5 is the first experiment against the eval, not the default.
Output schema:    below; enforced with structured outputs (output_config.format)
Validation:       below
Retry:            once, with the validation failures appended to the user turn
Fallback:         verdict needs_review with the rules signals and the generic template email;
                  a person decides. Used when the model is down, the breaker is open, the kill
                  switch is off, or the response is a refusal
Human gate:       advisory: accept / edit / reject with reason, on the review page
Stored:           model, prompt_version (hash of the prompt file), input_hash, output JSON as
                  returned, assembled subject and body, template version, latency_ms,
                  input/output/cache-read tokens, cost_usd, decision, decided_by, decided_at,
                  reject_reason, edited_value
```

Output schema:

```json
{
  "actionable": false,
  "application": "PayrollPro",
  "not_an_incident": false,
  "service_request": false,
  "missing": [
    {"item": "symptom", "why": "says 'check my salary' with nothing about what is wrong",
     "question": "What looks wrong with your salary: the amount, a missing allowance, or something else?"},
    {"item": "period", "why": "no pay period named",
     "question": "Which pay period is affected, for example October 2026?"},
    {"item": "identifier", "why": "no employee ID",
     "question": "What is your employee ID, so we can look up the payslip?"}
  ],
  "schema_version": 1
}
```

The model does not write the email. The model does not see or produce the ticket number, the requester's name, or any address.

Validation, in code after the schema check:

- `actionable == false` if and only if `missing` is non-empty or `not_an_incident` or `service_request`.
- `not_an_incident` or `service_request` implies `missing` is empty.
- `application` is in the registry or null. If the application guess came from `cmdb_ci` or `components`, `application` must equal it: the model may fill a null, not overrule a system field.
- `missing[].item` is in the taxonomy and unique within the list; 1 to 5 items.
- Each `question`: ends with `?`, at most 200 characters, no URL, no `@`, no digit run longer than 4, no redaction token, none of `password`, `OTP`, `PIN`, `card number`.
- No `question` asks for an item the signals found present: `identifier_found` rules out the `identifier` item unless `why` names a second identifier type.

Prompt hygiene: one system prompt file, `app/agents/data_quality/prompts/v1.md`: role, the rules of a question (plain words, no blame, one thing per question, never ask for a password or card number), the taxonomy with one line each, the schema. Cache breakpoint after that block. The per-app checklist and the ticket come after it, uncached, because at 20 calls a day across seven apps a per-app prefix would almost never be read. The ticket text is labelled as data; nothing in it can change the schema or cause an action.

### compose (code)

Decides: the subject and body a person sees. Runs only when `missing` is non-empty.
On what: `data/registry/dq_email_template.md`:

```
subject:  [{ticket_ref}] A few details so we can start on your {app_label} ticket
body:     Hi {reporter_first_name},

          Thanks for raising {ticket_ref}. To look into this we need {n} thing(s):

          1. {question 1}
          2. {question 2}
          ...

          Reply to this email and we will pick it up straight away.

          AMS Support
```

`app_label` is the registry display name, or "support" when the application is null. `reporter_first_name` is filled from `tickets.reporter_name` at render time on the review page, never passed to the model; "there" if the name cannot be split.

### gate (human, on the review page)

One HTMX page served by this app: the ticket unredacted (the reviewer is internal), the verdict and why, the assembled email with the real first name, a textarea, and three buttons that call `POST /api/v1/agent_runs/{id}/decision`. Accept and edit show the final text with a copy button and a `mailto:` link as a convenience; the person sends it from their own client.

Reject takes a reason:

| Reason | Meaning | Resulting status |
|---|---|---|
| `ticket_is_fine` | the verdict was wrong | `dq_passed` |
| `draft_unusable` | the verdict was right, the questions were not; reviewer writes their own, stored as `edited_value` | `needs_info` |
| `wrong_application` | reviewer corrects the app; the ticket is re-run with it | `pending`, re-run once |

### record (code)

Decides: the `agent_runs` row and `pipeline_status`.
On what: `pass` → `dq_passed`; accepted or edited draft → `needs_info`; `not_an_incident` and `service_request` → the same name, for a person to close or route; `needs_review` → stays `pending` with the run row visible on the page; reject → the table above. Unique on (`ticket_id`, `agent`, `input_hash`, `prompt_version`). Selection skips any ticket whose latest `data_quality` run has a human decision unless `input_hash` changed, so a prompt bump never re-chases a requester and a reply always re-runs.

**Hand-off to Triage:** `dq_verdict`, `missing[]`, `application`, `urgent`. Triage selects `pipeline_status = dq_passed OR urgent = true`; an urgent ticket that failed data quality is triaged and chased at the same time.

## 5. Data and knowledge

| Item | Where | Owner | Freshness |
|---|---|---|---|
| Tickets, common format | `tickets` table (exists) | ingestion | per ingest run |
| Agent runs | `agent_runs`, extended per the code review plus `status`, `reject_reason`, `input_hash`, `template_version` | this agent | per run |
| Identifier token map | `redaction_tokens` table: run id, token, original value | this agent | per run; same retention as the run |
| App registry | `data/registry/apps.yaml`, derived once from the KB pages | support lead | reviewed when an app is added |
| Per-app checklist | `data/registry/dq_checklists.yaml` | support lead | same |
| Email template | `data/registry/dq_email_template.md`, versioned by hash | support lead | same |
| Prompt | `app/agents/data_quality/prompts/v1.md`, hashed into `prompt_version` | engineering | per change, through the eval |
| Eval set and taxonomy map | `evaluation/ground_truth.xlsx`, `evaluation/dq_taxonomy.yaml`, `evaluation/holdout/` | engineering with the support lead | per labelled batch |

There is no checkpoint store in v0.1. Retrieval: not applicable, because the agent needs a 300-token checklist per application, not search.

Retention: the redacted model input, the model output, the assembled email, `edited_value` (which may hold the requester's first name after an edit) and the token map are kept 90 days for debugging, then deleted; the hash, verdict, decision and tokens-and-cost figures are kept. Raw ticket text already lives in `tickets.raw` under the ticket's own retention.

Access: the service database and the review page are reachable by the rota team only; the answer key stays outside `data/`.

## 6. Guardrails

- **PII.** The class list comes from the client's privacy owner (open question 2), not from this plan. Redaction in `prepare` is Presidio with spaCy NER, in process, logged per entity type, with an allow-list for application names and keep-list recognisers for business identifiers. The redaction eval in section 4 runs in milestone 2 and on every change to recognisers, allow-list or threshold. Third-party names in the body are covered by the NER pass from milestone 2, not left to a regex.
- **Untrusted input.** The ticket body is user-written. The system prompt labels it as data, the output is schema-constrained with no tools, the model never writes free text that a person forwards, and the question validator rejects URLs, redaction tokens and credential words.
- **Advisory vs automated.** Verdict and `pipeline_status` are internal state and are written automatically. The email is advisory. Nothing touches the source systems.
- **Never automated.** Sending email. Closing a `not_an_incident` ticket. Routing a `service_request`. Any ServiceNow or JIRA write.
- **Kill switch.** `LLM_ENABLED` (global, the design repo's one switch) and `DQ_LLM_ENABLED` (per agent), read from the environment or a settings row on every run, never cached at import. Off → `assess` is skipped, verdict `needs_review`, the queue keeps moving.
- **Audit.** One `agent_runs` row per run with everything listed under Stored. The proposed-versus-accepted gap is a query.
- **Residency and vendor.** The first-party API cannot pin inference to Canada, so the route under the project rule is the vendor's Bedrock client in a Canadian region, if the model is served there. Refusal fallback on that platform is the SDK's client-side middleware, not the server-side parameter. Verified by: ______ on ______ (fill in before any real ticket).

## 7. Operations

- **Queue and idempotency.** v0.1 is a CLI, `python -m app.agents.run data_quality`, selecting as in section 4 and processing in order. Idempotency is the unique key plus the selection rule. A scheduled background task is the v0.2 trigger; a queue table with `SKIP LOCKED` is the Postgres-day answer.
- **Model gateway.** The vendor SDK with `max_retries=2`, timeout 60 s. Circuit breaker: five consecutive failures open it for the rest of the run and route to the fallback; because the CLI exits per batch, the breaker is per run, which is acceptable at this volume and is written here so nobody expects more. Token usage read from the response on every call.
- **Observability.** Structured log per run: ticket id, request id, verdict, model, prompt version, latency, tokens, cost, skip reason, redaction counts. Dashboard (a SQL view): tickets per day, verdict mix, LLM skip rate, accept / edit / reject rate with reasons, application accuracy on tickets with a system field, p95 latency, cost per day.
- **Versioning.** Prompt file hash is `prompt_version`; `schema_version` is in the output; template hash is `template_version`. Changing any of them creates new runs on tickets without a decision and leaves decided tickets alone.
- **Runbook headings.** Model down or breaker open. False-fail spike. Redaction miss reported. Re-run after a prompt change. Rotating the API key. Turning the LLM off. Clearing the 90-day data.

## 8. Cost and latency

Per model call (*guess* on token counts; firmed up with the token-count endpoint on the real prompt in milestone 2):

| Part | Tokens | Price (vendor list, first party) | Cost |
|---|---|---|---|
| System prompt, taxonomy, schema (cached) | 1,100 | $0.20 / M cache read | $0.0002 |
| Checklist, signals, ticket (uncached) | 900 | $4 / M | $0.0036 |
| Output including thinking at low effort | 800 | $20 / M | $0.016 |
| **Per call** | | | **≈ $0.020** |

Volume: 40 tickets a day as a ceiling (*guess*; the sample suggests 8 to 10) × 49% reaching the model (*measured*) ≈ 20 calls a day → **$0.40 a day, about $12 a month**, plus 10% for retries. Haiku 5.5 would be under $1 a month; that is the experiment, not the default, because the quality bar is the product and $12 is not a design input. Partner pricing on the residency route will differ; the table is redone when question 1 is answered.

Latency: one call with about 800 output tokens on an Opus-tier model, 12 to 20 s (*guess*). The step is not user-facing. p95 target 60 s per ticket, as a dashboard line.

Human time replaced: about 3 minutes per bad ticket to read, guess the app and write the chase, times 15% of 40 tickets, is 18 minutes a day at the ceiling. The real value is the design repo's: fewer tickets sitting for days on a vague reply.

## 9. Stack

| Component | Decision | Why a library or platform feature did not do |
|---|---|---|
| FastAPI, SQLAlchemy, SQLite, ingestion, `Ticket`, `AgentRun` | reused | They exist and work; `AgentRun` extended per the code review and section 5 |
| Vendor Python SDK, Bedrock client class on the residency route | added | Structured outputs, caching, usage, retries and the refusal middleware are built in |
| `presidio-analyzer`, `presidio-anonymizer` | added | PII detection with pattern recognisers plus NER, custom recognisers, allow-lists, overlap resolution and reversible operators, all in process. Writing that by hand is the regex that ate invoice numbers |
| spaCy with `en_core_web_lg` (about 560 MB) | added | The NER model Presidio runs; the large model for recall on non-Anglo names. The Docker image grows by about that much; the transformer model is the fallback only if the eval demands it |
| `pydantic` (exists) | schema for the model output and the registry files | nothing custom |
| `PyYAML` | registry files | editable by the support lead without a deploy |
| `jinja2` + HTMX | the review page | one template, three buttons, served by the app that already exists |
| `evaluation/score.py` | new, about 200 lines | scoring is specific to our answer key and taxonomy |

Explicitly not used in v0.1: LangGraph and its checkpoint store (deferred to the v0.2 decision; no second database); LangChain; any vector store; Celery, Redis or a broker; a second model call for the email; an agent loop with tools; `confidence` in the schema (nothing routes on it).

Thrown away: nothing. Changed: `AgentRun` columns, `pipeline_status` values, the ingestion update branch (stale status bug from the code review), the README line that says the agent is LangGraph.

## 10. Delivery

| Milestone | Days | Demo | Number from section 2 |
|---|---|---|---|
| M0 Foundations | 1 | `agent_runs` migration and the token-map table applied; taxonomy map; `apps.yaml`, `dq_checklists.yaml` and the email template drafted from the KB pages; ADR 0001 written; eval harness runs and prints zeros | harness runs on all 100 |
| M1 Rules only | 2 | `--rules-only` over 100 tickets; verdicts in the table | fail recall 14 / 15, false fails 0 / 85, reproduced by the harness |
| M2 One model call | 3–4 | Presidio wired into prepare with the allow-list, keep-list recognisers and threshold chosen on the 100; redaction eval green; the 49 uncertain tickets assessed; questions and assembled emails printed for the 15; token counts measured | 15 / 15, ≤ 2 false fails, F1 ≥ 0.75, application ≥ 0.90 on the tuning set; marked "not yet met" until ≥ 7 holdout tickets are scored |
| M3 Gate | 5–6 | review page; a named rater accepts, edits or rejects all 15 with reasons; decided tickets skipped on re-run; a prompt bump re-chases nobody | draft accept ≥ 10 / 15; spurious asks ≤ 0.3 |
| M4 Hardening | 7 | kill switches, breaker, cost and latency in logs, runbook, Haiku 5.5 experiment, transformer NER model tried only if the redaction eval shows the large model missing names | cost per ticket reported; p95 on the dashboard; Haiku result recorded either way |

Deferred, with the evidence that pulls it forward:

- Reply re-check and the two-day reminder: when a mailbox or ServiceNow poll exists. The orchestration decision (LangGraph or not) is made then.
- Reading attachments (two of the 15 are screenshot-only): when question 7 says attachments may be sent to the model.
- Postgres and a job queue: when there is more than one worker or more than one service writing.

## 11. Risks

| # | Risk | Likelihood | Impact | Mitigation in this plan |
|---|---|---|---|---|
| 1 | The 15 synthetic negatives are the tuning set and the holdout does not exist yet | high | medium | Bars marked not met until 7 holdout tickets; thresholds marked provisional; weekly labelled feedback |
| 2 | Good tickets get chased and requesters lose trust | medium | high | ≤ 2 / 85 bar, spurious-ask count, named rater, human gate on every email, rollback at 5% in production |
| 3 | A name or identifier reaches the model on a real ticket | low once the eval is green | high | PII list from the owner, Presidio with NER from milestone 2, allow-list and keep-list, typed tokens, redaction eval on every change, pilot on synthetic data only |
| 4 | No Canadian endpoint serves the chosen model | unknown | blocks production | Verified before any real ticket; the code path is one client class plus the refusal middleware; Haiku becomes the baseline if needed |
| 5 | The orchestration question reopens at v0.2 and stalls the reply path | medium | low | ADR 0001 names the criteria now; nodes are plain functions either way |

## 12. Open questions

1. **Which endpoint satisfies the Canadian-region rule, and does it serve Opus 5.5 with structured outputs?** The client's security lead and the vendor's availability page. If a Canadian Bedrock region: refusal fallback is client-side and the cost table is redone at partner prices. If nothing qualifies: the model list changes and the Haiku experiment becomes the baseline.
2. **What is the client's PII class list, and are employee IDs, sites and third-party names on it?** The client's privacy owner. The answer sets Presidio's entity list and which entities are tokenised versus replaced. Presidio decides how; the owner decides what.
3. **Is LangGraph a stakeholder constraint or a preference?** The person who asked for it and the architect of the design repo. Constraint: it returns in v0.2 with the checkpoint store in the data and retention tables, and ARCHITECTURE.md updated. Preference: the v0.2 decision is made on the reply path's merits. Either way ADR 0001 is written in M0.
4. **Can the support lead give 7 to 14 real incomplete tickets before M2 ends, and will they rate the drafts?** The support lead. Without them M2's bar stays "not yet met" and the plan says so on the page.
5. **How does Triage pick up an urgent ticket that failed data quality?** The product owner. The plan's answer is the selection query in section 4; if the product owner wants a bypass instead, it is one early exit in `rules`.
6. **Is a request for access an incident, a service request, or out of scope?** The support lead. Decides whether `service_request` keeps its own route or such tickets are chased like any other.
7. **Who sends the chase, from which mailbox, does the source ticket move to On Hold, and may attachments be sent to the model?** The support lead and the client's data owner. Decides whether the review page needs more than copy, whether a ServiceNow write ever enters scope (not in v0.1), and whether the vision step comes forward.
8. **What is the real daily volume?** The support lead. Under 200 a day nothing changes; the sample suggests 8 to 10, so 40 is a ceiling, not a plan.
