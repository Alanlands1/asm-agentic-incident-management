import { Badge } from "@/components/ui/badge";

/** Map a priority ("1 - Critical", "P2", 5, ...) to a chip; unknown values render as a dash. P5 looks like P4. */
export function PriorityChip({ priority }: { priority?: string | number | null }) {
  const n = String(priority ?? "").match(/[1-5]/)?.[0];
  if (!n) return <Badge variant="secondary" className="min-w-8">—</Badge>;
  return (
    <Badge variant={`p${Math.min(4, Number(n))}` as "p1" | "p2" | "p3" | "p4"} title={typeof priority === "string" ? priority : undefined}>
      P{n}
    </Badge>
  );
}
