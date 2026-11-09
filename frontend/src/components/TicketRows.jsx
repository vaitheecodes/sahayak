import { ChatBadge } from "@/components/ChatBadge";
import { PriorityBadge, SlaBadge, StatusBadge } from "@/ui/status";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";
import { cn } from "@/lib/utils";
import { absoluteTime, relativeTime } from "@/utils/time";

/* Staff ticket rows: ID, Subject, Customer, Status, Priority, SLA, Updated.
 * From 768px a table; on a phone each ticket is two lines (ID and status,
 * then the subject), so nothing scrolls sideways. A row opens the ticket
 * (onOpen); `action` adds one trailing control (Claim). */
export default function TicketRows({ tickets, onOpen, selectedId, action, actionLabel }) {
  const updated = (t) => t.last_activity || t.updated_at || t.created_at;
  return (
    <>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Subject</TableHead>
              <TableHead>Customer</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Priority</TableHead>
              <TableHead>SLA</TableHead>
              <TableHead>Updated</TableHead>
              {action && (
                <TableHead>
                  <span className="sr-only">{actionLabel}</span>
                </TableHead>
              )}
            </TableRow>
          </TableHeader>
          <TableBody>
            {tickets.map((t) => (
              <TableRow
                key={t.ticket_id}
                data-state={selectedId === t.ticket_id ? "selected" : undefined}
                className="cursor-pointer"
                onClick={() => onOpen(t)}
              >
                <TableCell className="whitespace-nowrap">
                  <span className="inline-flex items-center gap-2">
                    <button
                      type="button"
                      className="cursor-pointer border-0 bg-transparent p-0 font-mono text-sm text-primary hover:underline"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpen(t);
                      }}
                    >
                      {t.ticket_id}
                    </button>
                    {t.ticket_type === "chat" && <ChatBadge />}
                  </span>
                </TableCell>
                <TableCell className="max-w-80">
                  <span className="block truncate" title={t.subject}>
                    {t.subject}
                  </span>
                </TableCell>
                <TableCell className="max-w-48">
                  <span className="block truncate" title={t.customer_email}>
                    {t.customer_name}
                  </span>
                </TableCell>
                <TableCell>
                  <StatusBadge status={t.status} />
                </TableCell>
                <TableCell>
                  <PriorityBadge priority={t.priority} />
                </TableCell>
                <TableCell>
                  <SlaBadge sla={t.sla} compact />
                </TableCell>
                <TableCell className="whitespace-nowrap text-sm text-muted-fg">
                  <time dateTime={updated(t)} title={absoluteTime(updated(t))}>
                    {relativeTime(updated(t))}
                  </time>
                </TableCell>
                {action && <TableCell>{action(t)}</TableCell>}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="m-0 list-none p-0 md:hidden">
        {tickets.map((t) => (
          <li
            key={t.ticket_id}
            className={cn(
              "flex items-center gap-3 border-b border-rule px-4 py-3 last:border-0",
              selectedId === t.ticket_id && "bg-active",
            )}
          >
            <button
              type="button"
              onClick={() => onOpen(t)}
              className="flex min-w-0 flex-1 cursor-pointer flex-col items-stretch rounded-none border-0 bg-transparent p-0 text-left text-fg shadow-none"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span className="font-mono text-sm text-primary">{t.ticket_id}</span>
                <StatusBadge status={t.status} />
                {t.ticket_type === "chat" && <ChatBadge />}
              </span>
              <span className="mt-1 block truncate text-base">{t.subject}</span>
            </button>
            {action && <span className="shrink-0">{action(t)}</span>}
          </li>
        ))}
      </ul>
    </>
  );
}
