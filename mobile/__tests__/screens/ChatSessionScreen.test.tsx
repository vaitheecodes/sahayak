import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';
import type { ChatSession } from '../../src/api/types';
import { ChatSessionScreen } from '../../src/features/chat/ChatSessionScreen';
import type { FakeReply } from '../../test/fakeFetch';
import { chatLine, chatSession, hangOnce, renderSignedIn } from '../../test/tickets';

const PATH = '/api/chats/CHAT-00000001';

type Handler = FakeReply | (() => FakeReply | Promise<FakeReply>);

async function setup(
  first: ChatSession,
  routes: Record<string, Handler> = {},
  opts: { initial?: boolean; timeoutMs?: number } = {},
) {
  const onOpenTicket = jest.fn();
  const onNewChat = jest.fn();
  let loads = 0;
  const r = await renderSignedIn(
    <ChatSessionScreen
      sessionId="CHAT-00000001"
      initial={opts.initial ? first : null}
      onOpenTicket={onOpenTicket}
      onNewChat={onNewChat}
    />,
    {
      [`GET ${PATH}`]: () => {
        loads += 1;
        return { body: first };
      },
      ...routes,
    },
    { timeoutMs: opts.timeoutMs },
  );
  await screen.findAllByText(first.issue);
  return { ...r, onOpenTicket, onNewChat, loads: () => loads };
}

const composer = () => screen.getByLabelText('Message');
const sendButton = () => screen.getByRole('button', { name: 'Send' });

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

const withReply = (text: string, reply: string, extra: Partial<ChatSession> = {}) => {
  const base = chatSession();
  return chatSession({
    messages: [...base.messages, chatLine('CM3', 'customer', text), chatLine('CM4', 'ai', reply)],
    ...extra,
  });
};

