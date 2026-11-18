"use client";

import { useId } from "react";
import { useRouter } from "next/navigation";
import { cn } from "cn";
import { ROLES, setViewAs, useViewAs } from "@/lib/view-as";

/** Demo role switch (no sign-in): a pill that slides under the chosen role. */
export function RoleSwitch() {
  const role = useViewAs();
  const router = useRouter();
  const labelId = useId();
  const index = ROLES.findIndex((r) => r.value === role);
  return (
    <div className="flex items-center gap-2.5">
      <span id={labelId} className="hidden text-xs text-muted-foreground lg:inline">
        Viewing as (demo, no sign-in)
      </span>
      <div role="group" aria-labelledby={labelId} className="relative grid grid-cols-3 rounded-full border border-border bg-card p-1">
        <span
          aria-hidden="true"
          className="absolute inset-y-1 left-1 w-[calc((100%-8px)/3)] rounded-full bg-primary transition-transform duration-300 ease-out"
          style={{ transform: `translateX(${index * 100}%)` }}
        />
        {ROLES.map((r) => (
          <button
            key={r.value}
            type="button"
            aria-pressed={r.value === role}
            onClick={() => {
              setViewAs(r.value);
              router.push(r.home);
            }}
            className={cn(
              "relative h-9 rounded-full px-4 text-[13px] font-semibold transition-colors duration-200 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none sm:px-5",
              r.value === role ? "text-primary-foreground" : "text-foreground"
            )}
          >
            {r.label}
          </button>
        ))}
      </div>
    </div>
  );
}
