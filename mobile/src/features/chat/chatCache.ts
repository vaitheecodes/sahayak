import type { ChatSession } from '../../api/types';

// Hands a just-started chat (the POST already returned the whole session,
// AI answer included) to its screen, so opening it costs no refetch.
const primed = new Map<string, ChatSession>();

export function primeChat(session: ChatSession): void {
  primed.set(session.session_id, session);
}

export function takePrimedChat(sessionId: string): ChatSession | null {
  const session = primed.get(sessionId) ?? null;
  primed.delete(sessionId);
  return session;
}
