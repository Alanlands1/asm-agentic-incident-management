"use client";

import { PersonaOverview } from "@/components/console/persona-overview";
import { useViewAs } from "@/lib/view-as";

/** Overview: open tickets by work status. An engineer sees their own; the lead sees all, runs the agents and sees the workload. */
export default function TeamPage() {
  return <PersonaOverview lead={useViewAs() !== "engineer"} />;
}
