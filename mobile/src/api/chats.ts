import type { ApiClient } from './client';
import type { ChatSession, ChatSummary } from './types';

// Caps from backend/chats.py (StartChatRequest, ChatMessageRequest,
// EscalateChatRequest).
export const ISSUE_MAX = 500;
export const CHAT_MESSAGE_MAX = 4000;
export const ESCALATE_SUBJECT_MAX = 200;

const chatPath = (id: string) => `/api/chats/${encodeURIComponent(id)}`;

export const chatsApi = {
  /** Newest first. Escalated ones also show up as tickets. */
  list: (api: ApiClient) => api.get<ChatSummary[]>('/api/chats'),
  get: (api: ApiClient, id: string) => api.get<ChatSession>(chatPath(id)),
  /** The issue is the first message; the AI answers it in the same call.
   *  The contact name defaults to the account's name on the server. */
  start: (api: ApiClient, issue: string, category: string | null) =>
    api.post<ChatSession>('/api/chats', { issue: issue.trim(), category: category || null }),
  send: (api: ApiClient, id: string, message: string) =>
    api.post<ChatSession>(`${chatPath(id)}/messages`, { message: message.trim() }),
  /** "My issue is solved". Needs at least one AI answer. */
  resolve: (api: ApiClient, id: string) => api.post<ChatSession>(`${chatPath(id)}/resolve`),
  /** "Raise a ticket": works even while the AI is unavailable. */
  escalate: (api: ApiClient, id: string, subject: string) =>
    api.post<ChatSession>(`${chatPath(id)}/escalate`, { subject: subject.trim() || null }),
};
