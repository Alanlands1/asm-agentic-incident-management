"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Menu } from "lucide-react";
import { cn } from "cn";
import { AppSidebar } from "@/components/console/app-sidebar";
import { AttentionBanner } from "@/components/console/attention-banner";
import { RoleSwitch } from "@/components/console/role-switch";
import { ThemeToggle } from "@/components/console/theme-toggle";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { ROLES, mayOpen, useViewAs } from "@/lib/view-as";

export function AppShell({ children, className }: { children: React.ReactNode; className?: string }) {
  const [menuOpen, setMenuOpen] = useState(false);

  // A page outside the role's menu sends them home. shortcut: UI lock only, the API has no sign-in; enforce there with real sessions.
  const role = useViewAs();
  const router = useRouter();
  const allowed = mayOpen(role, usePathname());
  useEffect(() => {
    if (!allowed) router.replace(ROLES.find((r) => r.value === role)!.home);
  }, [allowed, role, router]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 md:px-8">
        <div className="flex items-center gap-2.5">
          <Button variant="ghost" size="icon-lg" className="md:hidden" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
            <Menu />
          </Button>
          <span aria-hidden="true" className="flex size-8 items-center justify-center rounded-[10px] bg-primary text-sm font-bold text-primary-foreground">A</span>
          <span className="font-serif text-2xl font-semibold leading-none">AMS Console</span>
        </div>
        <RoleSwitch />
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <span className="hidden text-[13px] text-muted-foreground sm:inline">{ROLES.find((r) => r.value === role)!.person}</span>
        </div>
      </header>

      <Dialog open={menuOpen} onOpenChange={setMenuOpen}>
        <DialogContent className="top-0 left-0 h-full w-64 max-w-64 translate-x-0 translate-y-0 rounded-none border-y-0 border-l-0 p-3 sm:max-w-64">
          <DialogTitle className="sr-only">Menu</DialogTitle>
          <AppSidebar onNavigate={() => setMenuOpen(false)} />
        </DialogContent>
      </Dialog>

      <div className="flex items-start gap-5 px-4 pb-8 md:px-8">
        <aside className="sticky top-4 hidden max-h-[calc(100vh-2rem)] w-[216px] shrink-0 overflow-y-auto rounded-[20px] md:block">
          <AppSidebar />
        </aside>
        <main className={cn("flex min-w-0 max-w-[1200px] flex-1 flex-col gap-5", className)}>
          <AttentionBanner />
          {allowed && children}
        </main>
      </div>
    </div>
  );
}
