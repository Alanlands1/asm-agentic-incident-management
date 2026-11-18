import { Json } from "@/types/admin";

/** Words for one field of a reference document. `template` is what "Add" creates in an empty list or map. */
export interface Hint {
  label?: string;
  help?: string;
  /** What one entry is called on the Add button: "Add rule". */
  item?: string;
  template?: Json;
  multiline?: boolean;
}

// Keyed by `<document>.<path>` (list indices and user-named keys as `*`), or by a bare field name used in many places.
const HINTS: Record<string, Hint> = {
  // Fields shared by rules in several documents
  name: { label: "Name", help: "Short id, shown in results and the change history" },
  about: { label: "What it means", help: "Shown to the engineer and the model" },
  kb: { label: "Knowledge base article" },
  match: { label: "Matches when the text contains", help: "Regular expressions, case-insensitive. Any one is enough." },
  priority: { label: "Priority", help: "1 = critical … 5 = planning" },
  single: { label: "One person affected" },
  wide: { label: "Many people affected" },
  raise: { label: "Raised when", item: "alternative", help: "The first alternative whose conditions all hold sets the priority to “Raise to”", template: { to: 2, context: [] } },
  to: { label: "Raise to" },
  context: { label: "Ticket also mentions", help: "Patterns; any one" },
  window: { label: "Only inside the window" },
  scope: { label: "Only when the scope is" },
  needs: { label: "Facts needed first", help: "Until these are known the model is asked once; the rule cannot settle the ticket alone" },
  tier: { label: "Tier", help: "1 = business critical … 3 = reporting" },
  ceiling: { label: "Most severe allowed priority" },
  rules: { label: "Rules", item: "rule", help: "The most severe match wins", template: { name: "", kb: "", about: "", match: [], priority: 3 } },
  names: { label: "Also written as", help: "Case-insensitive, whole words, optional plural" },
  keywords: { label: "Keywords", help: "Point to it but are never masked" },
  app: { label: "Application" },
  criticality: { label: "Criticality", help: "critical, normal or rerunnable_next_day" },
  critical_in: { label: "Critical inside the window", help: "A window from the Triage rules. Omitted = critical at any time." },
  breaks: { label: "What stops when it fails" },
  storm: { label: "Fires for a storm ticket" },
  critical_job: { label: "Fires when a critical job failed in its window" },
  rule: { label: "Fires when this rule is chosen" },
  version: { label: "Version", help: "Bump on any change: tickets are re-checked and every verdict records it" },
  max_tokens: { label: "Max tokens", help: "Includes thinking" },
  system: { label: "System prompt", multiline: true },
  ticket_template: { label: "Ticket layout", help: "{name} placeholders are filled by the code; keep them", multiline: true },
  wrapper: { label: "Ticket wrapper", multiline: true },
  retry_note: { label: "Retry note", multiline: true },
  not_given: { label: "Shown when a value is empty" },
  found_in_text: { label: "Application found by keyword" },
  identifier_yes: { label: "Identifier present" },
  identifier_no: { label: "No identifier" },
  target_hours: { label: "Target (hours)" },
  window_min: { label: "Window (minutes)" },
  people_needed: { label: "Reporters needed" },
  from_day: { label: "From day of month" },
  last_days: { label: "Last days of the month" },
  first_days: { label: "First days of the month" },
  months: { label: "Months" },

  // Data Quality rules
  "data_quality_rules.min_body_length": { label: "Minimum description length", help: "Characters, after greeting, signature and filler are removed. Shorter needs more information." },
  "data_quality_rules.placeholder": { label: "Placeholder descriptions", help: "A description that is only one of these needs more information. Case and punctuation are ignored." },
  "data_quality_rules.filler": { label: "Filler phrases", help: "Add no detail; removed before the length is measured. Regular expressions." },
  "data_quality_rules.test_ticket": { label: "Test tickets", help: "A summary or description matching any of these is not an incident" },
  "data_quality_rules.ticket_reference": { label: "Ticket references", help: "Our own ticket ids; not counted as identifiers" },
  "data_quality_rules.previous_ticket": { label: "Earlier-ticket phrases" },
  "data_quality_rules.identifier": { label: "Identifiers", help: "Error codes, record and device ids, job names, employee ids. Case-sensitive." },

  // Triage rules
  "triage_rules.tone": { label: "Reporter urgency words", help: "Removed before any matching: they say nothing about impact" },
  "triage_rules.scope": { label: "Scope words", help: "How many are affected" },
  "triage_rules.scope.wide": { label: "Many people" },
  "triage_rules.scope.single": { label: "One person" },
  "triage_rules.must_follow": { label: "Must-follow rules", item: "rule", help: "Applied last, so no ceiling can cap them. The most severe that fires wins.", template: { name: "", about: "", priority: 1, match: [] } },
  "triage_rules.generic": { label: "Generic rules", item: "rule", help: "When no application rule matches: priority by scope, then the tier offset", template: { name: "", about: "", match: [], priority: { single: 3, wide: 2 } } },
  "triage_rules.tier_offset": { label: "Tier offset", help: "Generic priorities are tuned for Tier 1; lower tiers move this many levels down" },
  "triage_rules.default_tier": { label: "Default tier", help: "When the application is unknown" },
  "triage_rules.review_shift": { label: "Review when shifted by", help: "Recommendations further than this from the reporter's priority are flagged for a person" },
  "triage_rules.windows": { label: "Calendar windows", item: "window", help: "Day ranges are calendar days", template: { from_day: 20 } },
  "triage_rules.applications": { label: "Application rules", item: "application", help: "Only the ticket's application is checked. The most severe match wins; a raise can only raise.", template: { tier: 2, rules: [] } },

  // Batch jobs
  "triage_jobs.failed": { label: "Failure words", help: "A job name within 60 characters of one of these counts as a failure" },
  "triage_jobs.jobs": { label: "Batch jobs", item: "job", template: { app: "", names: [], criticality: "normal", breaks: "" } },

  // Prompts
  "data_quality_prompts.dq_completeness": { label: "Data Quality: completeness check" },
  "data_quality_prompts.triage_priority": { label: "Triage: facts for the priority", help: "{rulebook} is filled from the Triage rules and batch jobs" },

  // Applications
  apps: { item: "application", template: { names: [], keywords: [] } },

  // Privacy
  "pii.spacy_model": { label: "spaCy model" },
  "pii.score_threshold": { label: "Score threshold", help: "Presidio confidence needed. Phone numbers score about 0.4." },
  "pii.entities": { label: "Built-in entities", help: "Presidio entity → placeholder label" },
  "pii.patterns": { label: "Custom patterns", help: "Placeholder label → regular expressions, case-sensitive", template: [] },
  "pii.protect": { label: "Never masked", help: "Error codes, record ids, job names, internal systems. Application names are protected too." },
  "pii.keep": { label: "Not a person", help: "Words spaCy mistakes for people in tickets" },
  "pii.system_accounts": { label: "System accounts", help: "Callers that are shared accounts, not people" },

  // SLA
  "sla.priorities": { label: "Targets by priority", item: "priority", template: { target_hours: 8 } },
  "sla.watch_at": { label: "Watch at", help: "Share of the target used" },
  "sla.breach_likely_at": { label: "Breach likely at", help: "Share of the target used. At 1.0 or more: breached." },
  "sla.first_message_minutes": { label: "First message within (minutes)" },
  "sla.update_every_minutes": { label: "Next update every (minutes)" },
  "sla.first_message": { label: "First message", help: "Placeholders: {application}, {what}, {who}, {ticket_id}, {next_update}", multiline: true },

  // Storms
  "storms.default": { label: "Default thresholds" },
  "storms.applications": { label: "Per-application thresholds", item: "application", template: { window_min: 30, people_needed: 5 } },
  "storms.quiet_min": { label: "Closes after (minutes)", help: "A storm closes after this long without a new ticket" },
  "storms.similar_text": { label: "Similar text", help: "Share of words two tickets must share to count as the same issue" },
  "storms.cross_app": { label: "Cross-application patterns", help: "Tickets matching one group are compared across applications", template: [] },
};

/** Most specific first: the document path, then the bare field name. */
export function hintFor(doc: string, path: string[]): Hint {
  const full = HINTS[[doc, ...path].join(".")];
  const last = path[path.length - 1];
  return full ?? (last ? HINTS[last] : undefined) ?? {};
}

export function humanize(key: string): string {
  const s = key.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
