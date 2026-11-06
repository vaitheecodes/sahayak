import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import type { ThreadMessage, TicketDetail } from '../../src/api/types';
import { TicketDetailScreen } from '../../src/features/tickets/TicketDetailScreen';
import { detail, renderSignedIn } from '../../test/tickets';

const PATH = '/api/tickets/TCK-00000001';

async function setup(first: TicketDetail, routes = {}, after?: TicketDetail) {
  let loads = 0;
  const r = await renderSignedIn(<TicketDetailScreen ticketId="TCK-00000001" />, {
    [`GET ${PATH}`]: () => {
      loads += 1;
      return { body: loads > 1 && after ? after : first };
    },
    ...routes,
  });
  await screen.findByText(first.ticket.subject);
  return { ...r, loads: () => loads };
}

function msg(id: string, sender: ThreadMessage['sender'], message: string): ThreadMessage {
  return {
    message_id: id,
    sender,
    sender_name: sender === 'staff' ? 'Ravi Kumar' : sender === 'ai' ? 'Support Bot' : 'Asha Rao',
    sender_role: sender === 'staff' ? 'Support Agent' : 'AI Assistant',
    to: null,
    subject: null,
    incident_update: false,
    message,
    created_at: '2026-11-06T09:00:00+00:00',
    attachments: [],
  };
}

