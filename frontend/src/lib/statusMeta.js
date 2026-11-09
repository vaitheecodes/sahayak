/* Ticket status colours and icons (theme.css --status-*), shared by the
 * status badges, the dashboard rails and the charts. New is not a stored
 * status: an open ticket nobody has picked up yet. */

import { CircleCheck, Circle, Contrast, Hourglass, Lock, Sparkle } from "lucide-react";
import { statusLabel } from "@/utils/statusLabels";

export const STATUS_META = {
  new: { icon: Sparkle, token: "new", label: "New" },
  open: { icon: Circle, token: "open" },
  in_progress: { icon: Contrast, token: "progress" },
  pending_customer: { icon: Hourglass, token: "pending" },
  resolved: { icon: CircleCheck, token: "resolved" },
  closed: { icon: Lock, token: "closed" },
};

export const statusText = (status) => STATUS_META[status]?.label || statusLabel(status);
// The solid colour of a status, for bars, dots and chart series.
export const statusColor = (status) => `var(--status-${STATUS_META[status]?.token || "closed"})`;

