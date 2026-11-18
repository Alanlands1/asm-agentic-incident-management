"use client";

import { useSyncExternalStore } from "react";

// shortcut: demo-only role switch kept in localStorage, no sign-in or server checks; replace with real sessions.
export type ViewRole = "admin" | "lead" | "engineer";

/**
 * One entry per persona: who they are, where they land and their menu (hrefs of the sidebar's items).
 * The menu is also every page they may open; no `nav` means every page. The engineer's name is their Jira assignee name.
 */
export const ROLES: {
  value: ViewRole;
  label: string;
  person: string;
  home: string;
  nav?: { label: string; items: string[] }[];
}[] = [
  { value: "admin", label: "Admin", person: "Alan Lands", home: "/" },
  {
    value: "lead",
    label: "Lead",
    person: "Alan Lands",
    home: "/team",
    nav: [
      { label: "Overview", items: ["/team", "/my-tickets", "/incidents"] },
      { label: "Tickets", items: ["/review", "/tickets"] },
      { label: "Agents", items: ["/agents/resolution"] },
    ],
  },
  {
    value: "engineer",
    label: "Engineer",
    person: "Alan Test",
    home: "/team",
    nav: [
      { label: "My work", items: ["/team", "/my-tickets"] },
      { label: "Tickets", items: ["/review", "/tickets"] },
      { label: "Agents", items: ["/agents/resolution"] },
    ],
  },
];

/** Whether the role's menu covers this page (or a page under it). */
export function mayOpen(role: ViewRole, pathname: string): boolean {
  const nav = ROLES.find((r) => r.value === role)!.nav;
  return !nav || nav.some((g) => g.items.some((href) => pathname === href || pathname.startsWith(`${href}/`)));
}

const KEY = "ams.viewAs";
const EVENT = "ams-view-as";

function read(): ViewRole {
  try {
    const v = localStorage.getItem(KEY);
    const known = ROLES.find((r) => r.value === v);
    if (known) return known.value;
  } catch {
    // storage blocked: fall back to admin
  }
  return "admin";
}

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function setViewAs(role: ViewRole) {
  try {
    localStorage.setItem(KEY, role);
  } catch {
    // storage blocked: the switch lasts until reload
  }
  window.dispatchEvent(new Event(EVENT));
}

export function useViewAs(): ViewRole {
  return useSyncExternalStore(subscribe, read, () => "admin");
}

/** The demo person of the current role, sent as "who did it" until there are real logins. */
export function usePerson(): string {
  const role = useViewAs();
  return ROLES.find((r) => r.value === role)!.person;
}
