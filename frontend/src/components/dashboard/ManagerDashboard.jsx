import { useEffect, useState } from "react";
import { api } from "@/api";
import BarChart from "@/components/BarChart";
import { useDashboardStyle } from "@/lib/dashboardStyle";
import { statusColor } from "@/lib/statusMeta";
import { Alert } from "@/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { Skeleton } from "@/ui/skeleton";
import { PriorityBadge } from "@/ui/status";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";
import { cn } from "@/lib/utils";
import { PRIORITIES } from "@/utils/priorities";
import KanbanBoard from "./KanbanBoard";
import PeriodSelect, { DEFAULT_PERIOD } from "./PeriodSelect";
import { CreatedStrip, HBars, MetricStrip, StyleToggle, minutesText } from "./parts";

/* Manager dashboard (GET /api/manager/dashboard): the manager's own
 * department only. Classic: what was created in the period (by current
 * status), what is true now, how each technician is doing, created vs
 * resolved per day and open by priority. Kanban: the status rail and its
 * tickets (KanbanBoard). The period applies to both. */

const dayLabel = (p) =>
  new Date(`${p.date}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

function Technicians({ rows, period }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h3">How each technician is doing</CardTitle>
      </CardHeader>
      {rows.length === 0 ? (
        <CardContent>
          <p className="m-0 text-sm text-muted-fg">
            No technicians work this department yet. The administrator sets a technician&apos;s department under Users.
          </p>
        </CardContent>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Technician</TableHead>
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

export default function ManagerDashboard({ onDepartment }) {
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [style, setStyle] = useDashboardStyle();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    api
      .managerDashboard(period)
      .then((d) => {
        if (!current) return;
        setData(d);
        setError("");
        onDepartment?.(d.department?.name || null);
      })
      .catch((err) => current && setError(err.message));
    return () => {
      current = false;
    };
  }, [period, onDepartment]);

  if (error) return <Alert tone="negative">{error}</Alert>;
  if (!data) return <Skeleton className="h-64" />;
  if (!data.department)
    return (
      <Alert tone="info" title="No department yet">
        Ask your administrator to assign you a department. Your dashboard shows its tickets only.
      </Alert>
    );

  const k = data.kpis;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <StyleToggle value={style} onChange={setStyle} />
        <PeriodSelect value={period} onChange={setPeriod} />
      </div>

      {style === "kanban" ? (
        <KanbanBoard role="manager" period={period} byStatus={data.by_status} />
      ) : (
        <>
          <CreatedStrip period={data.period} byStatus={data.by_status} sla={data.created_sla} />
          <MetricStrip
            caption="Now"
            items={[
              { label: "Open", value: k.open, status: "open" },
              { label: "In progress", value: k.in_progress, status: "in_progress" },
              { label: "Unassigned", value: k.unassigned, status: "new" },
              {
                label: "SLA breached / at risk",
                value: `${k.sla_breached} / ${k.sla_at_risk}`,
                clock: true,
                tone: k.sla_breached ? "negative" : k.sla_at_risk ? "warning" : undefined,
              },
              {
                label: "Avg first response",
                value: minutesText(k.avg_first_response_minutes),
                hint: `${k.first_responses} ticket${k.first_responses === 1 ? "" : "s"}, ${data.period.label.toLowerCase()}`,
              },
            ]}
          />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <Technicians rows={data.technician_workload} period={data.period} />
            <HBars
              title="Open by priority"
              rows={PRIORITIES.map((p) => ({
                key: p,
                label: <PriorityBadge priority={p} />,
                value: data.open_by_priority[p] || 0,
                color: p === "urgent" ? "var(--negative)" : undefined,
              }))}
            />
          </div>

          <Card>
            <CardContent className="pt-4">
              <BarChart
                title={`Created and resolved per day, ${data.period.label.toLowerCase()}`}
                points={data.over_time}
                series={[
                  { key: "created", label: "Created", color: statusColor("open") },
                  { key: "resolved", label: "Resolved", color: statusColor("resolved") },
                ]}
                labelFor={dayLabel}
              />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
