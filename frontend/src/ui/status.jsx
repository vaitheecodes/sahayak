/* One vocabulary for every ticket mark, learned once.
 *
 *   status    a squared chip: its own colour + icon + word, the same on every
 *             page, rail and chart (theme.css --status-*). New is not a
 *             stored status: an open ticket nobody has picked up yet.
 *   SLA       a clock + words, no fill, so it never reads as a status. Amber
 *             (at risk) is used by nothing else, so amber means "act soon".
 *   priority  signal bars in ink; only urgent is red.
 *   route     ai / clarify = accent (the bot), human = neutral
 *
 * Colour never carries meaning alone: there is always an icon and a word. */

import { Circle, Clock } from "lucide-react";
import { BOT_NAME } from "@/lib/people";
import { cn } from "@/lib/utils";
import { Badge } from "@/ui/badge";
import { PRIORITY_LABELS } from "@/utils/priorities";
import { STATUS_META, statusText } from "@/lib/statusMeta";
import { statusLabel } from "@/utils/statusLabels";
import { absoluteTime, dueText } from "@/utils/time";

export function StatusIcon({ status, className }) {
  const Icon = STATUS_META[status]?.icon || Circle;
  return (
    <Icon
      aria-hidden="true"
      className={cn("size-3.5 shrink-0", className)}
      style={{ color: `var(--status-${STATUS_META[status]?.token || "closed"}-fg)` }}
      strokeWidth={2}
    />
  );
}

export function StatusBadge({ status, label, className }) {
  const meta = STATUS_META[status];
  if (!meta) return <Badge className={className}>{label || statusLabel(status)}</Badge>;
  const Icon = meta.icon;
  return (
    <span
      data-slot="status"
      className={cn(
        "inline-flex h-[22px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md pr-2 pl-1.5 text-sm font-medium",
        className,
      )}
      style={{ background: `var(--status-${meta.token}-bg)`, color: `var(--status-${meta.token}-fg)` }}
    >
      <Icon aria-hidden="true" className="size-3.5" strokeWidth={2} />
      {label || statusText(status)}
    </span>
  );
}

const PRIORITY_LEVEL = { low: 1, medium: 2, high: 3, urgent: 4 };

export function PriorityBadge({ priority, className }) {
  if (!priority) return <span className="text-muted-fg">—</span>;
  const level = PRIORITY_LEVEL[priority] || 0;
  const urgent = priority === "urgent";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-sm",
        urgent ? "font-medium text-negative" : "text-muted-fg",
        className,
      )}
    >
      <span aria-hidden="true" className="inline-flex h-3 items-end gap-[2px]">
        {[4, 7, 10, 12].map((h, i) => (
          <span
            key={h}
            className={cn(
              "w-[3px] rounded-[1px]",
              i < level ? (urgent ? "bg-negative" : "bg-fg") : "bg-border-strong",
            )}
            style={{ height: h }}
          />
        ))}
      </span>
      {PRIORITY_LABELS[priority] || priority}
    </span>
  );
}

const ROUTE = {
  ai: ["accent", BOT_NAME],
  clarify: ["accent", "Clarifying"],
  human: ["neutral", "Support team"],
};

export function RouteBadge({ route, className }) {
  if (!route) return null;
  const [tone, label] = ROUTE[route] || ["neutral", route];
  return (
    <Badge tone={tone} className={className}>
      {label}
    </Badge>
  );
}

const SLA_STATES = {
  on_track: { color: "text-positive", label: "On track" },
  at_risk: { color: "text-warning", label: "At risk" },
  breached: { color: "text-negative", label: "Breached" },
  met: { color: "text-positive", label: "Met" },
  paused: { color: "text-muted-fg", label: "Paused" },
};

const TARGET_LABEL = { first_response: "First response", resolution: "Resolution" };

// The running target nearest to (or past) its due time.
function focusTarget(sla) {
  const running = ["first_response", "resolution"].filter((k) => !sla[k].done_at && sla[k].state !== "paused");
  if (running.length === 0) return null;
  return running.sort((a, b) => new Date(sla[a].due_at) - new Date(sla[b].due_at))[0];
}

function SlaMark({ state, children, title }) {
  const meta = SLA_STATES[state] || SLA_STATES.on_track;
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap text-sm font-medium", meta.color)} title={title}>
      <Clock aria-hidden="true" className="size-3.5" strokeWidth={2} />
      {children || meta.label}
    </span>
  );
}

export function SlaStateBadge({ state }) {
  if (!SLA_STATES[state]) return null;
  return <SlaMark state={state} />;
}

/* A ticket's SLA (backend/sla.py evaluate()): the worst state of its two
 * targets and, unless compact, which target is due when. */
export function SlaBadge({ sla, compact = false }) {
  if (!sla) return <span className="text-muted-fg">—</span>;
  const meta = SLA_STATES[sla.state] || SLA_STATES.on_track;
  const target = focusTarget(sla);
  const detail = target ? `${TARGET_LABEL[target]} ${dueText(sla[target].due_at)}` : null;
  const title = ["first_response", "resolution"]
    .map((k) => `${TARGET_LABEL[k]}: ${SLA_STATES[sla[k].state]?.label} (due ${absoluteTime(sla[k].due_at)})`)
    .join("\n");
  return (
    <span className="inline-flex flex-wrap items-center gap-2" title={title}>
      <SlaMark state={sla.state}>{compact ? meta.label : `SLA ${meta.label.toLowerCase()}`}</SlaMark>
      {!compact && detail && <span className="text-sm tabular-nums text-muted-fg">{detail}</span>}
    </span>
  );
}
