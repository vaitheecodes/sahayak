import { useEffect, useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Inbox, Layers } from "lucide-react";
import { api } from "@/api";
import TicketRows from "@/components/TicketRows";
import { STATUS_META, statusColor } from "@/lib/statusMeta";
import { cn } from "@/lib/utils";
import { Alert } from "@/ui/alert";
import { Card } from "@/ui/card";
import { EmptyState } from "@/ui/empty-state";
import { Input } from "@/ui/input";
import { Skeleton } from "@/ui/skeleton";
import { statusLabel } from "@/utils/statusLabels";

/* Kanban dashboard: one status rail (tickets created in the period, by
 * current status; the counts add up to Total), then the selected status's
 * tickets below it. The same scope as everywhere: a manager's own
 * department, a technician's own tickets. New = open with nobody assigned,
 * so Open here means open and picked up. */

// Stored statuses use the admin's labels (utils/statusLabels.js, loaded at
// startup), as the chips do; read at render time, not import time.
const cards = () => [
  { key: "total", label: "Total tickets" },
  { key: "new", label: "New (unassigned)" },
  ...["open", "in_progress", "pending_customer", "resolved", "closed"].map((key) => ({ key, label: statusLabel(key) })),
];

function filtersFor(key, role) {
  if (key === "total") return {};
  if (key === "open" && role === "manager") return { status: "open", assigned: "true" };
  return { status: key };
}

function RailCard({ card, count, pressed, onSelect }) {
  const meta = STATUS_META[card.key];
  const Icon = meta?.icon || Layers;
  const token = meta?.token;
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onSelect}
      className={cn(
        "relative flex min-w-[8.5rem] flex-1 cursor-pointer flex-col max-md:min-w-max max-md:flex-none items-start justify-start rounded-none border-0 bg-sheet px-3.5 pt-2.5 pb-3 text-left text-fg shadow-none outline-none",
        "focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
        "[&+&]:border-l [&+&]:border-border",
        card.key === "total" && "md:flex-[1.3]",
      )}
      style={pressed ? { background: token ? `var(--status-${token}-bg)` : "var(--raised)" } : undefined}
    >
      <span
        className={cn("flex items-center gap-1.5 whitespace-nowrap text-sm", pressed ? "font-medium" : "text-muted-fg")}
        style={pressed && token ? { color: `var(--status-${token}-fg)` } : undefined}
      >
        <Icon
          aria-hidden="true"
          className="size-3.5 shrink-0"
          strokeWidth={2}
          style={{ color: token ? `var(--status-${token}-fg)` : undefined }}
        />
        {card.label}
      </span>
      <span className="mt-0.5 block text-2xl font-semibold tabular-nums tracking-tight">{count}</span>
      {pressed && (
        <span
          aria-hidden="true"
          className="absolute inset-x-0 bottom-0 h-[3px]"
          style={{ background: token ? statusColor(card.key) : "var(--fg)" }}
        />
      )}
    </button>
  );
}

export default function KanbanBoard({ role, period, byStatus }) {
  const navigate = useNavigate();
  const [selected, setSelected] = useState("total");
  const [q, setQ] = useState("");
  const [tickets, setTickets] = useState(null);
  const [error, setError] = useState("");
  const searchId = useId();

  useEffect(() => {
    let current = true;
    const filters = { period, q: q.trim(), ...filtersFor(selected, role) };
    const timer = setTimeout(() => {
      const load =
        role === "manager"
          ? api.managerTickets(filters).then((d) => d.tickets)
          : api.staffTickets({ view: "mine", ...filters });
      load
        .then((rows) => {
          if (current) {
            setTickets(rows);
            setError("");
          }
        })
        .catch((err) => current && setError(err.message));
    }, 200);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [role, period, selected, q]);

  function openTicket(t) {
    const id = encodeURIComponent(t.ticket_id);
    navigate(role === "manager" ? `/manager/tickets?open=${id}` : `/technician/tickets?view=mine&open=${id}`);
  }

  const CARDS = cards();
  const card = CARDS.find((c) => c.key === selected);
  const segments = CARDS.slice(1).filter((c) => byStatus[c.key] > 0);
  return (
    <div className="flex flex-col gap-4">
      <div>
        <div
          role="group"
          aria-label="Show tickets by status"
          className="flex overflow-x-auto rounded-xl border border-border-strong"
        >
          {CARDS.map((c) => (
            <RailCard
              key={c.key}
              card={c}
              count={byStatus[c.key] ?? 0}
              pressed={selected === c.key}
              onSelect={() => setSelected(c.key)}
            />
          ))}
        </div>
        {byStatus.total > 0 && (
          <div aria-hidden="true" className="mt-2 flex h-1 gap-0.5 overflow-hidden rounded-full">
            {segments.map((c) => (
              <span key={c.key} style={{ flexGrow: byStatus[c.key], background: statusColor(c.key) }} />
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="m-0 text-md font-semibold">{card.label}</h2>
        <span className="text-sm tabular-nums text-muted-fg">
          {tickets ? `${tickets.length} ticket${tickets.length === 1 ? "" : "s"}` : ""}
        </span>
        <label htmlFor={searchId} className="sr-only">
          Search these tickets
        </label>
        <Input
          id={searchId}
          type="search"
          placeholder="Subject, customer or #id"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="w-full sm:ml-auto sm:w-72"
        />
      </div>

      {error && <Alert tone="negative">{error}</Alert>}
      <Card>
        {!tickets && !error && <Skeleton className="m-5 h-24" />}
        {tickets && tickets.length === 0 && (
          <EmptyState icon={Inbox} title="No tickets here">
            Nothing {card.key === "total" ? "" : `${card.label.toLowerCase()} `}created in this period matches.
          </EmptyState>
        )}
        {tickets && tickets.length > 0 && <TicketRows tickets={tickets} onOpen={openTicket} />}
      </Card>
    </div>
  );
}
