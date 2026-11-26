"use client";

import { useEffect, useSyncExternalStore } from "react";
import { apiClient } from "@/lib/api-client";

// Who is signed in (the API's session cookie) and what their role may open.
export type ViewRole = "admin" | "lead" | "engineer";

/**
 * One entry per role: where they land and their menu (hrefs of the sidebar's items).
 * The menu is also every page they may open; no `nav` means every page.
 */
export const ROLES: {
  value: ViewRole;
  label: string;
  home: string;
  nav?: { label: string; items: string[] }[];
}[] = [
  { value: "admin", label: "Admin", home: "/" },
  {
    value: "lead",
    label: "Lead",
    home: "/lead",
    nav: [
      { label: "Overview", items: ["/lead", "/team", "/my-tickets", "/incidents"] },
      { label: "Tickets", items: ["/review", "/tickets"] },
      { label: "Agents", items: ["/agents/resolution", "/agents/knowledge"] },
    ],
  },
  {
    value: "engineer",
    label: "Engineer",
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

export type User = { email: string; name: string; role: ViewRole };

// undefined: not asked yet; null: nobody is signed in
let signedIn: User | null | undefined;
// The person an admin chose to view the console as. Kept in this browser; the API still sees the admin's own session.
let persona: User | null = null;
let shown: User | null | undefined; // what the pages see: the persona for an admin who chose one, else who is signed in
let asked: Promise<void> | undefined;
const listeners = new Set<() => void>();
const PERSONA_KEY = "ams.persona";

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

function publish() {
  shown = signedIn?.role === "admin" && persona ? persona : signedIn;
  listeners.forEach((l) => l());
}

/** Set after signing in or out, so every page follows. */
export function setUser(next: User | null) {
  signedIn = next;
  asked = Promise.resolve();
  try {
    if (next === null) localStorage.removeItem(PERSONA_KEY); // the next person here starts as themselves
    persona = JSON.parse(localStorage.getItem(PERSONA_KEY) ?? "null");
  } catch {
    persona = null; // storage blocked or unreadable: no persona
  }
  publish();
}

/** An admin views the console as this person; null: as themselves again. */
export function setPersona(next: User | null) {
  persona = next;
  try {
    if (next) localStorage.setItem(PERSONA_KEY, JSON.stringify(next));
    else localStorage.removeItem(PERSONA_KEY);
  } catch {
    // storage blocked: the choice lasts until reload
  }
  publish();
}

/** Asks the API once who holds the session cookie. */
export function loadUser(): Promise<void> {
  asked ??= apiClient<User>("/auth/me").then(setUser, () => setUser(null));
  return asked;
}

export async function signOut() {
  await apiClient("/auth/logout", { method: "POST" });
  setUser(null);
}

function useStore(read: () => User | null | undefined) {
  useEffect(() => {
    loadUser();
  }, []);
  return useSyncExternalStore(subscribe, read, () => undefined);
}

/** Who really signed in; undefined until the API has answered, null when nobody is signed in. */
export function useSignedIn(): User | null | undefined {
  return useStore(() => signedIn);
}

/** The person the console is shown as: the signed-in person, or the persona an admin chose. */
export function useUser(): User | null | undefined {
  return useStore(() => shown);
}

/** That person's role. The app shell shows a page only once it is known. */
export function useViewAs(): ViewRole {
  return useUser()?.role ?? "engineer";
}

/** That person's name, sent as "who did it". shortcut: the API still trusts this name; take it from the session there. */
export function usePerson(): string {
  return useUser()?.name ?? "";
}
