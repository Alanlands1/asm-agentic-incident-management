"use client";

import { ROLES, useViewAs } from "@/lib/view-as";

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");

/** Who the console is showing: initials, name and the role being viewed as. */
export function PersonChip() {
  const viewAs = useViewAs();
  const role = ROLES.find((r) => r.value === viewAs)!;
  return (
    <span className="hidden h-11 items-center gap-2 rounded-full border border-border bg-card py-1 pr-4 pl-1.5 sm:inline-flex">
      <span aria-hidden="true" className="grid size-8 place-items-center rounded-full bg-foreground text-xs font-bold text-background">
        {initials(role.person)}
      </span>
      <span className="flex flex-col leading-tight">
        <span className="text-[13px] font-semibold text-foreground">{role.person}</span>
        <span className="text-[11px] text-muted-foreground">{role.label}</span>
      </span>
    </span>
  );
}
