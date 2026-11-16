import { cn } from "cn";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

// Fixed order, so a series keeps its fill whatever else is on the chart. The fourth is hollow: for a rare "Other".
const FILLS = ["bg-chart-1", "bg-chart-3", "bg-chart-4", "border border-chart-1"];

const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
export const short = (n: number) => (n >= 10000 ? compact.format(n) : n.toLocaleString());
export const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);

const dayLabel = (iso: string, weekday = false) =>
  new Date(iso).toLocaleDateString(undefined, { weekday: weekday ? "short" : undefined, day: "numeric", month: "short" });

/** The axis top: the next round number whose half is also round. */
function ceiling(n: number): number {
  const pow = 10 ** Math.floor(Math.log10(Math.max(n, 1)));
  return [2, 4, 6, 8, 10].map((s) => s * pow).find((s) => s >= n)!;
}

function Swatch({ index }: { index: number }) {
  return <span className={cn("inline-block size-2.5 shrink-0 rounded-[2px]", FILLS[index])} aria-hidden="true" />;
}

/** Stacked columns, one per day. Hover or focus a day for its numbers; the same numbers are in the table underneath. */
export function TrendChart({ days, series }: { days: string[]; series: [string, number[]][] }) {
  const totals = days.map((_, i) => sum(series.map(([, values]) => values[i])));
  if (sum(totals) === 0) return <p className="px-4 py-6 text-muted-foreground">Nothing in this period.</p>;
  const top = ceiling(Math.max(...totals));
  const many = series.length > 1;

  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      {many && (
        <ul role="list" className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {series.map(([label, values], s) => (
            <li key={label} className="inline-flex items-center gap-1.5">
              <Swatch index={s} />
              {label}
              <span className="tabular-nums text-muted-foreground">{short(sum(values))}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-2 text-xs text-muted-foreground">
        <div className="flex h-40 flex-col justify-between text-right tabular-nums leading-none" aria-hidden="true">
          <span>{short(top)}</span>
          <span>{short(top / 2)}</span>
          <span>0</span>
        </div>
        <div className="relative h-40">
          <div className="absolute inset-0 flex flex-col justify-between" aria-hidden="true">
            <span className="border-t border-border" />
            <span className="border-t border-border" />
            <span className="border-t border-border-strong" />
          </div>
          <ul role="list" className="relative flex h-full">
            {days.map((day, i) => {
              const last = series.findLastIndex(([, values]) => values[i] > 0);
              return (
                <li
                  key={day}
                  tabIndex={0}
                  aria-label={`${dayLabel(day, true)}: ${series.map(([label, values]) => `${label} ${values[i].toLocaleString()}`).join(", ")}`}
                  className="group relative flex h-full min-w-0 flex-1 justify-center outline-none hover:bg-accent focus-visible:bg-accent focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                >
                  <span className="flex h-full w-full max-w-6 flex-col-reverse gap-0.5 px-px" aria-hidden="true">
                    {series.map(
                      ([label, values], s) =>
                        values[i] > 0 && (
                          <span
                            key={label}
                            className={cn("min-h-0.5", FILLS[s], s === last && "rounded-t-[4px]")}
                            style={{ height: `${(values[i] / top) * 100}%` }}
                          />
                        ),
                    )}
                  </span>
                  <span
                    className={cn(
                      "pointer-events-none absolute top-0 z-10 hidden w-max flex-col gap-1 rounded-md border border-border-strong bg-popover px-2.5 py-2 text-xs text-popover-foreground group-hover:flex group-focus-visible:flex",
                      i < days.length / 2 ? "left-full" : "right-full",
                    )}
                    aria-hidden="true"
                  >
                    <span className="text-muted-foreground">{dayLabel(day, true)}</span>
                    {series.map(([label, values], s) => (
                      <span key={label} className="flex items-center gap-1.5">
                        <Swatch index={s} />
                        <span className="font-semibold tabular-nums">{values[i].toLocaleString()}</span>
                        {label}
                      </span>
                    ))}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
        <div className="col-start-2 mt-1.5 flex justify-between" aria-hidden="true">
          <span>{dayLabel(days[0])}</span>
          <span>{dayLabel(days[Math.floor((days.length - 1) / 2)])}</span>
          <span>{dayLabel(days[days.length - 1])}</span>
        </div>
      </div>

      <details className="text-xs">
        <summary className="w-fit cursor-pointer rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
          Show the numbers
        </summary>
        <div className="mt-2 max-h-72 overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Day</TableHead>
                {series.map(([label]) => (
                  <TableHead key={label} className="text-right">
                    {label}
                  </TableHead>
                ))}
                {many && <TableHead className="text-right">Total</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {days.map((day, i) => (
                <TableRow key={day}>
                  <TableCell>{dayLabel(day, true)}</TableCell>
                  {series.map(([label, values]) => (
                    <TableCell key={label} className="text-right tabular-nums">
                      {values[i].toLocaleString()}
                    </TableCell>
                  ))}
                  {many && <TableCell className="text-right tabular-nums">{totals[i].toLocaleString()}</TableCell>}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </details>
    </div>
  );
}
