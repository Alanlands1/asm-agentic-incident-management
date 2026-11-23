"use client";

import { PersonaOverview } from "@/components/console/persona-overview";
import { useViewAs } from "@/lib/view-as";

/** Overview: every open ticket by work status, for every role; the lead also runs the agents and sees the workload. */
export default function TeamPage() {
  return <PersonaOverview lead={useViewAs() !== "engineer"} />;
}
