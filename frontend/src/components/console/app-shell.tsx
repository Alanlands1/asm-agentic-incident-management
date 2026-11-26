"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { LogOut, Menu } from "lucide-react";
import { cn } from "cn";
import { AppSidebar } from "@/components/console/app-sidebar";
import { AttentionBell } from "@/components/console/attention-bell";
import { PersonChip } from "@/components/console/person-chip";
import { PersonaSelect } from "@/components/console/persona-select";
import { ThemeToggle } from "@/components/console/theme-toggle";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { ROLES, mayOpen, signOut, useUser } from "@/lib/view-as";

/** True once the page has scrolled, so the sticky top bar can show its bottom line. */
function useScrolled() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return scrolled;
}

export function AppShell({ children, className }: { children: React.ReactNode; className?: string }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const scrolled = useScrolled();

  // Nobody signed in goes to the sign-in page; a page outside the role's menu sends them home.
  // The API checks the session on every call, and the role where it matters (reset, assigning, lead approval, settings).
  const user = useUser();
  const role = user?.role;
  const router = useRouter();
  const pathname = usePathname();
  const allowed = role !== undefined && mayOpen(role, pathname);
  useEffect(() => {
    if (user === null) router.replace("/login");
    else if (role && !allowed) router.replace(ROLES.find((r) => r.value === role)!.home);
  }, [user, allowed, role, router]);
  if (!user) return null;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header
        className={cn(
          // Sticky only from md up: on a phone the bar wraps to three rows and would cover the page.
          "top-0 z-20 flex flex-wrap md:sticky items-center justify-between gap-3 border-b border-transparent bg-background px-4 py-3 transition-[border-color,box-shadow] duration-150 md:px-8",
          scrolled && "border-border shadow-[0_4px_12px_rgba(25,29,56,0.06)]"
        )}
      >
        <div className="flex items-center gap-2.5">
          <Button variant="ghost" size="icon-lg" className="md:hidden" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
            <Menu />
          </Button>
          <span aria-hidden="true" className="flex size-8 items-center justify-center rounded-[10px] bg-primary text-sm font-bold text-primary-foreground">A</span>
          <span className="font-serif text-2xl font-semibold leading-none">AMS Console</span>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <AttentionBell />
          <PersonaSelect />
          <PersonChip />
          <Button variant="ghost" size="icon-lg" aria-label="Sign out" title="Sign out" onClick={() => signOut()}>
            <LogOut />
          </Button>
        </div>
      </header>

      <Dialog open={menuOpen} onOpenChange={setMenuOpen}>
        <DialogContent className="top-0 left-0 flex h-full max-h-none w-64 max-w-64 translate-x-0 translate-y-0 flex-col overflow-hidden rounded-none border-y-0 border-l-0 p-3 sm:max-w-64">
          <DialogTitle className="sr-only">Menu</DialogTitle>
          <AppSidebar className="min-h-0 flex-1" onNavigate={() => setMenuOpen(false)} />
        </DialogContent>
      </Dialog>

      <div className="flex items-start gap-5 px-4 pb-8 md:px-8">
        <aside className="sticky top-[76px] hidden h-[calc(100vh-92px)] w-[216px] shrink-0 rounded-[20px] md:block">
          <AppSidebar />
        </aside>
        <main className={cn("flex min-w-0 max-w-[1440px] flex-1 flex-col gap-5", className)}>
          {allowed && children}
        </main>
      </div>
    </div>
  );
}