describe('TicketDetailScreen', () => {
  it('shows the header facts and the email-style thread', async () => {
    await setup(detail());
    expect(screen.getByText('TCK-00000001')).toBeOnTheScreen();
    expect(await screen.findByText('Waiting on you')).toBeOnTheScreen();
    expect(screen.getByText('Billing & payments')).toBeOnTheScreen();
    expect(screen.getByText('High')).toBeOnTheScreen();
    expect(screen.getByText('My payslip page is blank.')).toBeOnTheScreen();
    // AI replies render their Markdown list as items.
    expect(screen.getByText('Chrome')).toBeOnTheScreen();
    expect(screen.getByText('AI Assistant')).toBeOnTheScreen();
  });

  it('shows the incident notice and a collapsed chat transcript', async () => {
    await setup(
      detail({
        incident_notice: "We're aware of this issue affecting multiple customers and are working on it.",
        chat: {
          session_id: 'S1',
          transcript: [
            { message_id: 'C1', role: 'customer', content: 'Hi, payslip is blank', created_at: '2026-11-06T08:59:00+00:00' },
            { message_id: 'C2', role: 'ai', content: 'Let me pass this on.', created_at: '2026-11-06T08:59:10+00:00' },
          ],
        },
      }, { ticket_type: 'chat' }),
    );
    expect(screen.getByTestId('incident-notice')).toHaveTextContent(/aware of this issue/);
    expect(screen.getByText('(2 messages, before escalation)')).toBeOnTheScreen();
    expect(screen.queryByText('Hi, payslip is blank')).not.toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: /Chat transcript/ }));
    expect(screen.getByText('Hi, payslip is blank')).toBeOnTheScreen();
  });

  it('collapses the middle of a long thread', async () => {
    const messages = ['one', 'two', 'three', 'four', 'five', 'six'].map((m, i) =>
      msg(`M${i}`, i % 2 ? 'staff' : 'customer', `message ${m}`),
    );
    await setup(detail({ messages }));
    expect(screen.getByText('message one')).toBeOnTheScreen();
    expect(screen.queryByText('message three')).not.toBeOnTheScreen();
    expect(screen.getByText('message six')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Show 3 earlier messages' }));
    expect(screen.getByText('message three')).toBeOnTheScreen();
  });

  it('never hides the newest staff reply behind the collapse', async () => {
    const messages = [
      msg('M0', 'customer', 'message one'),
      msg('M1', 'ai', 'message two'),
      msg('M2', 'customer', 'message three'),
      msg('M3', 'staff', 'Fixed it on our side, please check'),
      msg('M4', 'system', 'Status changed to Resolved'),
      msg('M5', 'system', 'Assigned to Ravi Kumar'),
    ];
    await setup(detail({ messages }));
    expect(screen.getByText('Fixed it on our side, please check')).toBeOnTheScreen();
    expect(screen.queryByText('message two')).not.toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Show 2 earlier messages' }));
    expect(screen.getByText('message two')).toBeOnTheScreen();
  });

  it('sends a reply, clears the composer and reloads the thread', async () => {
    const updated = detail();
    updated.messages = [...updated.messages, msg('M3', 'customer', 'Chrome on Android')];
    const { calls, loads } = await setup(
      detail(),
      { [`POST ${PATH}/reply`]: { body: { route: 'clarify', status: 'pending_customer', message_id: 'M3' } } },
      updated,
    );
    const send = screen.getByRole('button', { name: 'Send' });
    expect(send).toBeDisabled();
    await fireEvent.changeText(screen.getByLabelText('Reply'), '  Chrome on Android ');
    expect(screen.getByText('17 / 4000')).toBeOnTheScreen();
    await fireEvent.press(send);
    await waitFor(() => expect(loads()).toBe(2));
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ message: 'Chrome on Android' });
    expect(await screen.findByText('Chrome on Android')).toBeOnTheScreen();
    expect(screen.getByLabelText('Reply')).toHaveDisplayValue('');
  });

  it('keeps the reply when the AI is unavailable and says so', async () => {
    await setup(detail(), {
      [`POST ${PATH}/reply`]: {
        body: { route: 'clarify', status: 'pending_customer', message_id: 'M3', ai_error: 'Our AI assistant is unavailable right now.' },
      },
    });
    await fireEvent.changeText(screen.getByLabelText('Reply'), 'hello');
    await fireEvent.press(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByTestId('reply-notice')).toHaveTextContent(/unavailable right now/);
  });

  it('blocks a reply over 4000 characters', async () => {
    const { calls } = await setup(detail());
    await fireEvent.changeText(screen.getByLabelText('Reply'), 'x'.repeat(4001));
    expect(screen.getByText('4001 / 4000')).toBeOnTheScreen();
    expect(screen.getByText(/at most 4000 characters/)).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('counts down a rate limit on reply', async () => {
    await setup(detail(), {
      [`POST ${PATH}/reply`]: { status: 429, body: { detail: 'Too many requests' }, headers: { 'Retry-After': '30' } },
    });
    await fireEvent.changeText(screen.getByLabelText('Reply'), 'hello');
    await fireEvent.press(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText(/try again in 30 seconds/)).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  it('reopens a resolved ticket and reloads it', async () => {
    const { calls, loads } = await setup(
      detail({}, { status: 'resolved', route: 'ai' }),
      { [`POST ${PATH}/reopen`]: { body: { ticket_id: 'TCK-00000001', status: 'open' } } },
      detail({}, { status: 'open', route: 'human' }),
    );
    await fireEvent.press(screen.getByRole('button', { name: 'Reopen ticket' }));
    await waitFor(() => expect(loads()).toBe(2));
    expect(calls.some((c) => c.path === `${PATH}/reopen`)).toBe(true);
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Reopen ticket' })).not.toBeOnTheScreen());
  });

  it('shows the server reason when reopening fails', async () => {
    await setup(detail({}, { status: 'resolved' }), {
      [`POST ${PATH}/reopen`]: { status: 400, body: { detail: 'Only resolved tickets can be reopened' } },
    });
    await fireEvent.press(screen.getByRole('button', { name: 'Reopen ticket' }));
    expect(await screen.findByText('Only resolved tickets can be reopened')).toBeOnTheScreen();
  });

  it('has no composer once closed', async () => {
    await setup(detail({}, { status: 'closed' }));
    expect(screen.getByText(/This ticket is closed/)).toBeOnTheScreen();
    expect(screen.queryByLabelText('Reply')).not.toBeOnTheScreen();
    expect(screen.queryByRole('button', { name: 'Reopen ticket' })).not.toBeOnTheScreen();
  });

  it('explains a ticket that is not available', async () => {
    await renderSignedIn(<TicketDetailScreen ticketId="TCK-00000001" />, {
      [`GET ${PATH}`]: { status: 404, body: { detail: 'Ticket not found' } },
    });
    expect(await screen.findByText("This ticket isn't available.")).toBeOnTheScreen();
  });
});
