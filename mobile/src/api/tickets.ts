import type { ApiClient } from './client';
import type { Attachment, CreatedTicket, Meta, NewTicket, ReplyResult, TicketDetail, TicketStatus, TicketSummary } from './types';

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
  /** Attaches files to one of the customer's own messages (the new ticket's
   *  first message, or a reply). The server checks every file before it
   *  stores any, so a refused upload can be retried as a whole. */
  uploadAttachments: (api: ApiClient, id: string, messageId: string, files: UploadPart[]) => {
    const form = new FormData();
    form.append('message_id', messageId);
    for (const f of files) form.append('files', f.blob, f.name);
    return api.postForm<Attachment[]>(`${ticketPath(id)}/attachments`, form);
  },
  downloadAttachment: (api: ApiClient, id: string, attachmentId: string) =>
    api.getBytes(`${ticketPath(id)}/attachments/${encodeURIComponent(attachmentId)}`),
};

/** One file in an upload. On the phone `blob` is an expo-file-system File,
 *  which implements Blob, so fetch sends a real Content-Length (the server
 *  refuses chunked uploads with 411). */
export type UploadPart = { name: string; blob: Blob };

export const metaApi = {
  get: (api: ApiClient) => api.get<Meta>('/api/meta', { auth: false }),
};
