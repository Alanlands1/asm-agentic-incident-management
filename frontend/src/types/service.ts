/** Service performance (backend/app/services/service_report.py). Shares are 0..1; null where there is nothing to measure. */

export type Period = "mtd" | "last_month" | "qtd" | "ytd" | "12m";
export const PRIORITY_GROUPS = ["P1", "P2", "P3", "P4–P5"] as const;
export type PriorityGroup = (typeof PRIORITY_GROUPS)[number];

export interface ServiceMeasures {
  opened: number;
  resolved: number;
  resolved_by_priority: Record<PriorityGroup, number>;
  mttr_hours: number | null;
  median_hours: number | null;
  sla_met: number | null;
  first_fix: number | null;
}

export interface ServicePerformance {
  period: Period;
  start: string;
  end: string;
  applications: string[];
  sla_targets: Record<string, number>;
  kpis: {
    current: ServiceMeasures;
    previous: ServiceMeasures;
    backlog: number;
    backlog_past_sla: number;
    spark: Record<"opened" | "resolved" | "mttr_hours" | "sla_met" | "first_fix", (number | null)[]>;
  };
  monthly: {
    months: string[];
    opened: number[];
    resolved: number[];
    resolved_by_priority: Record<PriorityGroup, number[]>;
    mttr_by_priority: Record<PriorityGroup, (number | null)[]>;
    sla_met: (number | null)[];
    resolved_by_application: Record<string, number[]>;
  };
  by_application: { application: string; resolved: number; mttr_hours: number | null; sla_met: number | null }[];
  ageing: ({ age: string; Unprioritised: number } & Record<PriorityGroup, number>)[];
}
