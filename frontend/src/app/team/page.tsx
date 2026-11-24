"use client";

import { PersonaOverview } from "@/components/console/persona-overview";
import { useViewAs } from "@/lib/view-as";

/** Overview: open tickets by work status. An engineer sees their own; the lead sees all and runs the agents. */
export default function TeamPage() {
  return <PersonaOverview lead={useViewAs() !== "engineer"} />;
}