describe('ChatSessionScreen', () => {
  it('opens on a just-started chat without refetching it', async () => {
    const { loads } = await setup(chatSession(), {}, { initial: true });
    expect(screen.getAllByText('How do I add a team member?').length).toBeGreaterThan(0);
    // The AI's Markdown answer renders as a list.
    expect(screen.getByText('Choose Team')).toBeOnTheScreen();
    expect(loads()).toBe(0);
  });

  it('sends a message, shows it and a typing indicator, then the reply', async () => {
    const gate = deferred<FakeReply>();
    const { calls } = await setup(chatSession(), { [`POST ${PATH}/messages`]: () => gate.promise });
    expect(sendButton()).toBeDisabled();
    await fireEvent.changeText(composer(), '  It says I have no seats left ');
    expect(screen.getByText('28 / 4000')).toBeOnTheScreen();

    const pressed = fireEvent.press(sendButton());
    expect(await screen.findByTestId('typing-indicator')).toBeOnTheScreen();
    expect(screen.getByTestId('chat-message-pending')).toHaveTextContent(/It says I have no seats left/);
    expect(composer()).toHaveDisplayValue('');

    gate.resolve({ body: withReply('It says I have no seats left', 'You can buy more seats under Billing.') });
    await pressed;
    expect(await screen.findByText('You can buy more seats under Billing.')).toBeOnTheScreen();
    expect(screen.queryByTestId('typing-indicator')).not.toBeOnTheScreen();
    expect(screen.queryByTestId('chat-message-pending')).not.toBeOnTheScreen();
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ message: 'It says I have no seats left' });
  });

  it("shows the server's follow-up question as written and takes a typed answer", async () => {
    const question = 'What exactly do you want to set up, and in which part of the product: Payroll, Leave or Attendance?';
    const first = chatSession({
      issue: 'how do I set it up',
      messages: [chatLine('CM1', 'customer', 'how do I set it up'), chatLine('CM2', 'ai', question)],
    });
    const { calls } = await setup(first, {
      [`POST ${PATH}/messages`]: { body: withReply('Leave', 'Open Leave, then Policies.') },
    });
    expect(screen.getByText(question)).toBeOnTheScreen();
    // The session view marks no fixed choices, so none become buttons.
    expect(screen.queryByRole('button', { name: 'Leave' })).not.toBeOnTheScreen();
    expect(screen.getByPlaceholderText('Ask a follow-up…')).toBeOnTheScreen();
    await fireEvent.changeText(composer(), 'Leave');
    await fireEvent.press(sendButton());
    expect(await screen.findByText('Open Leave, then Policies.')).toBeOnTheScreen();
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ message: 'Leave' });
  });

  it('blocks a message over 4000 characters', async () => {
    await setup(chatSession());
    await fireEvent.changeText(composer(), 'x'.repeat(4001));
    expect(screen.getByText(/at most 4000 characters/)).toBeOnTheScreen();
    expect(sendButton()).toBeDisabled();
  });

  it('"My issue is solved" waits for an answer, then closes the chat read-only', async () => {
    const unanswered = chatSession({ messages: [chatLine('CM1', 'customer', 'How do I add a team member?')] });
    const { calls, onNewChat } = await setup(unanswered);
    expect(screen.getByRole('button', { name: 'My issue is solved' })).toBeDisabled();
    calls.length = 0;

    // Once answered, it's enabled.
    const answered = chatSession();
    const { onNewChat: onNew2 } = await setup(answered, {
      [`POST ${PATH}/resolve`]: {
        body: chatSession({
          status: 'resolved',
          messages: [...answered.messages, chatLine('CM3', 'ai', "Glad that's sorted. I've closed this chat.")],
        }),
      },
    });
    expect(onNewChat).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByRole('button', { name: 'My issue is solved' }));
    expect(await screen.findByText(/This chat is resolved and closed/)).toBeOnTheScreen();
    expect(screen.queryByLabelText('Message')).not.toBeOnTheScreen();
    expect(screen.queryByRole('button', { name: 'Raise a ticket' })).not.toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Start a new chat' }));
    expect(onNew2).toHaveBeenCalled();
  });

  it('raises a ticket after confirming the subject, then links to it', async () => {
    const { calls, onOpenTicket } = await setup(chatSession(), {
      [`POST ${PATH}/escalate`]: { body: chatSession({ status: 'escalated', ticket_id: 'TCK-42' }) },
    });
    await fireEvent.press(screen.getByRole('button', { name: 'Raise a ticket' }));
    const subject = screen.getByLabelText('Ticket subject');
    expect(subject).toHaveDisplayValue('How do I add a team member?');
    await fireEvent.changeText(subject, 'Team invite');
    await fireEvent.press(screen.getByRole('button', { name: 'Create ticket' }));
    expect(await screen.findByText(/Escalated to our support team as ticket TCK-42/)).toBeOnTheScreen();
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ subject: 'Team invite' });
    expect(screen.queryByLabelText('Message')).not.toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Open ticket' }));
    expect(onOpenTicket).toHaveBeenCalledWith('TCK-42');
  });

  it('cancelling the confirmation brings the composer back', async () => {
    await setup(chatSession());
    await fireEvent.press(screen.getByRole('button', { name: 'Raise a ticket' }));
    expect(screen.queryByLabelText('Message')).not.toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Cancel' }));
    expect(composer()).toBeOnTheScreen();
  });

  it('when the AI is unavailable, shows the notice with "Raise a ticket instead"', async () => {
    const unavailable = 'Our AI assistant is unavailable right now. Your messages are saved.';
    const base = chatSession();
    await setup(base, {
      [`POST ${PATH}/messages`]: {
        body: chatSession({ messages: [...base.messages, chatLine('CM3', 'customer', 'Still stuck')], ai_error: unavailable }),
      },
    });
    await fireEvent.changeText(composer(), 'Still stuck');
    await fireEvent.press(sendButton());
    expect(await screen.findByTestId('chat-notice')).toHaveTextContent(/unavailable right now/);
    // The message is kept.
    expect(screen.getByText('Still stuck')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Raise a ticket instead' }));
    expect(screen.getByTestId('raise-ticket-confirm')).toBeOnTheScreen();
  });

  it('a hand-off by the server makes the chat read-only with a link to the ticket', async () => {
    const base = chatSession();
    await setup(base, {
      [`POST ${PATH}/messages`]: {
        body: chatSession({
          status: 'escalated',
          ticket_id: 'TCK-55',
          messages: [
            ...base.messages,
            chatLine('CM3', 'customer', 'I want a human'),
            chatLine('CM4', 'ai', "I've passed this to our support team as ticket TCK-55."),
          ],
        }),
      },
    });
    await fireEvent.changeText(composer(), 'I want a human');
    await fireEvent.press(sendButton());
    expect(await screen.findByRole('button', { name: 'Open ticket' })).toBeOnTheScreen();
    expect(screen.queryByLabelText('Message')).not.toBeOnTheScreen();
  });

  it('counts down a rate limit, keeps Send disabled and gives the text back', async () => {
    await setup(chatSession(), {
      [`POST ${PATH}/messages`]: { status: 429, body: { detail: 'Too many messages' }, headers: { 'Retry-After': '2' } },
    });
    await fireEvent.changeText(composer(), 'Still stuck');
    jest.useFakeTimers();
    try {
      await fireEvent.press(sendButton());
      expect(await screen.findByText(/try again in 2 seconds/)).toBeOnTheScreen();
      expect(composer()).toHaveDisplayValue('Still stuck');
      expect(sendButton()).toBeDisabled();
      for (let i = 0; i < 2; i++) {
        await act(async () => {
          jest.advanceTimersByTime(1000);
        });
      }
      expect(screen.getByText('You can try again now.')).toBeOnTheScreen();
      expect(sendButton()).toBeEnabled();
    } finally {
      jest.useRealTimers();
    }
  });

  it('offers Try again after a network failure and resends', async () => {
    let posts = 0;
    const { impl } = await setup(chatSession(), {
      [`POST ${PATH}/messages`]: () => {
        posts += 1;
        return { body: withReply('Still stuck', 'Try signing out and in.') };
      },
    });
    (impl as jest.Mock).mockImplementationOnce(async () => {
      throw new TypeError('Network request failed');
    });
    await fireEvent.changeText(composer(), 'Still stuck');
    await fireEvent.press(sendButton());
    expect(await screen.findByText(/Can't reach the help desk/)).toBeOnTheScreen();
    expect(composer()).toHaveDisplayValue('Still stuck');
    await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Try signing out and in.')).toBeOnTheScreen();
    expect(posts).toBe(1);
  });

  it('never resends after a timeout: warns, reloads, and keeps a message that went through', async () => {
    const base = chatSession();
    const stored = chatSession({ messages: [...base.messages, chatLine('CM3', 'customer', 'Still stuck')] });
    let gets = 0;
    let posts = 0;
    const { impl } = await setup(
      base,
      {
        [`GET ${PATH}`]: () => {
          gets += 1;
          return { body: gets === 1 ? base : stored };
        },
        [`POST ${PATH}/messages`]: () => {
          posts += 1;
          return { body: base };
        },
      },
      { timeoutMs: 300 },
    );
    hangOnce(impl);
    await fireEvent.changeText(composer(), 'Still stuck');
    await fireEvent.press(sendButton());
    expect(await screen.findByTestId('chat-notice')).toHaveTextContent(/may have gone through/);
    await waitFor(() => expect(gets).toBe(2));
    expect(await screen.findByText('Still stuck')).toBeOnTheScreen();
    expect(composer()).toHaveDisplayValue('');
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeOnTheScreen();
    expect(posts).toBe(0);
  });

  it('shows a closed chat read-only', async () => {
    await setup(chatSession({ status: 'resolved' }));
    expect(screen.getByText('Resolved')).toBeOnTheScreen();
    expect(screen.queryByLabelText('Message')).not.toBeOnTheScreen();
    expect(screen.queryByRole('button', { name: 'My issue is solved' })).not.toBeOnTheScreen();
  });

  it("says when the chat isn't available", async () => {
    const onOpenTicket = jest.fn();
    await renderSignedIn(
      <ChatSessionScreen sessionId="CHAT-x" onOpenTicket={onOpenTicket} onNewChat={jest.fn()} />,
      { 'GET /api/chats/CHAT-x': { status: 404, body: { detail: 'Chat not found' } } },
    );
    expect(await screen.findByText("This chat isn't available.")).toBeOnTheScreen();
  });
});
