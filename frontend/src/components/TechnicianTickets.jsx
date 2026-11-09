import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Inbox } from "lucide-react";
import { api } from "@/api";
import { ChatBadge } from "@/components/ChatBadge";
import StaffTicketView from "@/components/StaffTicketView";
import { Alert } from "@/ui/alert";
import { Button } from "@/ui/button";
import { Card } from "@/ui/card";
import { EmptyState } from "@/ui/empty-state";
import { Input, Select } from "@/ui/input";
import { Skeleton } from "@/ui/skeleton";
import { PriorityBadge, SlaBadge, StatusBadge } from "@/ui/status";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/ui/tabs";
import { PRIORITIES, PRIORITY_LABELS } from "@/utils/priorities";
import { STATUS_KEYS, statusLabel } from "@/utils/statusLabels";
import { absoluteTime, relativeTime } from "@/utils/time";

/* Technician Tickets: tabs with counts, search (subject, customer, #id),
 * status / priority / type filters, one row per ticket. Unassigned rows
 * have Claim (the race-safe claim: of two simultaneous claims one gets
 * 409). A row opens the ticket workspace below the table. */

const VIEWS = [
  ["unassigned", "Unassigned"],
  ["mine", "Mine"],
  ["open_pending", "All open"],
  ["resolved", "Recently resolved"],
];

export default function TechnicianTickets() {
  const [params, setParams] = useSearchParams();
  const view = VIEWS.some(([k]) => k === params.get("view")) ? params.get("view") : "unassigned";
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [ticketType, setTicketType] = useState("");
  const [tickets, setTickets] = useState(null);
  const [counts, setCounts] = useState(null);
  const [error, setError] = useState("");
  const [claiming, setClaiming] = useState("");
  const openId = params.get("open");
  const detailRef = useRef(null);
  const ids = { q: useId(), status: useId(), priority: useId(), type: useId() };

  const load = useCallback(() => {
    const filters = { q: q.trim(), status, priority, ticket_type: ticketType };
    Promise.all([api.staffTickets({ view, ...filters }), api.staffTicketCounts(filters)])
      .then(([rows, c]) => {
        setTickets(rows);
        setCounts(c);
        setError("");
      })
      .catch((err) => setError(err.message));
  }, [view, q, status, priority, ticketType]);

  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [load]);

  function update(changes) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  }

  function open(ticketId) {
    update({ open: ticketId });
    requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  async function claim(e, ticketId) {
    e.stopPropagation();
    setClaiming(ticketId);
    try {
      await api.staffClaim(ticketId);
      update({ view: "mine", open: ticketId });
    } catch (err) {
      setError(err.message);
      load();
    } finally {
      setClaiming("");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Tabs value={view} onValueChange={(v) => update({ view: v, open: null })}>
        <TabsList aria-label="Ticket lists">
          {VIEWS.map(([key, label]) => (
            <TabsTrigger key={key} value={key} count={counts ? counts[key] : undefined}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex min-w-56 flex-1 flex-col gap-1">
          <label htmlFor={ids.q} className="text-sm text-muted-fg">
            Search
          </label>
          <Input id={ids.q} type="search" placeholder="Subject, customer or #id" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="flex w-40 flex-col gap-1">
          <label htmlFor={ids.status} className="text-sm text-muted-fg">
            Status
          </label>
          <Select id={ids.status} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any</option>
            {STATUS_KEYS.map((key) => (
              <option key={key} value={key}>
                {statusLabel(key)}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex w-36 flex-col gap-1">
          <label htmlFor={ids.priority} className="text-sm text-muted-fg">
            Priority
          </label>
          <Select id={ids.priority} value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option value="">Any</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {PRIORITY_LABELS[p]}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex w-44 flex-col gap-1">
          <label htmlFor={ids.type} className="text-sm text-muted-fg">
            Type
          </label>
          <Select id={ids.type} value={ticketType} onChange={(e) => setTicketType(e.target.value)}>
            <option value="">Tickets and chats</option>
            <option value="ticket">Tickets</option>
            <option value="chat">Escalated chats</option>
          </Select>
        </div>
      </div>

      {error && <Alert tone="negative">{error}</Alert>}
      <Card>
        {!tickets && !error && <Skeleton className="m-5 h-24" />}
        {tickets && tickets.length === 0 && (
          <EmptyState icon={Inbox} title={view === "unassigned" ? "Nothing waiting to be claimed" : "No tickets match"} />
        )}
        {tickets && tickets.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Subject</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>SLA</TableHead>
                <TableHead>Updated</TableHead>
                {view === "unassigned" && (
                  <TableHead>
                    <span className="sr-only">Claim</span>
                  </TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {tickets.map((t) => (
                <TableRow
                  key={t.ticket_id}
                  data-state={openId === t.ticket_id ? "selected" : undefined}
                  className="cursor-pointer"
                  onClick={() => open(t.ticket_id)}
                >
                  <TableCell className="whitespace-nowrap">
                    <span className="inline-flex items-center gap-2">
                      <button
                        type="button"
                        className="cursor-pointer border-0 bg-transparent p-0 font-mono text-sm text-primary hover:underline"
                        onClick={(e) => {
                          e.stopPropagation();
                          open(t.ticket_id);
                        }}
                      >
                        {t.ticket_id}
                      </button>
                      {t.ticket_type === "chat" && <ChatBadge />}
                    </span>
                  </TableCell>
                  <TableCell className="max-w-80">
                    <span className="block truncate" title={t.subject}>
                      {t.subject}
                    </span>
                  </TableCell>
                  <TableCell className="max-w-48">
                    <span className="block truncate" title={t.customer_email}>
                      {t.customer_name}
                    </span>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={t.status} />
                  </TableCell>
                  <TableCell>
                    <PriorityBadge priority={t.priority} />
                  </TableCell>
                  <TableCell>
                    <SlaBadge sla={t.sla} compact />
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm text-muted-fg">
                    <time dateTime={t.last_activity} title={absoluteTime(t.last_activity)}>
                      {relativeTime(t.last_activity)}
                    </time>
                  </TableCell>
                  {view === "unassigned" && (
                    <TableCell>
                      <Button size="sm" onClick={(e) => claim(e, t.ticket_id)} disabled={claiming === t.ticket_id}>
                        {claiming === t.ticket_id ? "Claiming…" : "Claim"}
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <div ref={detailRef}>
        {openId && (
          <div className="card">
            <StaffTicketView key={openId} ticketId={openId} onChanged={load} />
          </div>
        )}
      </div>
    </div>
  );
}
