import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';
import { NewTicketScreen } from '../../src/features/tickets/NewTicketScreen';
import { renderSignedIn } from '../../test/tickets';

const CREATED = { ticket_id: 'TCK-new', message_id: 'M1', ticket_type: 'ticket', route: 'ai', status: 'resolved', ai_response: 'Hi' };

async function setup(create: Parameters<typeof renderSignedIn>[1][string] = { body: CREATED }) {
  const onCreated = jest.fn();
  const r = await renderSignedIn(<NewTicketScreen onCreated={onCreated} />, { 'POST /api/tickets': create });
  // Categories come from /api/meta.
  await screen.findByRole('radio', { name: 'Billing & payments' });
  return { ...r, onCreated };
}

async function fill(subject = 'Payslip blank', description = 'The payslip page shows nothing since Monday.') {
  await fireEvent.changeText(screen.getByLabelText('Subject'), subject);
  await fireEvent.changeText(screen.getByLabelText('Description'), description);
}

const submit = () => fireEvent.press(screen.getByRole('button', { name: 'Submit ticket' }));
const posts = <T extends { method: string }>(calls: T[]) => calls.filter((c) => c.method === 'POST');

describe('NewTicketScreen', () => {
  it('asks for a subject and description without calling the server', async () => {
    const { calls } = await setup();
    await submit();
    expect(screen.getByText('Enter a subject.')).toBeOnTheScreen();
    expect(screen.getByText('Describe the problem.')).toBeOnTheScreen();
    expect(posts(calls)).toHaveLength(0);
    await fireEvent.changeText(screen.getByLabelText('Subject'), 'x');
    expect(screen.queryByText('Enter a subject.')).not.toBeOnTheScreen();
  });

  it('counts the description and blocks more than 8000 characters', async () => {
    const { calls } = await setup();
    await fill('Long one', 'y'.repeat(8001));
    expect(screen.getByText('8001 / 8000')).toBeOnTheScreen();
    await submit();
    expect(screen.getByText('Too long (at most 8000 characters).')).toBeOnTheScreen();
    expect(posts(calls)).toHaveLength(0);
  });

  it('sends subject, category, priority and description, then hands back the new ticket', async () => {
    const { calls, onCreated } = await setup();
    await fill();
    await fireEvent.press(screen.getByRole('radio', { name: 'Billing & payments' }));
    // A category without a label reads as a phrase.
    expect(screen.getByRole('radio', { name: 'Login access' })).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('radio', { name: 'Urgent' }));
    await submit();
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ ticket_id: 'TCK-new' })));
    expect(posts(calls)[0].body).toEqual({
      subject: 'Payslip blank',
      description: 'The payslip page shows nothing since Monday.',
      priority: 'urgent',
      category: 'BILLING',
    });
  });

  it('defaults to medium priority and no category', async () => {
    const { calls } = await setup();
    await fill();
    await submit();
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toMatchObject({ priority: 'medium', category: null });
  });

  it('puts 422 field errors under their fields', async () => {
    await setup({
      status: 422,
      body: {
        detail: [
          { loc: ['body', 'description'], type: 'string_too_long', msg: 'too long', ctx: { max_length: 8000 } },
          { loc: ['body', 'category'], type: 'value_error', msg: 'Value error, Unknown category' },
        ],
      },
    });
    await fill();
    await submit();
    expect(await screen.findByText('Description is too long (at most 8000 characters).')).toBeOnTheScreen();
    expect(screen.getByText("Category isn't valid.")).toBeOnTheScreen();
    expect(screen.getByTestId('new-ticket-error')).toHaveTextContent(/Description is too long.*Category isn't valid/s);
  });

  it('counts down a 429 and keeps Submit disabled until it ends', async () => {
    jest.useFakeTimers();
    try {
      await setup({ status: 429, body: { detail: 'Too many requests' }, headers: { 'Retry-After': '2' } });
      await fill();
      await submit();
      expect(await screen.findByText(/try again in 2 seconds/)).toBeOnTheScreen();
      expect(screen.getByRole('button', { name: 'Submit ticket' })).toBeDisabled();
      for (let i = 0; i < 2; i++) {
        await act(async () => {
          jest.advanceTimersByTime(1000);
        });
      }
      expect(screen.getByText('You can try again now.')).toBeOnTheScreen();
      expect(screen.getByRole('button', { name: 'Submit ticket' })).toBeEnabled();
    } finally {
      jest.useRealTimers();
    }
  });

  it('offers a retry when the help desk is busy, and it works', async () => {
    let fail = true;
    const { onCreated } = await setup(() => (fail ? { status: 503, body: { detail: 'busy' } } : { body: CREATED }));
    await fill();
    await submit();
    expect(await screen.findByText(/busy right now/)).toBeOnTheScreen();
    fail = false;
    await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
  });

  it('offers a retry when the phone is offline', async () => {
    const { impl } = await setup();
    (impl as jest.Mock).mockImplementationOnce(async () => {
      throw new TypeError('Network request failed');
    });
    await fill();
    await submit();
    expect(await screen.findByText(/Can't reach the help desk/)).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeOnTheScreen();
  });

  it('warns that a timed-out ticket may already exist, and offers no blind retry', async () => {
    const { impl } = await setup();
    // Never answers; the client gives up after its timeout.
    (impl as jest.Mock).mockImplementationOnce(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted')))),
    );
    await fill();
    jest.useFakeTimers();
    try {
      // RNTL waits for the press handler, which is waiting on the request.
      const pressed = submit();
      await act(async () => {
        jest.advanceTimersByTime(120_000);
      });
      await pressed;
      await act(async () => {
        jest.advanceTimersByTime(0);
      });
      expect(await screen.findByText(/may still have been created/)).toBeOnTheScreen();
      expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeOnTheScreen();
    } finally {
      jest.useRealTimers();
    }
  });
});
