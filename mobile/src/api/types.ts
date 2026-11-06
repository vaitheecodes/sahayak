// Response shapes from backend/main.py and docs/API.md (customer side).

export type Role = 'customer' | 'technician' | 'manager' | 'admin';

export type LoginResponse = {
  user_id: string;
  role: Role;
  name: string;
  must_change_password: boolean;
  token: string;
};

export type Me = {
  user_id: string;
  role: Role;
  name: string;
  email: string;
  must_change_password: boolean;
};

// --- Tickets (GET /api/tickets/mine, GET /api/tickets/{id}) ---------------

export type TicketStatus = 'open' | 'in_progress' | 'pending_customer' | 'resolved' | 'closed';
export type Priority = 'low' | 'medium' | 'high' | 'urgent';
export type Route = 'ai' | 'clarify' | 'human';

export type TicketSummary = {
  ticket_id: string;
  ticket_type: 'ticket' | 'chat';
  subject: string;
  status: TicketStatus;
  priority: Priority | null;
  category: string | null;
  created_at: string;
  last_updated: string;
  unread: boolean;
  /** With the support team (route human); drives the Escalated filter. */
  escalated: boolean;
};

export type Attachment = {
  attachment_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
};

export type ThreadMessage = {
  message_id: string;
  sender: 'customer' | 'ai' | 'staff' | 'system';
  sender_name: string;
  sender_role: string;
  to: string | null;
  subject: string | null;
  incident_update: boolean;
  message: string;
  created_at: string;
  attachments: Attachment[];
};

export type ChatTranscriptMessage = {
  message_id: string;
  role: 'customer' | 'ai';
  content: string;
  created_at: string;
};

export type TicketDetail = {
  incident_notice: string | null;
  chat: { session_id: string; transcript: ChatTranscriptMessage[] } | null;
  ticket: {
    ticket_id: string;
    ticket_type: 'ticket' | 'chat';
    subject: string;
    status: TicketStatus;
    route: Route | null;
    priority: Priority | null;
    category: string | null;
    created_at: string;
  };
  messages: ThreadMessage[];
};

export type NewTicket = {
  subject: string;
  description: string;
  priority: Priority;
  category: string | null;
};

export type CreatedTicket = {
  ticket_id: string;
  message_id: string;
  ticket_type: 'ticket';
  route: Route;
  status: TicketStatus;
  ai_response: string | null;
};

export type ReplyResult = {
  /** "closed" when the reply was a bare thank-you that closed the ticket. */
  route: Route | 'closed';
  status: TicketStatus;
  message_id: string;
  /** Set when the AI couldn't answer; the reply itself is saved. */
  ai_error?: string;
};

// --- Display config (GET /api/meta, public) ------------------------------

export type Meta = {
  status_labels: Record<TicketStatus, string>;
  categories: string[];
  category_labels: Record<string, string>;
  product: { name: string; support_team_name: string };
  kb_entries: number;
};
