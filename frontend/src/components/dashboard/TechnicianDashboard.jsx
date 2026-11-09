import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CircleCheck } from "lucide-react";
import { api } from "@/api";
import { ChatBadge } from "@/components/ChatBadge";
import { Alert } from "@/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { EmptyState } from "@/ui/empty-state";
import { Skeleton } from "@/ui/skeleton";
import { PriorityBadge, SlaBadge } from "@/ui/status";
import { relativeTime } from "@/utils/time";
import PeriodSelect, { DEFAULT_PERIOD } from "./PeriodSelect";
import { KpiCard, minutesText } from "./parts";

/* Technician dashboard (GET /api/staff/dashboard): this technician's own
 * tickets only. Cards are now (resolved: in the period), the attention
 * list puts SLA near breach first, then new customer replies, then the
 * rest by last update; "My numbers" cover the period. */

const REASON = { sla: "SLA", customer_reply: "Customer replied" };

function Number({ label, value }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-rule py-2 last:border-0">
      <dt className="text-sm text-muted-fg">{label}</dt>
      <dd className="m-0 text-base font-medium tabular-nums text-fg">{value}</dd>
    </div>
  );
}

export default function TechnicianDashboard() {
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    api
      .staffDashboard(period)
      .then((d) => {
        if (current) {
          setData(d);
          setError("");
        }
      })
      .catch((err) => current && setError(err.message));
    return () => {
      current = false;
    };
  }, [period]);

  if (error) return <Alert tone="negative">{error}</Alert>;
  if (!data) return <Skeleton className="h-64" />;
  const c = data.cards;
  const n = data.numbers;
  const label = data.period.label.toLowerCase();

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="m-0 text-base text-muted-fg">Your tickets only.</p>
        <PeriodSelect value={period} onChange={setPeriod} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <KpiCard label="Assigned to me" value={c.assigned} />
        <KpiCard label="In progress" value={c.in_progress} />
        <KpiCard label="Waiting on customer" value={c.pending_customer} />
        <KpiCard label="Resolved" value={c.resolved} hint={data.period.label} />
        <KpiCard label="SLA at risk" value={c.sla_at_risk} tone={c.sla_at_risk ? "warning" : undefined} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle as="h3">Needs my attention</CardTitle>
            <Link to="/technician/tickets?view=mine" className="inline-flex items-center gap-1 text-sm text-primary">
              All my tickets <ArrowRight className="size-3.5" aria-hidden="true" />
            </Link>
          </CardHeader>
          <CardContent>
            {data.attention.length === 0 ? (
              <EmptyState icon={CircleCheck} title="Nothing waiting on you">
                Claim a ticket from Unassigned to start.
              </EmptyState>
            ) : (
              <ul className="m-0 list-none p-0">
                {data.attention.map((t) => (
                  <li key={t.ticket_id} className="border-b border-rule last:border-0">
                    <Link
                      to={`/technician/tickets?view=mine&open=${encodeURIComponent(t.ticket_id)}`}
                      className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2.5 text-fg no-underline hover:bg-raised"
                    >
                      <span className="min-w-0">
                        <span className="flex items-center gap-2 text-sm text-muted-fg">
                          <span className="font-mono">{t.ticket_id}</span>
                          {t.ticket_type === "chat" && <ChatBadge />}
                          {t.reason && <span>· {REASON[t.reason]}</span>}
                          <span>· {relativeTime(t.updated_at)}</span>
                        </span>
                        <span className="block truncate text-base">{t.subject}</span>
                      </span>
                      <span className="flex items-center gap-2">
                        <SlaBadge sla={t.sla} compact />
                        <PriorityBadge priority={t.priority} />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            {data.attention_total > data.attention.length && (
              <p className="m-0 mt-2 text-sm text-muted-fg">
                {data.attention_total - data.attention.length} more in All my tickets.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle as="h3">My numbers · {data.period.label}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="m-0">
              <Number label="Avg first response" value={minutesText(n.avg_first_response_minutes)} />
              <Number label="Avg resolution" value={minutesText(n.avg_resolution_minutes)} />
              <Number label="SLA met" value={n.sla_met_percent === null ? "—" : `${n.sla_met_percent}%`} />
              <Number label="Reopened" value={n.reopened} />
              <Number label="Chats reviewed" value={n.chats_reviewed} />
            </dl>
            <p className="m-0 mt-2 text-xs text-muted-fg">Tickets you own, {label}.</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
