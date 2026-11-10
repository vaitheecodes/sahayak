import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";

/* Small building blocks shared by the manager and technician dashboards. */

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
