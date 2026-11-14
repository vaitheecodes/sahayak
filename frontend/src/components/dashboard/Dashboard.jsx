import { useEffect, useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Clock, Inbox, Layers } from "lucide-react";
import { api } from "@/api";
import BarChart from "@/components/BarChart";
import TicketRows from "@/components/TicketRows";
import { STATUS_META, statusColor } from "@/lib/statusMeta";
import { cn } from "@/lib/utils";
import { Alert } from "@/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { EmptyState } from "@/ui/empty-state";
import { Input } from "@/ui/input";
import { Skeleton } from "@/ui/skeleton";
import { PriorityBadge } from "@/ui/status";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";
import { PRIORITIES } from "@/utils/priorities";
import { statusLabel } from "@/utils/statusLabels";
import PeriodSelect, { DEFAULT_PERIOD } from "./PeriodSelect";
import { HBars, minutesText } from "./parts";

/* The one dashboard, for managers (their own department) and support
 * engineers (their own tickets): GET /api/manager/dashboard or
 * /api/staff/dashboard for the selected period.
 *
 *   1. One line of counts: tickets created in the period by current status
 *      (they add up to Total), then SLA breached and at risk. A count is a
 *      button: it filters the list below.
 *   2. That list (search and period apply; two lines per ticket on phones).
 *   3. Charts for the period: by priority, by status, created vs resolved.
 *   4. Managers: how each support engineer is doing. */

const STATUSES = ["open", "in_progress", "pending_customer", "resolved", "closed"];

// Read at render time: the admin's status labels load at startup.
const counts = () => [
  { key: "total", label: "Total tickets" },
  { key: "new", label: "New (unassigned)" },
  ...STATUSES.map((key) => ({ key, label: statusLabel(key) })),
];
const SLA_COUNTS = [
  { key: "sla_breached", state: "breached", label: "SLA breached", color: "text-negative" },
  { key: "sla_at_risk", state: "at_risk", label: "SLA at risk", color: "text-warning" },
];

function listFilters(key, role) {
  if (key === "total") return {};
  const sla = SLA_COUNTS.find((c) => c.key === key);
  if (sla) return { sla: sla.state };
  if (key === "open" && role === "manager") return { status: "open", assigned: "true" };
  return { status: key };
}

function CountButton({ count, value, pressed, onSelect, compact }) {
  const meta = STATUS_META[count.key];
  const Icon = meta?.icon || (count.state ? Clock : Layers);
  const token = meta?.token;
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onSelect}
      className={cn(
        "relative flex shrink-0 cursor-pointer flex-col items-start justify-start rounded-none border-0 bg-sheet pt-2.5 pb-3 text-left text-fg shadow-none outline-none",
        "focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
        compact ? "px-3" : "min-w-[8.5rem] px-3.5 md:flex-1",
      )}
      style={pressed ? { background: token ? `var(--status-${token}-bg)` : "var(--raised)" } : undefined}
    >
      <span
        className={cn(
          "flex items-center gap-1.5 whitespace-nowrap text-sm",
          pressed ? "font-medium" : "text-muted-fg",
          count.state && count.color,
        )}
        style={pressed && token ? { color: `var(--status-${token}-fg)` } : undefined}
      >
        <Icon
          aria-hidden="true"
          className="size-3.5 shrink-0"
          strokeWidth={2}
          style={{ color: token ? `var(--status-${token}-fg)` : undefined }}
        />
        {count.label}
      </span>
      <span className={cn("mt-0.5 block font-semibold tabular-nums tracking-tight", compact ? "text-xl" : "text-2xl")}>
        {value}
      </span>
      {pressed && (
        <span
          aria-hidden="true"
          className="absolute inset-x-0 bottom-0 h-[3px]"
          style={{ background: token ? statusColor(count.key) : count.state ? "currentColor" : "var(--fg)" }}
        />
      )}
    </button>
  );
}

function TicketList({ role, period, selected, label, department }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [tickets, setTickets] = useState(null);
  const [error, setError] = useState("");
  const searchId = useId();
  useEffect(() => {
    let current = true;
    const filters = { period, q: q.trim(), department, ...listFilters(selected, role) };
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
  }, [role, period, selected, q, department]);

  function open(t) {
    const id = encodeURIComponent(t.ticket_id);
    navigate(role === "manager" ? `/manager/tickets?open=${id}` : `/technician/tickets?view=mine&open=${id}`);
  }

  return (
    <section aria-label={`${label} tickets`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="m-0 text-md font-semibold">{label}</h2>
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
            Nothing created in this period matches.
          </EmptyState>
        )}
        {tickets && tickets.length > 0 && (
          // New is not a stored status: those rows say New, not Open (display only).
          <TicketRows tickets={tickets} onOpen={open} statusFor={selected === "new" ? () => "new" : undefined} />
        )}
      </Card>
    </section>
  );
}

