"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PRIORITY_GROUPS, PriorityGroup, ServicePerformance } from "@/types/service";
import { ChartCard, LegendKey } from "./chart-card";
import { ChartTooltip } from "./chart-tooltip";
import { count, hours, month, percent } from "./format";

// Priority is ordinal: one hue, P1 most prominent (validated light and dark, see globals.css).
export const PRIORITY_COLOR: Record<PriorityGroup | "Unprioritised", string> = {
  P1: "var(--viz-p1)",
  P2: "var(--viz-p2)",
  P3: "var(--viz-p3)",
  "P4–P5": "var(--viz-p4)",
  Unprioritised: "var(--viz-muted)",
};
const SLA_TARGET = 0.95; // provisional contract target for the share of P1/P2 resolved in time
const axis = { tick: { fill: "var(--muted-foreground)", fontSize: 11 }, axisLine: false, tickLine: false } as const;
const grid = <CartesianGrid vertical={false} stroke="var(--viz-grid)" />;
const crosshair = { stroke: "var(--border-strong)", strokeWidth: 1 };
const barHover = { fill: "var(--muted)", opacity: 0.6 };
const H = 240;

type Data = ServicePerformance;

/** Opened against resolved per month: are we keeping up with demand? Resolved is the point (accent), opened is context. */
export function OpenedResolved({ data }: { data: Data }) {
  const m = data.monthly;
  const rows = m.months.map((key, i) => ({ key, opened: m.opened[i], resolved: m.resolved[i] }));
  return (
    <ChartCard
      title="Opened vs resolved"
      description="Incidents per month, the last 12 months. Resolved above opened means the backlog is shrinking."
      file="opened-vs-resolved"
      legend={
        <>
          <LegendKey color="var(--viz-accent)" label="Resolved" line />
          <LegendKey color="var(--viz-muted)" label="Opened" line />
        </>
      }
      table={{ columns: ["Month", "Opened", "Resolved"], rows: rows.map((r) => [month(r.key, true), r.opened, r.resolved]) }}
    >
      <ResponsiveContainer width="100%" height={H}>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          {grid}
          <XAxis dataKey="key" tickFormatter={(k) => month(k)} {...axis} />
          <YAxis allowDecimals={false} {...axis} />
          <Tooltip cursor={crosshair} content={<ChartTooltip line title={(k) => month(k, true)} value={(v) => count(v)} />} />
          <Line name="Opened" dataKey="opened" stroke="var(--viz-muted)" strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }} />
          <Line name="Resolved" dataKey="resolved" stroke="var(--viz-accent)" strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }} />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

const priorityLegend = (groups: readonly (PriorityGroup | "Unprioritised")[]) => groups.map((g) => <LegendKey key={g} color={PRIORITY_COLOR[g]} label={g} />);

