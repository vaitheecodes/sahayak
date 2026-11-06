import type { ThreadMessage } from '../../api/types';

// Long threads collapse their middle, as on the web (TicketThread.jsx): the
// first message and the two latest stay open. Unlike the web, the newest
// staff reply also always stays open, so status lines after it can't hide
// the answer the customer is waiting for.
export const COLLAPSE_AFTER = 4;
export const COLLAPSE_KEEP_LATEST = 2;

export type ThreadItem = { kind: 'message'; message: ThreadMessage } | { kind: 'hidden'; count: number; key: string };

export function threadItems(messages: ThreadMessage[], expanded: boolean): ThreadItem[] {
  if (expanded || messages.length <= COLLAPSE_AFTER) {
    return messages.map((message) => ({ kind: 'message', message }));
  }
  const keep = new Set<number>([0]);
  for (let i = Math.max(1, messages.length - COLLAPSE_KEEP_LATEST); i < messages.length; i++) keep.add(i);
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].sender === 'staff') {
      keep.add(i);
      break;
    }
  }

  const items: ThreadItem[] = [];
  let hidden = 0;
  messages.forEach((message, i) => {
    if (keep.has(i)) {
      if (hidden) items.push({ kind: 'hidden', count: hidden, key: `hidden-${i}` });
      hidden = 0;
      items.push({ kind: 'message', message });
    } else {
      hidden++;
    }
  });
  return items;
}
