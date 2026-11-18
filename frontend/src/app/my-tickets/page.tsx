import { PersonaOverview } from "@/components/console/persona-overview";

/** The page after the Overview: the tickets assigned to the viewer in Jira, as a list. */
export default function MyTicketsPage() {
  return <PersonaOverview mine worklist />;
}
