"use client";

/** One tooltip for every series at the hovered point: the value leads, the series name follows, keyed like the legend. */
export function ChartTooltip({
  active,
  payload,
  label,
  title,
  value,
  line,
}: {
  active?: boolean;
  payload?: { name?: string | number; value?: number | string | null; color?: string; dataKey?: string | number }[];
  label?: string | number;
  title?: (label: string) => string;
  value: (v: number | null, name: string) => string;
  line?: boolean;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-36 rounded-xl border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-[0_8px_20px_rgba(25,29,56,0.14)]">
      <p className="mb-1 font-semibold">{title ? title(String(label)) : label}</p>
      <ul className="flex flex-col gap-0.5">
        {[...payload].reverse().map((p) => (
          <li key={String(p.dataKey)} className="flex items-center gap-2">
            <span aria-hidden="true" className={line ? "h-0.5 w-3 rounded-full" : "size-2 rounded-[2px]"} style={{ background: p.color }} />
            <span className="font-semibold tabular-nums">{value(typeof p.value === "number" ? p.value : null, String(p.name))}</span>
            <span className="text-muted-foreground">{p.name}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
