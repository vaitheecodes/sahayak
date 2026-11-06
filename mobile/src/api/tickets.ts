import type { ApiClient } from './client';
import type { CreatedTicket, Meta, NewTicket, ReplyResult, TicketDetail, TicketStatus, TicketSummary } from './types';

// Caps from backend/main.py (CreateTicketRequest, ChatMessageRequest).
export const SUBJECT_MAX = 200;
export const DESCRIPTION_MAX = 8000;
export const REPLY_MAX = 4000;

const ticketPath = (id: string) => `/api/tickets/${encodeURIComponent(id)}`;

export const ticketsApi = {
  mine: (api: ApiClient) => api.get<TicketSummary[]>('/api/tickets/mine'),
  /** Also marks every reply so far as read on the server. */
  detail: (api: ApiClient, id: string) => api.get<TicketDetail>(ticketPath(id)),
  create: (api: ApiClient, ticket: NewTicket) =>
    api.post<CreatedTicket>('/api/tickets', {
      subject: ticket.subject.trim(),
      description: ticket.description.trim(),
      priority: ticket.priority,
      category: ticket.category || null,
    }),
  reply: (api: ApiClient, id: string, message: string) =>
    api.post<ReplyResult>(`${ticketPath(id)}/reply`, { message: message.trim() }),
  reopen: (api: ApiClient, id: string) =>
    api.post<{ ticket_id: string; status: TicketStatus }>(`${ticketPath(id)}/reopen`),
};

export const metaApi = {
  get: (api: ApiClient) => api.get<Meta>('/api/meta', { auth: false }),
};