const dayLabel = (p) =>
  new Date(`${p.date}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

function Charts({ data }) {
  const period = data.period.label.toLowerCase();
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <HBars
        title={`By priority, created ${period}`}
        rows={PRIORITIES.map((p) => ({
          key: p,
          label: <PriorityBadge priority={p} />,
          value: data.by_priority[p] || 0,
          color: p === "urgent" ? "var(--negative)" : undefined,
        }))}
      />
      <HBars
        title={`By status, created ${period}`}
        rows={["new", ...STATUSES].map((s) => ({
          key: s,
          label: s === "new" ? "New (unassigned)" : statusLabel(s),
          value: data.by_status[s] || 0,
          color: statusColor(s),
        }))}
      />
      <Card className="lg:col-span-2">
        <CardContent className="pt-4">
          <BarChart
            title={`Created and resolved per day, ${period}`}
            points={data.over_time}
            series={[
              { key: "created", label: "Created", color: "var(--chart-1)" },
              { key: "resolved", label: "Resolved", color: "var(--chart-2)" },
            ]}
            labelFor={dayLabel}
          />
        </CardContent>
      </Card>
    </div>
  );
}

function SupportEngineers({ rows, period }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Support engineers</CardTitle>
      </CardHeader>
      {rows.length === 0 ? (
        <CardContent>
          <p className="m-0 text-sm text-muted-fg">
            No support engineers work this department yet. The administrator sets their department under Users.
          </p>
        </CardContent>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Support engineer</TableHead>
              <TableHead className="num">Assigned now</TableHead>
              <TableHead className="num">Resolved</TableHead>
              <TableHead className="num">First reply</TableHead>
              <TableHead className="num">Breached</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((t) => (
              <TableRow key={t.technician_id}>
                <TableCell>{t.name}</TableCell>
                <TableCell className="num tabular-nums">{t.open}</TableCell>
                <TableCell className="num tabular-nums">{t.resolved}</TableCell>
                <TableCell className="num tabular-nums">{minutesText(t.avg_first_response_minutes)}</TableCell>
                <TableCell className={cn("num tabular-nums", t.breached && "font-medium text-negative")}>
                  {t.breached}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <p className="m-0 px-5 pt-1 pb-4 text-xs text-muted-fg">
        Resolved and first reply: {period.label.toLowerCase()}. Assigned and breached: open tickets now.
      </p>
    </Card>
  );
}

export default function Dashboard({ role, department, onDepartment }) {
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [selected, setSelected] = useState("total");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    (role === "manager" ? api.managerDashboard(period, department) : api.staffDashboard(period))
      .then((d) => {
        if (!current) return;
        setData(d);
        setError("");
        onDepartment?.(d.all_departments ? "All departments" : d.department?.name || null);
      })
      .catch((err) => current && setError(err.message));
    return () => {
      current = false;
    };
  }, [role, period, department, onDepartment]);

  if (error) return <Alert tone="negative">{error}</Alert>;
  if (!data) return <Skeleton className="h-64" />;
  if (role === "manager" && !data.department && !data.all_departments)
    return (
      <Alert tone="info" title="No department yet">
        Ask your administrator to assign you a department. Your dashboard shows its tickets only.
      </Alert>
    );

  const values = { ...data.by_status, sla_breached: data.created_sla.breached, sla_at_risk: data.created_sla.at_risk };
  const all = [...counts(), ...SLA_COUNTS];
  const label = all.find((c) => c.key === selected).label;
  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="created-counts" className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="created-counts" className="m-0 text-sm font-medium text-muted-fg">
            Created {data.period.label.toLowerCase()}
            {role === "technician" ? ", your tickets" : ""}
          </h2>
          <PeriodSelect value={period} onChange={setPeriod} />
        </div>
        <div
          role="group"
          aria-label="Show tickets by status or SLA"
          className="flex overflow-x-auto rounded-xl border border-border-strong [&>*+*]:border-l [&>*+*]:border-border"
        >
          {counts().map((c) => (
            <CountButton
              key={c.key}
              count={c}
              value={values[c.key] ?? 0}
              pressed={selected === c.key}
              onSelect={() => setSelected(c.key)}
            />
          ))}
          {SLA_COUNTS.map((c) => (
            <CountButton
              key={c.key}
              count={c}
              compact
              value={values[c.key] ?? 0}
              pressed={selected === c.key}
              onSelect={() => setSelected(c.key)}
            />
          ))}
        </div>
      </section>

      <TicketList role={role} period={period} selected={selected} label={label} department={department} />
      <Charts data={data} />
      {role === "manager" && <SupportEngineers rows={data.technician_workload} period={data.period} />}
    </div>
  );
}
