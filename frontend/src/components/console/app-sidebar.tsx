"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BookOpen, CheckCheck, CheckCircle2, ClipboardList, Database, FileText, History, LayoutDashboard,
  ListChecks, Plug, ShieldCheck, SlidersHorizontal, Ticket, TrendingUp, TriangleAlert, Users, type LucideIcon,
} from "lucide-react";
import { cn } from "cn";
import { ROLES, useViewAs } from "@/lib/view-as";
import { REVIEW_EVENT } from "@/components/console/review-actions";
import { pipelineService } from "@/services/pipeline-service";

type NavItem = {
  label: string;
  href: string;
  step?: number;
  count?: number;
  match: (pathname: string) => boolean;
  children?: { label: string; href: string }[];
};

// Its count is the live review queue, filled in by the sidebar.
const REVIEW: NavItem = { label: "Review queue", href: "/review", match: (p) => p.startsWith("/review") };

const INCIDENTS: NavItem = { label: "Incidents", href: "/incidents", match: (p) => p.startsWith("/incidents") };

const ADMIN_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Overview",
    items: [{ label: "Home", href: "/", match: (p) => p === "/" },
      INCIDENTS,
      { label: "Trends", href: "/trends", match: (p) => p.startsWith("/trends") },
    ],
  },
  {
    label: "Tickets",
    items: [
      { label: "All tickets", href: "/tickets", match: (p) => p.startsWith("/tickets") },
      REVIEW,
      {
        label: "Rule builder",
        href: "/dq-rules",
        match: (p) => p.startsWith("/dq-rules"),
        children: [
          { label: "Rules", href: "/dq-rules" },
          { label: "Runs", href: "/dq-rules/execute" },
        ],
      },
    ],
  },
  {
    label: "Agents",
    items: [
      { label: "Data Quality", href: "/agents/data-quality", step: 1, match: (p) => p.startsWith("/agents/data-quality") },
      { label: "Triage", href: "/agents/triage", step: 2, match: (p) => p.startsWith("/agents/triage") },
      { label: "Resolution", href: "/agents/resolution", step: 3, match: (p) => p.startsWith("/agents/resolution") },
      { label: "Closure Quality", href: "/agents/closure", step: 4, match: (p) => p.startsWith("/agents/closure") },
    ],
  },
  {
    label: "Settings",
    items: [
      { label: "Jira", href: "/settings/jira", match: (p) => p.startsWith("/settings/jira") },
      { label: "Confluence", href: "/settings/confluence", match: (p) => p.startsWith("/settings/confluence") },
      { label: "Reference data", href: "/settings/reference", match: (p) => p.startsWith("/settings/reference") },
      { label: "Change history", href: "/settings/history", match: (p) => p.startsWith("/settings/history") },
    ],
  },
];

const ICONS: Record<string, LucideIcon> = {
  "/": LayoutDashboard, "/incidents": TriangleAlert, "/trends": TrendingUp, "/tickets": Ticket, "/review": CheckCircle2,
  "/dq-rules": ListChecks, "/agents/data-quality": ShieldCheck, "/agents/triage": SlidersHorizontal,
  "/agents/resolution": BookOpen, "/agents/closure": CheckCheck, "/settings/jira": Plug, "/settings/confluence": FileText,
  "/settings/reference": Database, "/settings/history": History, "/team": Users, "/my-tickets": ClipboardList,
};

// Every item a persona's menu in lib/view-as.ts can name by href.
const ITEMS: NavItem[] = [
  ...ADMIN_GROUPS.flatMap((g) => g.items),
  { label: "Overview", href: "/team", match: (p) => p.startsWith("/team") },
  { label: "My worklist", href: "/my-tickets", match: (p) => p.startsWith("/my-tickets") },
];

const itemBase =
  "relative flex h-10 items-center gap-2.5 rounded-lg px-3 text-sm font-medium text-sidebar-foreground transition-colors duration-[80ms] hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar focus-visible:outline-none";
const itemActive =
  "bg-sidebar-accent font-semibold";

interface AppSidebarProps {
  /** Called after a link is followed (used to close the mobile menu). */
  onNavigate?: () => void;
  className?: string;
}

export function AppSidebar({ onNavigate, className }: AppSidebarProps) {
  const pathname = usePathname();
  const role = useViewAs();
  const roleInfo = ROLES.find((r) => r.value === role)!;
  const groups = roleInfo.nav
    ? roleInfo.nav.map((g) => ({ label: g.label, items: g.items.map((href) => ITEMS.find((i) => i.href === href)!) }))
    : ADMIN_GROUPS;

  const [waiting, setWaiting] = useState<number>();
  useEffect(() => {
    const load = () =>
      pipelineService
        .reviewQueue()
        .then((q) => setWaiting(q.length))
        .catch(() => setWaiting(undefined)); // the link still works without the count
    load();
    window.addEventListener(REVIEW_EVENT, load);
    return () => window.removeEventListener(REVIEW_EVENT, load);
  }, [pathname]);

  return (
    <nav aria-label="Pages" className={cn("flex flex-col gap-3 rounded-[20px] bg-sidebar p-3 text-sidebar-foreground", className)}>
      <div className="-m-1 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-1">
        {groups.map((group) => (
          <div key={group.label} className="flex flex-col gap-1">
            <p className="px-3 pb-1 pt-1 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-sidebar-foreground/75">{group.label}</p>
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => {
                const active = item.match(pathname);
                const exact = pathname === item.href;
                const count = item === REVIEW ? waiting : item.count;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={exact && !item.children ? "page" : undefined}
                      aria-label={item.label}
                      title={item.label}
                      className={cn(itemBase, active && itemActive)}
                    >
                      <span className="flex min-w-0 flex-1 items-center gap-1.5">
                        {ICONS[item.href] && (() => { const Icon = ICONS[item.href]; return <Icon className="size-4 shrink-0" aria-hidden="true" />; })()}
                        <span>{item.label}</span>
                      </span>
                      {count !== undefined && (
                        <span className="ml-auto min-w-6 rounded-full bg-sidebar-primary px-2 py-0.5 text-center text-xs font-bold tabular-nums text-sidebar-primary-foreground">{count}</span>
                      )}
                    </Link>
                    {item.children && active && (
                      <ul className="mt-0.5 flex flex-col gap-0.5 pl-6">
                        {item.children.map((child) => {
                          const childActive = pathname === child.href;
                          return (
                            <li key={child.href}>
                              <Link
                                href={child.href}
                                onClick={onNavigate}
                                aria-current={childActive ? "page" : undefined}
                                className={cn(itemBase, childActive && "bg-sidebar-accent font-semibold")}
                              >
                                {child.label}
                              </Link>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-0.5 border-t border-sidebar-border pt-3">
        <a
          href="/docs"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="API docs"
          title="API docs"
          className={itemBase}
        >
          <span>API docs</span>
        </a>
      </div>
    </nav>
  );
}
