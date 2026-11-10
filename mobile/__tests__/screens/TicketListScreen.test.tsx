import { act, fireEvent, screen, waitFor, within } from '@testing-library/react-native';
import { TicketListScreen } from '../../src/features/tickets/TicketListScreen';
import { renderSignedIn, summary } from '../../test/tickets';

// Focus = mount in tests; the app reloads each time the tab comes back.
jest.mock('expo-router', () => {
  const { useEffect } = jest.requireActual('react');
  return { useFocusEffect: (cb: () => void) => useEffect(cb, [cb]) };
});

const TICKETS = [
  summary({ ticket_id: 'TCK-a', subject: 'Login fails on mobile', status: 'open', escalated: true, unread: true }),
  summary({ ticket_id: 'TCK-b', subject: 'Invoice copy', status: 'pending_customer', ticket_type: 'chat' }),
  summary({ ticket_id: 'TCK-c', subject: 'Password reset email', status: 'resolved' }),
  summary({ ticket_id: 'TCK-d', subject: 'Payslip export', status: 'in_progress' }),
];

async function setup(routes = {}) {
  const onOpen = jest.fn();
  const onNew = jest.fn();
  const r = await renderSignedIn(<TicketListScreen onOpen={onOpen} onNew={onNew} />, {
    'GET /api/tickets/mine': { body: TICKETS },
    ...routes,
  });
  return { ...r, onOpen, onNew };
}

describe('TicketListScreen', () => {
  it('lists tickets with status labels from /api/meta, unread dot and chat badge', async () => {
    await setup();
    const row = await screen.findByTestId('ticket-TCK-a');
    expect(within(row).getByTestId('unread-dot')).toBeOnTheScreen();
    expect(within(row).getByText('Open')).toBeOnTheScreen();
    const chatRow = screen.getByTestId('ticket-TCK-b');
    expect(within(chatRow).getByText('Chat')).toBeOnTheScreen();
    // The admin's label for pending_customer, not the built-in one.
    expect(await within(chatRow).findByText('Waiting on you')).toBeOnTheScreen();
    expect(within(chatRow).queryByTestId('unread-dot')).not.toBeOnTheScreen();
    // The server's default staff label ("In Progress") becomes the customer word.
    expect(within(screen.getByTestId('ticket-TCK-d')).getByText('In progress')).toBeOnTheScreen();
  });

  it('shows an offline strip and reloads by itself when the connection comes back', async () => {
    const network = jest.requireMock('expo-network') as { __setConnected: (c: boolean) => void };
    let online = false;
    network.__setConnected(false);
    try {
      await setup({
        'GET /api/tickets/mine': () => {
          if (!online) throw new TypeError('Network request failed');
          return { body: TICKETS };
        },
      });
      expect(await screen.findByTestId('offline-banner')).toBeOnTheScreen();
      expect(await screen.findByTestId('tickets-error')).toBeOnTheScreen();
      online = true;
      await act(async () => network.__setConnected(true));
      expect(await screen.findByTestId('ticket-TCK-a')).toBeOnTheScreen();
      expect(screen.queryByTestId('offline-banner')).not.toBeOnTheScreen();
      expect(screen.queryByTestId('tickets-error')).not.toBeOnTheScreen();
    } finally {
      network.__setConnected(true);
    }
  });

  it('filters by tab', async () => {
    await setup();
    await screen.findByTestId('ticket-TCK-a');
    await fireEvent.press(screen.getByRole('radio', { name: 'Resolved' }));
    expect(screen.getByTestId('ticket-TCK-c')).toBeOnTheScreen();
    expect(screen.queryByTestId('ticket-TCK-a')).not.toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('radio', { name: 'Escalated' }));
    expect(screen.getByTestId('ticket-TCK-a')).toBeOnTheScreen();
    expect(screen.queryByTestId('ticket-TCK-b')).not.toBeOnTheScreen();
  });

  it('searches and says when nothing matches', async () => {
    await setup();
    await screen.findByTestId('ticket-TCK-a');
    await fireEvent.changeText(screen.getByLabelText('Search by subject or ticket #'), 'invoice');
    expect(screen.getByTestId('ticket-TCK-b')).toBeOnTheScreen();
    expect(screen.queryByTestId('ticket-TCK-a')).not.toBeOnTheScreen();
    await fireEvent.changeText(screen.getByLabelText('Search by subject or ticket #'), 'nothing like this');
    expect(screen.getByText('No tickets match')).toBeOnTheScreen();
    await fireEvent.press(screen.getAllByRole('button', { name: 'Clear search' })[0]);
    expect(screen.getByTestId('ticket-TCK-a')).toBeOnTheScreen();
  });

  it('opens a ticket', async () => {
    const { onOpen } = await setup();
    await fireEvent.press(await screen.findByTestId('ticket-TCK-c'));
    expect(onOpen).toHaveBeenCalledWith('TCK-c');
  });

  it('shows a clear empty state with a way to raise a ticket', async () => {
    const { onNew } = await setup({ 'GET /api/tickets/mine': { body: [] } });
    expect(await screen.findByText('No tickets yet')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Raise a ticket' }));
    expect(onNew).toHaveBeenCalled();
  });

  it('offers a retry when the server is unavailable', async () => {
    let fail = true;
    await setup({
      'GET /api/tickets/mine': () => (fail ? { status: 503, body: { detail: 'busy' } } : { body: TICKETS }),
    });
    expect(await screen.findByText(/busy right now/)).toBeOnTheScreen();
    fail = false;
    await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(screen.getByTestId('ticket-TCK-a')).toBeOnTheScreen());
    expect(screen.queryByTestId('tickets-error')).not.toBeOnTheScreen();
  });
});
