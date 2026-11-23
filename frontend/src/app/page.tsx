"use client";

import { PersonaOverview } from "@/components/console/persona-overview";

/** The Admin's home is the same Overview as everyone's, with the demo reset and sync health added. */
export default function Home() {
  return <PersonaOverview lead admin />;
}
