import type { TicketSummary } from '../../api/types';

// Same tabs as the web portal's My tickets (frontend CustomerPortal.jsx).
export type TicketFilter = 'all' | 'open' | 'resolved' | 'escalated';

export const TICKET_FILTERS: TicketFilter[] = ['all', 'open', 'resolved', 'escalated'];

const DONE = ['resolved', 'closed'];

const MATCH: Record<TicketFilter, (t: TicketSummary) => boolean> = {
  all: () => true,
  open: (t) => ['open', 'in_progress', 'pending_customer'].includes(t.status),
  resolved: (t) => DONE.includes(t.status),
  escalated: (t) => t.escalated && !DONE.includes(t.status),
};

/** Filter tab, then a case-insensitive search on subject or ticket #. */
export function filterTickets(tickets: TicketSummary[], filter: TicketFilter, query: string): TicketSummary[] {
  const q = query.trim().toLowerCase();
  return tickets.filter(
    (t) =>
      MATCH[filter](t) &&
      (!q || t.subject.toLowerCase().includes(q) || t.ticket_id.toLowerCase().includes(q)),
  );
}
