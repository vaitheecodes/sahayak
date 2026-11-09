import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { cn } from "@/lib/utils";

/* Small building blocks shared by the manager and technician dashboards. */

const TONE_TEXT = { warning: "text-warning", negative: "text-negative", positive: "text-positive" };

export function KpiCard({ label, value, hint, tone }) {
  return (
    <Card className="px-4 py-3">
      <p className="m-0 text-sm text-muted-fg">{label}</p>
      <p className={cn("m-0 mt-1 text-2xl font-semibold tabular-nums text-fg", TONE_TEXT[tone])}>{value}</p>
      {hint && <p className="m-0 mt-0.5 text-xs text-muted-fg">{hint}</p>}
    </Card>
  );
}

/* Horizontal bars: one row per item, the bar's length relative to the
 * largest value. The numbers are text, so nothing depends on the bars. */
export function HBars({ title, rows, empty = "Nothing to show." }) {
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
                <span className="truncate text-sm text-fg" title={r.label}>
                  {r.label}
                </span>
                <span className="h-2.5 rounded-sm bg-active" aria-hidden="true">
                  <span
                    className="block h-full rounded-sm"
                    style={{ width: `${(100 * r.value) / max}%`, background: "var(--chart-1)" }}
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
