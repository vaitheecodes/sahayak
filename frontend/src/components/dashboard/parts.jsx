import { Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { cn } from "@/lib/utils";
import { statusColor } from "@/lib/statusMeta";

/* Small building blocks shared by the manager and technician dashboards. */

const TONE_TEXT = { warning: "text-warning", negative: "text-negative", positive: "text-positive" };

/* One ruled strip of numbers (not a grid of cards): a caption that says
 * what the numbers count ("Now", "Created this week"), then label + value
 * cells. A cell with a status gets that status's square; the SLA cell a
 * clock. Phones wrap it to three columns. */
export function MetricStrip({ caption, items }) {
  return (
    <section aria-label={caption}>
      <h2 className="m-0 mb-1.5 text-sm font-medium text-muted-fg">{caption}</h2>
      <dl className="m-0 grid grid-cols-3 border-y border-border sm:grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))]">
        {items.map((item, i) => (
          <div
            key={item.label}
            className={cn("min-w-0 py-3 pr-3", i % 3 !== 0 && "pl-3 max-sm:border-l max-sm:border-border",
              i > 0 && "sm:border-l sm:border-border sm:pl-4")}
          >
            <dd className={cn("m-0 text-2xl font-semibold tabular-nums tracking-tight text-fg", TONE_TEXT[item.tone])}>
              {item.value}
            </dd>
            <dt className="m-0 flex items-start gap-1.5 text-sm leading-snug text-muted-fg sm:items-center">
              {item.status && (
                <span aria-hidden="true" className="mt-1.5 size-2 shrink-0 rounded-[2px] sm:mt-0" style={{ background: statusColor(item.status) }} />
              )}
              {item.clock && <Clock aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 sm:mt-0" />}
              <span className="sm:truncate">{item.label}</span>
            </dt>
            {item.hint && <p className="m-0 mt-0.5 text-xs text-muted-fg sm:truncate">{item.hint}</p>}
          </div>
        ))}
      </dl>
    </section>
  );
}

/* The totals of tickets created in the period, by current status; they add
 * up to Total (New is part of Open here; the kanban rail splits it). */
export function CreatedStrip({ period, byStatus, sla }) {
  return (
    <MetricStrip
      caption={`Created ${period.label.toLowerCase()}`}
      items={[
        { label: "Total", value: byStatus.total },
        { label: "Open", value: byStatus.new + byStatus.open, status: "open" },
        { label: "In progress", value: byStatus.in_progress, status: "in_progress" },
        { label: "Pending customer", value: byStatus.pending_customer, status: "pending_customer" },
        { label: "Resolved", value: byStatus.resolved, status: "resolved" },
        { label: "Closed", value: byStatus.closed, status: "closed" },
        {
          label: "SLA breached / at risk",
          value: `${sla.breached} / ${sla.at_risk}`,
          clock: true,
          tone: sla.breached ? "negative" : sla.at_risk ? "warning" : undefined,
        },
      ]}
    />
  );
}

/* Classic | Kanban. A pair of toggle buttons (aria-pressed), not tabs:
 * both show the same data. */
export function StyleToggle({ value, onChange }) {
  return (
    <div role="group" aria-label="Dashboard style" className="inline-flex rounded-lg border border-border-strong p-0.5">
      {[
        ["classic", "Classic"],
        ["kanban", "Kanban"],
      ].map(([key, label]) => (
        <button
          key={key}
          type="button"
          aria-pressed={value === key}
          onClick={() => onChange(key)}
          className={cn(
            "h-7 cursor-pointer rounded-md border-0 bg-transparent px-3 text-sm text-muted-fg shadow-none outline-none",
            "hover:text-fg focus-visible:ring-2 focus-visible:ring-ring",
            value === key && "bg-active font-medium text-fg",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/* Horizontal bars: one row per item, the bar's length relative to the
 * largest value. The numbers are text, so nothing depends on the bars. */
export function HBars({ title, rows, empty = "Nothing to show.", color = "var(--fg)" }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h3">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="m-0 text-sm text-muted-fg">{empty}</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
            {rows.map((r) => (
              <li key={r.key} className="grid grid-cols-[minmax(6rem,10rem)_minmax(0,1fr)_2.5rem] items-center gap-3">
                <span className="truncate text-sm text-fg" title={typeof r.label === "string" ? r.label : undefined}>
                  {r.label}
                </span>
                <span className="h-2 rounded-sm bg-active" aria-hidden="true">
                  <span
                    className="block h-full rounded-sm"
                    style={{ width: `${(100 * r.value) / max}%`, background: r.color || color }}
                  />
                </span>
                <span className="text-right text-sm font-medium tabular-nums text-fg">{r.value}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function minutesText(minutes) {
  if (minutes === null || minutes === undefined) return "—";
  if (minutes < 60) return `${Math.round(minutes)} min`;
  if (minutes < 60 * 24) return `${(minutes / 60).toFixed(minutes < 600 ? 1 : 0)} h`;
  return `${(minutes / 1440).toFixed(1)} d`;
}
