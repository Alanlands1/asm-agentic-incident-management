"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { Line, LineChart, ResponsiveContainer } from "recharts";
import { Card } from "@/components/ui/card";
import { cn } from "cn";

/**
 * A headline number: the value, its change against the previous period (green when the change is good, crimson when it
 * is bad, with an arrow and words, never colour alone), and a 6-month sparkline in grey with this month in the accent.
 */
export function KpiTile({
  label,
  value,
  detail,
  delta,
  goodWhen,
  trend,
}: {
  label: string;
  value: string;
  /** A second line under the value, e.g. the split by priority. */
  detail?: React.ReactNode;
  /** The change against the previous period, already formatted, with its raw sign. */
  delta?: { text: string; sign: number; versus: string } | null;
  /** Whether a rise is good (resolved, SLA met) or bad (opened, MTTR). */
  goodWhen?: "up" | "down";
  trend?: (number | null)[];
}) {
  const good = delta && delta.sign !== 0 && goodWhen ? (delta.sign > 0) === (goodWhen === "up") : null;
  const Arrow = !delta || delta.sign === 0 ? Minus : delta.sign > 0 ? ArrowUpRight : ArrowDownRight;
  const points = (trend ?? []).map((v, i) => ({ i, v }));
  return (
    <Card size="sm" className="min-h-36 gap-1.5 p-4">
      <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">{label}</span>
      <div className="flex items-end justify-between gap-2">
        <span className="text-[32px] leading-none font-semibold whitespace-nowrap">{value}</span>
        {points.length > 1 && (
          <div className="h-9 w-24" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
                <Line
                  dataKey="v"
                  stroke="var(--viz-muted)"
                  strokeWidth={2}
                  connectNulls
                  isAnimationActive={false}
                  dot={({ cx, cy, index }) =>
                    index === points.length - 1 && cy != null ? (
                      <circle key="now" cx={cx} cy={cy} r={4} fill="var(--viz-accent)" stroke="var(--card)" strokeWidth={2} />
                    ) : (
                      <g key={index} />
                    )
                  }
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
      {detail && <div className="text-xs text-muted-foreground">{detail}</div>}
      {delta && (
        <span className={cn("mt-auto inline-flex items-center gap-1 text-xs font-medium", good === true ? "text-[var(--viz-good)]" : good === false ? "text-[var(--viz-bad)]" : "text-muted-foreground")}>
          <Arrow className="size-3.5" aria-hidden="true" />
          {delta.text} <span className="font-normal text-muted-foreground">vs {delta.versus}</span>
        </span>
      )}
    </Card>
  );
}
