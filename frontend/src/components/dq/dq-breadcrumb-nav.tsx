"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Home, ShieldCheck } from "lucide-react";

export interface DQBreadcrumbItem {
  label: string;
  href?: string;
}

interface DQBreadcrumbNavProps {
  currentTab: "manage" | "execute";
  items?: DQBreadcrumbItem[];
}

export function DQBreadcrumbNav({ currentTab, items }: DQBreadcrumbNavProps) {
  const pathname = usePathname();

  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-border">
      {/* Breadcrumb path */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Link
          href="/"
          className="hover:text-foreground flex items-center gap-1 transition-colors"
        >
          <Home className="size-4" aria-hidden="true" />
          <span>Home</span>
        </Link>

        <ChevronRight className="size-4 text-muted-foreground shrink-0" />

        <Link
          href="/dq-rules"
          className="hover:text-foreground flex items-center gap-1 font-medium transition-colors"
        >
          <ShieldCheck className="size-4" aria-hidden="true" />
          <span>Data Quality Agent</span>
        </Link>

        <ChevronRight className="size-4 text-muted-foreground shrink-0" />

        <span className="font-medium text-foreground">
          {currentTab === "manage" ? "Manage Rules" : "Execute Evaluation & Runs"}
        </span>

        {items?.map((item, idx) => (
          <div key={idx} className="flex items-center gap-1.5">
            <ChevronRight className="size-4 text-muted-foreground shrink-0" />
            {item.href ? (
              <Link href={item.href} className="hover:text-foreground transition-colors">
                {item.label}
              </Link>
            ) : (
              <span className="font-medium text-foreground">{item.label}</span>
            )}
          </div>
        ))}
      </nav>

      {/* Sub-navigation tabs between Manage & Execute */}
      <div className="flex items-center gap-1">
        <Link
          href="/dq-rules"
          className={`inline-flex h-8 items-center rounded-lg border px-3 text-[13px] font-medium transition-colors duration-[80ms] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
            currentTab === "manage"
              ? "border-border-strong bg-accent font-semibold text-foreground"
              : "border-transparent text-muted-foreground hover:bg-accent hover:text-foreground"
          }`}
        >
          Manage Rules
        </Link>
        <Link
          href="/dq-rules/execute"
          className={`inline-flex h-8 items-center rounded-lg border px-3 text-[13px] font-medium transition-colors duration-[80ms] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
            currentTab === "execute"
              ? "border-border-strong bg-accent font-semibold text-foreground"
              : "border-transparent text-muted-foreground hover:bg-accent hover:text-foreground"
          }`}
        >
          Execute & Audit Runs
        </Link>
      </div>
    </div>
  );
}
