"use client";

import { PersonaOverview } from "@/components/console/persona-overview";
import { useViewAs } from "@/lib/view-as";

/** Overview, the home of the lead and the engineer: every open ticket for the lead, their own for the engineer. */
export default function TeamPage() {
  return <PersonaOverview mine={useViewAs() === "engineer"} />;
}
