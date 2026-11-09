import { useEffect, useState } from "react";
import { api } from "@/api";
import BarChart from "@/components/BarChart";
import { Alert } from "@/ui/alert";
import { Card, CardContent } from "@/ui/card";
import { Skeleton } from "@/ui/skeleton";
import { PRIORITIES, PRIORITY_LABELS } from "@/utils/priorities";
import PeriodSelect, { DEFAULT_PERIOD } from "./PeriodSelect";
import { HBars, KpiCard, minutesText } from "./parts";

/* Manager dashboard (GET /api/manager/dashboard): the manager's own
 * department only. KPIs are now; the first-response average and the
 * created vs resolved bars cover the period. */

const dayLabel = (p) =>
  new Date(`${p.date}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

export default function ManagerDashboard({ onDepartment }) {
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
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
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="m-0 text-base text-muted-fg">
          {data.department.name}: {data.created} created and {data.resolved} resolved in {data.period.label.toLowerCase()}.
        </p>
        <PeriodSelect value={period} onChange={setPeriod} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <KpiCard label="Open" value={k.open} />
        <KpiCard label="In progress" value={k.in_progress} />
        <KpiCard label="Unassigned" value={k.unassigned} tone={k.unassigned ? "warning" : undefined} />
        <KpiCard
          label="SLA at risk / breached"
          value={`${k.sla_at_risk} / ${k.sla_breached}`}
          tone={k.sla_breached ? "negative" : k.sla_at_risk ? "warning" : undefined}
        />
        <KpiCard
          label="Avg first response"
          value={minutesText(k.avg_first_response_minutes)}
          hint={`${k.first_responses} ticket${k.first_responses === 1 ? "" : "s"} in ${data.period.label.toLowerCase()}`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <HBars
          title="Technician workload (open tickets)"
          rows={data.technician_workload.map((w) => ({ key: w.technician_id, label: w.name, value: w.open }))}
          empty="No technicians work this department yet. The administrator sets a technician's department under Users."
        />
        <HBars
          title="Open by priority"
          rows={PRIORITIES.map((p) => ({ key: p, label: PRIORITY_LABELS[p], value: data.open_by_priority[p] || 0 }))}
        />
      </div>

      <Card>
        <CardContent className="pt-4">
          <BarChart
            title={`Created vs resolved per day · ${data.period.label}`}
            points={data.over_time}
            series={[
              { key: "created", label: "Created" },
              { key: "resolved", label: "Resolved" },
            ]}
            labelFor={dayLabel}
          />
        </CardContent>
      </Card>
    </div>
  );
}
