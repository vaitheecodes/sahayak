import { createApiClient } from '../../src/api/client';
import { chatsApi } from '../../src/api/chats';
import type { ThreadMessage } from '../../src/api/types';
import { threadItems } from '../../src/features/tickets/threadView';
import { fakeFetch } from '../../test/fakeFetch';
import { chatSession, chatSummary } from '../../test/tickets';

function client(routes: Parameters<typeof fakeFetch>[0]) {
  const fake = fakeFetch(routes);
  const api = createApiClient({ baseUrl: 'https://api.test', getToken: () => 'tok', fetchImpl: fake.impl });
  return { api, calls: fake.calls };
}

describe('chatsApi', () => {
  it('lists chats and loads one by escaped id', async () => {
    const { api, calls } = client({
      'GET /api/chats': { body: [chatSummary()] },
      'GET /api/chats/CHAT-1%2F2': { body: chatSession() },
    });
    expect((await chatsApi.list(api))[0].session_id).toBe('CHAT-00000001');
    await chatsApi.get(api, 'CHAT-1/2');
    expect(calls[1].path).toBe('/api/chats/CHAT-1%2F2');
    expect(calls[0].headers.Authorization).toBe('Bearer tok');
  });

  it('starts a chat with trimmed text and no empty category', async () => {
    const { api, calls } = client({ 'POST /api/chats': { body: chatSession() } });
    await chatsApi.start(api, '  Export fails \n', '');
    await chatsApi.start(api, 'Export fails', 'BILLING');
    expect(calls[0].body).toEqual({ issue: 'Export fails', category: null });
    expect(calls[1].body).toEqual({ issue: 'Export fails', category: 'BILLING' });
  });

  it('sends, resolves and escalates on the chat path', async () => {
    const { api, calls } = client({
      'POST /api/chats/C1/messages': { body: chatSession() },
      'POST /api/chats/C1/resolve': { body: chatSession({ status: 'resolved' }) },
      'POST /api/chats/C1/escalate': { body: chatSession({ status: 'escalated', ticket_id: 'TCK-9' }) },
    });
    await chatsApi.send(api, 'C1', ' still blank ');
    await chatsApi.resolve(api, 'C1');
    const escalated = await chatsApi.escalate(api, 'C1', '   ');
    expect(calls[0].body).toEqual({ message: 'still blank' });
    expect(calls[1].body).toEqual({});
    // An empty subject lets the server use the chat's issue.
    expect(calls[2].body).toEqual({ subject: null });
    expect(escalated.ticket_id).toBe('TCK-9');
  });
});

function m(id: string, sender: ThreadMessage['sender']): ThreadMessage {
  return {
    message_id: id,
    sender,
    sender_name: sender,
    sender_role: sender,
    to: null,
    subject: null,
    incident_update: false,
    message: id,
    created_at: '2026-11-06T09:00:00+00:00',
    attachments: [],
  };
}

const ids = (items: ReturnType<typeof threadItems>) =>
  items.map((i) => (i.kind === 'message' ? i.message.message_id : `+${i.count}`));

describe('threadItems', () => {
  it('shows short threads, and every message once expanded', () => {
    const four = [m('a', 'customer'), m('b', 'ai'), m('c', 'customer'), m('d', 'ai')];
    expect(ids(threadItems(four, false))).toEqual(['a', 'b', 'c', 'd']);
    const six = [...four, m('e', 'customer'), m('f', 'ai')];
    expect(ids(threadItems(six, true))).toEqual(['a', 'b', 'c', 'd', 'e', 'f']);
  });

  it('keeps the first message and the two latest', () => {
    const six = ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => m(id, 'customer'));
    expect(ids(threadItems(six, false))).toEqual(['a', '+3', 'e', 'f']);
  });

  it('keeps the newest staff reply even when status lines follow it', () => {
    const thread = [
      m('ask', 'customer'),
      m('bot', 'ai'),
      m('old-staff', 'staff'),
      m('more', 'customer'),
      m('staff', 'staff'),
      m('sys1', 'system'),
      m('sys2', 'system'),
      m('sys3', 'system'),
    ];
    expect(ids(threadItems(thread, false))).toEqual(['ask', '+3', 'staff', '+1', 'sys2', 'sys3']);
  });
});