/** How many P1, P2, P3 and P4–P5 were resolved each month. */
export function ResolvedByPriority({ data }: { data: Data }) {
  const m = data.monthly;
  const rows = m.months.map((key, i) => ({ key, ...Object.fromEntries(PRIORITY_GROUPS.map((g) => [g, m.resolved_by_priority[g][i]])) }));
  return (
    <ChartCard
      title="Resolved by priority"
      description="Incidents resolved per month, split by the priority in force."
      file="resolved-by-priority"
      legend={priorityLegend(PRIORITY_GROUPS)}
      table={{
        columns: ["Month", ...PRIORITY_GROUPS, "Total"],
        rows: m.months.map((key, i) => [month(key, true), ...PRIORITY_GROUPS.map((g) => m.resolved_by_priority[g][i]), m.resolved[i]]),
      }}
    >
      <ResponsiveContainer width="100%" height={H}>
        <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          {grid}
          <XAxis dataKey="key" tickFormatter={(k) => month(k)} {...axis} />
          <YAxis allowDecimals={false} {...axis} />
          <Tooltip cursor={barHover} content={<ChartTooltip title={(k) => month(k, true)} value={(v) => count(v)} />} />
          {PRIORITY_GROUPS.map((g, i) => (
            <Bar
              key={g}
              dataKey={g}
              name={g}
              stackId="p"
              fill={PRIORITY_COLOR[g]}
              stroke="var(--card)"
              strokeWidth={1}
              maxBarSize={24}
              radius={i === PRIORITY_GROUPS.length - 1 ? [4, 4, 0, 0] : 0}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

/** Mean time to resolve per month, one small chart per priority (the scales differ too much to share an axis). */
export function MttrByPriority({ data }: { data: Data }) {
  const m = data.monthly;
  return (
    <ChartCard
      title="Mean time to resolve by priority"
      description="Average hours from opened to resolved, per month. The dashed line is the SLA target where the priority has one."
      file="mttr-by-priority"
      table={{
        columns: ["Month", ...PRIORITY_GROUPS],
        rows: m.months.map((key, i) => [month(key, true), ...PRIORITY_GROUPS.map((g) => m.mttr_by_priority[g][i])]),
        format: (v, col) => (col === 0 ? String(v) : hours(v as number | null)),
      }}
      className="lg:col-span-2"
    >
      <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2 xl:grid-cols-4">
        {PRIORITY_GROUPS.map((g) => {
          const target = data.sla_targets[g];
          const rows = m.months.map((key, i) => ({ key, v: m.mttr_by_priority[g][i] }));
          return (
            <figure key={g} className="flex flex-col">
              <figcaption className="px-3 text-xs font-semibold">
                {g}
                <span className="font-normal text-muted-foreground">{target ? ` · SLA ${target} h` : " · no SLA target"}</span>
              </figcaption>
              <ResponsiveContainer width="100%" height={150}>
                <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
                  {grid}
                  <XAxis dataKey="key" tickFormatter={(k) => month(k)} interval="preserveStartEnd" minTickGap={24} {...axis} />
                  <YAxis tickFormatter={(h) => `${h}h`} {...axis} />
                  {target && <ReferenceLine y={target} stroke="var(--viz-accent)" strokeDasharray="4 3" ifOverflow="extendDomain" />}
                  <Tooltip cursor={crosshair} content={<ChartTooltip line title={(k) => month(k, true)} value={(v) => hours(v)} />} />
                  <Line name={`${g} MTTR`} dataKey="v" stroke={PRIORITY_COLOR[g]} strokeWidth={2} connectNulls dot={false} activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }} />
                </LineChart>
              </ResponsiveContainer>
            </figure>
          );
        })}
      </div>
    </ChartCard>
  );
}

/** The share of P1/P2 incidents resolved within their SLA target, per month, against the contract target. */
export function SlaTrend({ data }: { data: Data }) {
  const m = data.monthly;
  const rows = m.months.map((key, i) => ({ key, v: m.sla_met[i] }));
  return (
    <ChartCard
      title="SLA compliance, P1 and P2"
      description={`Share of P1/P2 incidents resolved within target (P1 ${data.sla_targets.P1 ?? "—"} h, P2 ${data.sla_targets.P2 ?? "—"} h). The band is the ${percent(SLA_TARGET)} target (provisional).`}
      file="sla-compliance"
      table={{ columns: ["Month", "SLA met"], rows: rows.map((r) => [month(r.key, true), r.v]), format: (v, col) => (col === 0 ? String(v) : percent(v as number | null)) }}
    >
      <ResponsiveContainer width="100%" height={H}>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          {grid}
          <ReferenceArea y1={SLA_TARGET} y2={1} fill="var(--p3)" fillOpacity={0.08} ifOverflow="hidden" />
          <ReferenceLine y={SLA_TARGET} stroke="var(--p3)" strokeDasharray="4 3" />
          <XAxis dataKey="key" tickFormatter={(k) => month(k)} {...axis} />
          <YAxis domain={[0, 1]} tickFormatter={(v) => percent(v)} {...axis} />
          <Tooltip cursor={crosshair} content={<ChartTooltip line title={(k) => month(k, true)} value={(v) => percent(v)} />} />
          <Line name="SLA met" dataKey="v" stroke="var(--viz-p2)" strokeWidth={2} connectNulls dot={{ r: 4, fill: "var(--viz-p2)", stroke: "var(--card)", strokeWidth: 2 }} />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

const SEQ = ["var(--viz-seq-1)", "var(--viz-seq-2)", "var(--viz-seq-3)", "var(--viz-seq-4)", "var(--viz-seq-5)"];

/** Resolved incidents per application per month: each application's monthly resolution trend at a glance. */
export function ApplicationHeatmap({ data }: { data: Data }) {
  const m = data.monthly;
  const apps = Object.entries(m.resolved_by_application).filter(([, v]) => v.some(Boolean)).sort((a, b) => b[1].reduce((s, v) => s + v, 0) - a[1].reduce((s, v) => s + v, 0));
  const max = Math.max(1, ...apps.flatMap(([, v]) => v));
  const step = (v: number) => (v === 0 ? -1 : Math.min(4, Math.floor((v / max) * 5)));
  return (
    <ChartCard
      title="Monthly resolution by application"
      description="Incidents resolved per application and month. Darker means more."
      file="resolution-by-application"
      className="lg:col-span-2"
      table={{ columns: ["Application", ...m.months.map((k) => month(k, true)), "Total"], rows: apps.map(([app, v]) => [app, ...v, v.reduce((s, n) => s + n, 0)]) }}
    >
      <div className="overflow-x-auto px-2">
        <div className="grid min-w-[640px] gap-[2px] text-xs" style={{ gridTemplateColumns: `minmax(8rem, 1.4fr) repeat(${m.months.length}, minmax(2.5rem, 1fr))` }}>
          <span />
          {m.months.map((k) => (
            <span key={k} className="pb-1 text-center text-[11px] text-muted-foreground">
              {month(k)}
            </span>
          ))}
          {apps.map(([app, values]) => (
            <div key={app} className="contents">
              <span className="truncate py-1.5 pr-2 font-medium">{app}</span>
              {values.map((v, i) => {
                const s = step(v);
                return (
                  <span
                    key={m.months[i]}
                    title={`${app}, ${month(m.months[i], true)}: ${v} resolved`}
                    className="flex h-8 items-center justify-center rounded-[4px] tabular-nums"
                    style={{ background: s < 0 ? "var(--muted)" : SEQ[s], color: s < 0 ? "var(--foreground)" : `var(--viz-on-seq-${s + 1})` }}
                  >
                    {v || ""}
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </ChartCard>
  );
}

/** Applications by mean time to resolve in the period, slowest first: where fixes take longest. */
export function MttrByApplication({ data }: { data: Data }) {
  const rows = data.by_application.filter((r) => r.mttr_hours !== null);
  return (
    <ChartCard
      title="Mean time to resolve by application"
      description="Average hours from opened to resolved in the selected period, slowest first."
      file="mttr-by-application"
      table={{
        columns: ["Application", "Resolved", "MTTR (hours)", "SLA met (P1/P2)"],
        rows: data.by_application.map((r) => [r.application, r.resolved, r.mttr_hours, r.sla_met]),
        format: (v, col) => (col === 2 ? hours(v as number | null) : col === 3 ? percent(v as number | null) : v === null ? "—" : String(v)),
      }}
    >
      {rows.length === 0 ? (
        <p className="px-2 py-10 text-center text-[13px] text-muted-foreground">Nothing resolved in this period.</p>
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(160, rows.length * 34 + 24)}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 40, bottom: 0, left: 8 }}>
            <CartesianGrid horizontal={false} stroke="var(--viz-grid)" />
            <XAxis type="number" tickFormatter={(h) => `${h}h`} {...axis} />
            <YAxis type="category" dataKey="application" width={120} {...axis} tick={{ ...axis.tick, fill: "var(--foreground)" }} />
            <Tooltip cursor={barHover} content={<ChartTooltip title={(a) => a} value={(v) => hours(v)} />} />
            <Bar
              name="MTTR"
              dataKey="mttr_hours"
              fill="var(--viz-p2)"
              maxBarSize={20}
              radius={[0, 4, 4, 0]}
              label={{ position: "right", fill: "var(--muted-foreground)", fontSize: 11, formatter: (v: unknown) => hours(typeof v === "number" ? v : null) }}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  );
}

/** Open incidents by age and priority: where old tickets pile up. */
export function BacklogAgeing({ data }: { data: Data }) {
  const groups = [...PRIORITY_GROUPS, "Unprioritised"] as const;
  const used = groups.filter((g) => data.ageing.some((r) => r[g] > 0));
  return (
    <ChartCard
      title="Open backlog by age"
      description="Incidents open now, by how long they have been open and their priority."
      file="backlog-ageing"
      className="lg:col-span-2"
      legend={priorityLegend(used)}
      table={{ columns: ["Age", ...groups, "Total"], rows: data.ageing.map((r) => [r.age, ...groups.map((g) => r[g]), groups.reduce((s, g) => s + r[g], 0)]) }}
    >
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data.ageing} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
          <CartesianGrid horizontal={false} stroke="var(--viz-grid)" />
          <XAxis type="number" allowDecimals={false} {...axis} />
          <YAxis type="category" dataKey="age" width={80} {...axis} tick={{ ...axis.tick, fill: "var(--foreground)" }} />
          <Tooltip cursor={barHover} content={<ChartTooltip title={(a) => `Open ${a}`} value={(v) => count(v)} />} />
          {used.map((g, i) => (
            <Bar key={g} dataKey={g} name={g} stackId="a" fill={PRIORITY_COLOR[g]} stroke="var(--card)" strokeWidth={1} maxBarSize={22} radius={i === used.length - 1 ? [0, 4, 4, 0] : 0} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
