"use client";

import { useEffect, useState, useMemo } from "react";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { ListRow } from "@/components/console/list-row";
import { StatTile } from "@/components/console/stat-tile";
import { STAGES } from "@/components/console/dashboard";
import { apiClient } from "@/lib/api-client";
import { ticketService } from "@/services/ticket-service";
import { ServiceNowTicket } from "@/types/servicenow";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertAction, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Search,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  ShieldCheck,
  ChevronLeft,
  ChevronRight,
  ArrowRight,
} from "lucide-react";
import Link from "next/link";
import { PriorityChip } from "@/components/console/priority-chip";
import { useViewAs } from "@/lib/view-as";

// The reporter's name is masked at ingest; a placeholder like <PERSON_1> says nothing in a list.
const masked = (v?: string | null) => !!v && /^<[A-Z_]+_\d+>$/.test(v);

const STAGE_WORDS = Object.fromEntries(STAGES);

const selectClass =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

export default function TicketsPage() {
  const admin = useViewAs() === "admin";
  const [tickets, setTickets] = useState<ServiceNowTicket[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [serviceFilter, setServiceFilter] = useState<string>("all");
  const [dqFilter, setDqFilter] = useState<string>("all"); // 'all', 'flagged', 'clean'
  const [statusFilter, setStatusFilter] = useState<string>("all"); // 'all', 'open', 'closed'
  const [selectedTicket, setSelectedTicket] = useState<ServiceNowTicket | null>(null);
  // What the agents made of each open ticket: its stage and the priority in force (decided, else recommended).
  const [agents, setAgents] = useState<Record<string, { stage: string; priority: number | null }>>({});

  // Pagination
  const [page, setPage] = useState<number>(1);
  const pageSize = 20;

  async function fetchTickets() {
    setLoading(true);
    setError(null);
    try {
      const data = await ticketService.getTickets({
        limit: 500, // the most the API returns; filtering is client-side
      });
      setTickets(data.items);
      setTotalCount(data.total);
      apiClient<{ tickets: { id: string; stage: string; priority: number | null }[] }>("/personas/board")
        .then((board) => setAgents(Object.fromEntries(board.tickets.map((t) => [t.id, t]))))
        .catch(() => setAgents({})); // the list still works without the agents' view
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load ServiceNow tickets";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchTickets();
  }, []);

  // Unique services for filter dropdown
  const uniqueServices = useMemo(() => {
    const set = new Set<string>();
    tickets.forEach((t) => {
      if (t.service) set.add(t.service);
    });
    return Array.from(set).sort();
  }, [tickets]);

  // Filtered tickets
  const filteredTickets = useMemo(() => {
    return tickets.filter((t) => {
      // Search
      const search = searchTerm.toLowerCase();
      const matchesSearch =
        !search ||
        t.ticket_id.toLowerCase().includes(search) ||
        (t.short_description && t.short_description.toLowerCase().includes(search)) ||
        (t.caller && t.caller.toLowerCase().includes(search)) ||
        (t.service && t.service.toLowerCase().includes(search));

      if (!matchesSearch) return false;

      // Service filter
      if (serviceFilter !== "all" && t.service !== serviceFilter) return false;

      // DQ filter
      if (dqFilter === "flagged" && !t.dq_flag) return false;
      if (dqFilter === "clean" && t.dq_flag) return false;

      // Status filter
      if (statusFilter === "open" && t.closed_at !== null) return false;
      if (statusFilter === "closed" && t.closed_at === null) return false;

      return true;
    });
  }, [tickets, searchTerm, serviceFilter, dqFilter, statusFilter]);

  // Paginated slice
  const paginatedTickets = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredTickets.slice(start, start + pageSize);
  }, [filteredTickets, page, pageSize]);

  const totalPages = Math.ceil(filteredTickets.length / pageSize) || 1;

  // Counts for KPI summary
  const flaggedCount = useMemo(() => tickets.filter((t) => t.dq_flag).length, [tickets]);
  const cleanCount = useMemo(() => tickets.filter((t) => !t.dq_flag).length, [tickets]);
  const openCount = useMemo(() => tickets.filter((t) => !t.closed_at).length, [tickets]);

  return (
    <AppShell>
      <PageHeader
        title="All tickets"
        context="Every ticket from ServiceNow sheets and Jira, with personal details masked on the way in."
        actions={
          <>
            <Button variant="secondary" onClick={fetchTickets} disabled={loading}>
              <RefreshCw className={loading ? "animate-spin" : ""} />
              Refresh
            </Button>
            {admin && (
              <Button render={<Link href="/dq-rules" />} nativeButton={false}>
                <ShieldCheck />
                Open the rule builder
              </Button>
            )}
          </>
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile variant="primary" label="Ingested tickets" value={totalCount} />
        <StatTile label="Clean" value={cleanCount} window={`of ${tickets.length} loaded`} />
        <StatTile label="Flagged by the rule builder" value={flaggedCount} window={`of ${tickets.length} loaded`} />
        <StatTile label="Open" value={openCount} window={`of ${tickets.length} loaded`} />
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
          <AlertAction>
            <Button variant="secondary" size="sm" onClick={fetchTickets}>
              Retry
            </Button>
          </AlertAction>
        </Alert>
      )}

      <Card className="gap-0 py-0">
        <div className="flex flex-wrap gap-2 border-b border-border px-4 py-3">
          <div className="relative flex-[1_1_100%] min-[1100px]:flex-[2_1_18rem]">
            <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground" aria-hidden="true" />
            <Input
              aria-label="Search tickets"
              placeholder="Search by ticket ID, description, caller or service"
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setPage(1);
              }}
              className="pl-8"
            />
          </div>
          <div className="flex-[1_1_9rem]">
            <select
              aria-label="Service"
              value={serviceFilter}
              onChange={(e) => {
                setServiceFilter(e.target.value);
                setPage(1);
              }}
              className={selectClass}
            >
              <option value="all">All services</option>
              {uniqueServices.map((svc) => (
                <option key={svc} value={svc}>
                  {svc}
                </option>
              ))}
            </select>
          </div>
          <div className="flex-[1_1_9rem]">
            <select
              aria-label="Data quality status"
              value={dqFilter}
              onChange={(e) => {
                setDqFilter(e.target.value);
                setPage(1);
              }}
              className={selectClass}
            >
              <option value="all">Flagged or clean</option>
              <option value="clean">Clean only</option>
              <option value="flagged">Flagged only</option>
            </select>
          </div>
          <div className="flex-[1_1_9rem]">
            <select
              aria-label="Lifecycle"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className={selectClass}
            >
              <option value="all">All lifecycle</option>
              <option value="open">Open / unresolved</option>
              <option value="closed">Closed</option>
            </select>
          </div>
        </div>

        <ul role="list">
          {loading ? (
            <li className="flex items-center justify-center gap-2 px-4 py-10 text-muted-foreground">
              <RefreshCw className="size-4 animate-spin" aria-hidden="true" />
              Loading tickets…
            </li>
          ) : paginatedTickets.length === 0 ? (
            <li className="px-4 py-10 text-center text-muted-foreground">
              No incident tickets match the filters.
            </li>
          ) : (
            paginatedTickets.map((ticket) => (
              <ListRow
                key={ticket.ticket_id}
                lead={<PriorityChip priority={agents[ticket.ticket_id]?.priority ?? ticket.priority} />}
                itemKey={
                  <Link href={`/tickets/${encodeURIComponent(ticket.ticket_id)}`} className="underline-offset-4 hover:underline">
                    {ticket.ticket_id}
                  </Link>
                }
                title={ticket.short_description || "No short description"}
                meta={[
                  ticket.service || "No service",
                  masked(ticket.caller) ? null : ticket.caller || "Unknown caller",
                  ticket.priority || "Unassigned priority",
                  ticket.closed_at ? "Closed" : "Open",
                ]
                  .filter(Boolean)
                  .join(" · ")}
                trailing={
                  ticket.dq_flag ? (
                    <span className="inline-flex items-center gap-1.5 text-foreground">
                      <AlertTriangle className="size-4" aria-hidden="true" />
                      Flagged
                    </span>
                  ) : agents[ticket.ticket_id] ? (
                    <span>{STAGE_WORDS[agents[ticket.ticket_id].stage] ?? agents[ticket.ticket_id].stage}</span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5">
                      <CheckCircle2 className="size-4" aria-hidden="true" />
                      Clean
                    </span>
                  )
                }
                actions={
                  <Button variant="secondary" onClick={() => setSelectedTicket(ticket)}>
                    Inspect
                    <span className="sr-only"> {ticket.ticket_id}</span>
                  </Button>
                }
              />
            ))
          )}
        </ul>

        <div className="flex flex-col items-center justify-between gap-3 border-t border-border px-4 py-3 sm:flex-row">
          <span className="text-xs text-muted-foreground tabular-nums">
            Showing {paginatedTickets.length > 0 ? (page - 1) * pageSize + 1 : 0} to{" "}
            {Math.min(page * pageSize, filteredTickets.length)} of {filteredTickets.length} tickets
            {filteredTickets.length !== totalCount && ` (filtered from ${totalCount} total)`}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              <ChevronLeft />
              Previous
            </Button>
            <span className="px-2 text-xs font-medium tabular-nums">
              Page {page} of {totalPages}
            </span>
            <Button
              variant="secondary"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              Next
              <ChevronRight />
            </Button>
          </div>
        </div>
      </Card>

      {admin && (
        <nav aria-label="Pipeline" className="mt-8 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
          <Button variant="secondary" render={<Link href="/dq-rules" />} nativeButton={false}>
            Next: Rule builder
            <ArrowRight />
          </Button>
        </nav>
      )}

      {selectedTicket && (
        <Dialog open={!!selectedTicket} onOpenChange={(open) => !open && setSelectedTicket(null)}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className="font-mono">{selectedTicket.ticket_id}</Badge>
                <Badge variant={selectedTicket.dq_flag ? "destructive" : "default"}>
                  {selectedTicket.dq_flag ? "Flagged by the rule builder" : "Clean"}
                </Badge>
                {selectedTicket.service && <Badge>{selectedTicket.service}</Badge>}
              </div>
              <DialogTitle className="text-base font-semibold">
                {selectedTicket.short_description || "ServiceNow incident detail"}
              </DialogTitle>
              <DialogDescription>
                Opened {selectedTicket.opened_at ? new Date(selectedTicket.opened_at).toLocaleString() : "unknown"} · Caller: {masked(selectedTicket.caller) ? "masked" : selectedTicket.caller || "N/A"}
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-col gap-4">
              {selectedTicket.dq_flag && (
                <Alert variant="destructive">
                  <AlertTriangle />
                  <AlertDescription>
                    <span className="font-medium">Data quality defect: </span>
                    {selectedTicket.dq_reason || "Flagged by automated DQ rules."}
                  </AlertDescription>
                </Alert>
              )}

              <div className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">Full description (PII masked)</span>
                <div className="rounded-lg border border-border bg-background p-3 text-body leading-relaxed whitespace-pre-wrap break-words">
                  {selectedTicket.description || "No description provided."}
                </div>
              </div>

              <dl className="grid grid-cols-1 gap-3 rounded-lg border border-border p-3 sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-muted-foreground">Priority</dt>
                  <dd className="font-medium">{selectedTicket.priority || "Not specified"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Assignment group</dt>
                  <dd className="font-medium">{selectedTicket.assignment_group || "Unassigned"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Lifecycle</dt>
                  <dd className="font-medium">
                    {selectedTicket.closed_at ? `Closed (${new Date(selectedTicket.closed_at).toLocaleDateString()})` : "Open / unresolved"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">PII protection</dt>
                  <dd className="font-medium">Presidio masked at ingest</dd>
                </div>
              </dl>

              {selectedTicket.resolution_notes && (
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Resolution notes</span>
                  <div className="rounded-lg border border-border bg-background p-3 text-body leading-relaxed break-words">
                    {selectedTicket.resolution_notes}
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
              <span className="text-xs text-muted-foreground">
                DB record: <code className="font-mono text-foreground">{selectedTicket.ticket_id}</code>
              </span>
              <div className="flex gap-2">
                <Button render={<Link href={`/tickets/${encodeURIComponent(selectedTicket.ticket_id)}`} />} nativeButton={false}>
                  Open ticket
                </Button>
                <Button variant="secondary" onClick={() => setSelectedTicket(null)}>
                  Close
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </AppShell>
  );
}
