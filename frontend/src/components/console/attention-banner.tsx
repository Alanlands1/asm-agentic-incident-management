"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Siren } from "lucide-react";
import { useAttention } from "@/hooks/use-attention";
import { useViewAs } from "@/lib/view-as";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** Shown to admin and lead while a storm is open or a P1/P2 has no sent first message. Silent on errors. */
export function AttentionBanner() {
  const role = useViewAs();
  const { data } = useAttention();
  const onIncidents = usePathname().startsWith("/incidents"); // the page itself already lists them
  if (onIncidents || role === "engineer" || !data || data.count === 0) return null;
  const waiting = data.p1_p2.filter((i) => !i.last_sent).length;
  const parts = [
    data.storms.length > 0 && plural(data.storms.length, "storm", "storms"),
    waiting > 0 && `${plural(waiting, "P1/P2", "P1/P2s")} whose reporter has heard nothing yet`,
  ].filter(Boolean);
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-primary bg-selected px-4 py-2.5 text-[13px]"
    >
      <Siren className="size-4 shrink-0 text-primary" aria-hidden="true" />
      <span className="font-semibold">{data.count} need attention:</span>
      <span>{parts.join(", ")}</span>
      <Link href="/incidents" className="ml-auto font-semibold text-primary underline-offset-4 hover:underline">
        Open incidents
      </Link>
    </div>
  );
}
