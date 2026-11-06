import { createApiClient } from '../../src/api/client';
import { metaApi, ticketsApi } from '../../src/api/tickets';
import { filterTickets } from '../../src/features/tickets/filters';
import { charCount } from '../../src/lib/charCount';
import { fakeFetch } from '../../test/fakeFetch';
import { summary } from '../../test/tickets';

function client(routes: Parameters<typeof fakeFetch>[0]) {
  const fake = fakeFetch(routes);
  const api = createApiClient({ baseUrl: 'https://api.test', getToken: () => 'tok', fetchImpl: fake.impl });
  return { api, calls: fake.calls };
}

describe('ticketsApi', () => {
  it('lists my tickets with the bearer token', async () => {
    const { api, calls } = client({ 'GET /api/tickets/mine': { body: [summary()] } });
    const list = await ticketsApi.mine(api);
    expect(list[0].ticket_id).toBe('TCK-00000001');
    expect(calls[0].headers.Authorization).toBe('Bearer tok');
  });

  it('loads one ticket by id, escaping the path', async () => {
    const { api, calls } = client({ 'GET /api/tickets/TCK-1%2F2': { body: { ticket: {} } } });
    await ticketsApi.detail(api, 'TCK-1/2');
    expect(calls[0].path).toBe('/api/tickets/TCK-1%2F2');
  });

  it('creates a ticket with trimmed text and no empty category', async () => {
    const { api, calls } = client({ 'POST /api/tickets': { body: { ticket_id: 'TCK-9' } } });
    await ticketsApi.create(api, { subject: '  Login  ', description: ' Broken \n', priority: 'high', category: '' });
    expect(calls[0].body).toEqual({ subject: 'Login', description: 'Broken', priority: 'high', category: null });
  });

  it('replies and reopens on the ticket path', async () => {
    const { api, calls } = client({
      'POST /api/tickets/TCK-1/reply': { body: { route: 'human', status: 'open', message_id: 'M9' } },
      'POST /api/tickets/TCK-1/reopen': { body: { ticket_id: 'TCK-1', status: 'open' } },
    });
    const reply = await ticketsApi.reply(api, 'TCK-1', ' thanks, still broken ');
    await ticketsApi.reopen(api, 'TCK-1');
    expect(reply.message_id).toBe('M9');
    expect(calls[0].body).toEqual({ message: 'thanks, still broken' });
    expect(calls[1].method).toBe('POST');
  });

  it('reads /api/meta without a token', async () => {
    const { api, calls } = client({ 'GET /api/meta': { body: { categories: [] } } });
    await metaApi.get(api);
    expect(calls[0].headers.Authorization).toBeUndefined();
  });
});

describe('filterTickets', () => {
  const tickets = [
    summary({ ticket_id: 'TCK-a', subject: 'Login fails', status: 'open', escalated: true }),
    summary({ ticket_id: 'TCK-b', subject: 'Invoice copy', status: 'pending_customer' }),
    summary({ ticket_id: 'TCK-c', subject: 'Login question', status: 'resolved', escalated: true }),
    summary({ ticket_id: 'TCK-d', subject: 'Old thing', status: 'closed' }),
    summary({ ticket_id: 'TCK-e', subject: 'Being worked', status: 'in_progress', escalated: true }),
  ];
  const ids = (list: { ticket_id: string }[]) => list.map((t) => t.ticket_id);

  it('matches the web tabs', () => {
    expect(ids(filterTickets(tickets, 'all', ''))).toHaveLength(5);
    expect(ids(filterTickets(tickets, 'open', ''))).toEqual(['TCK-a', 'TCK-b', 'TCK-e']);
    expect(ids(filterTickets(tickets, 'resolved', ''))).toEqual(['TCK-c', 'TCK-d']);
    // Escalated = with the support team and not finished.
    expect(ids(filterTickets(tickets, 'escalated', ''))).toEqual(['TCK-a', 'TCK-e']);
  });

  it('searches subject and ticket # case-insensitively within the tab', () => {
    expect(ids(filterTickets(tickets, 'all', '  LOGIN '))).toEqual(['TCK-a', 'TCK-c']);
    expect(ids(filterTickets(tickets, 'open', 'login'))).toEqual(['TCK-a']);
    expect(ids(filterTickets(tickets, 'all', 'tck-d'))).toEqual(['TCK-d']);
  });
});

describe('charCount', () => {
  it('counts code points of the trimmed text, like the server', () => {
    expect(charCount('  ab  ')).toBe(2);
    expect(charCount('👍🏽')).toBe(2);
    expect('👍🏽'.length).toBe(4);
  });
});
