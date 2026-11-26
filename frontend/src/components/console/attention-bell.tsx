"use client";

import Link from "next/link";
import { Bell } from "lucide-react";
import { useAttention } from "@/hooks/use-attention";
import { useViewAs } from "@/lib/view-as";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** In the top bar for admin and lead while a storm is open or a P1/P2 has no sent first message. Silent on errors. */
export function AttentionBell() {
  const role = useViewAs();
  const { data } = useAttention();
  if (role === "engineer" || !data || data.count === 0) return null;
  const waiting = data.p1_p2.filter((i) => !i.last_sent).length;
  const parts = [
    data.storms.length > 0 && plural(data.storms.length, "storm", "storms"),
    waiting > 0 && `${plural(waiting, "P1/P2 ticket", "P1/P2 tickets")} without a first update to the requester`,
  ].filter(Boolean);
  const label = `${data.count} need attention: ${parts.join(", ")}. Open Incidents`;
  return (
    <Link
      href="/incidents"
      aria-label={label}
      title={label}
      className="relative grid size-11 shrink-0 place-items-center rounded-full border border-border bg-card text-foreground transition-colors duration-[80ms] hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
    >
      <Bell className="size-5" aria-hidden="true" />
      <span
        aria-hidden="true"
        className="absolute -top-0.5 -right-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full border-2 border-background bg-primary px-1 text-[11px] font-bold tabular-nums text-primary-foreground"
      >
        {data.count}
      </span>
    </Link>
  );
}
