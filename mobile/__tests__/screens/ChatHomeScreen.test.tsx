import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';
import { ChatHomeScreen } from '../../src/features/chat/ChatHomeScreen';
import { chatSession, chatSummary, hangOnce, renderSignedIn } from '../../test/tickets';

// Focus = mount in tests; the app reloads each time the tab comes back.
jest.mock('expo-router', () => {
  const { useEffect } = jest.requireActual('react');
  return { useFocusEffect: (cb: () => void) => useEffect(cb, [cb]) };
});

const CHATS = [
  chatSummary({ session_id: 'CHAT-a', issue: 'Export to CSV fails', status: 'active' }),
  chatSummary({ session_id: 'CHAT-b', issue: 'Cannot sign in', status: 'escalated', ticket_id: 'TCK-77' }),
  chatSummary({ session_id: 'CHAT-c', issue: 'Add a team member', status: 'resolved' }),
];

async function setup(routes = {}, chats = CHATS, timeoutMs?: number) {
  const onStarted = jest.fn();
  const onOpen = jest.fn();
  let lists = 0;
  const r = await renderSignedIn(<ChatHomeScreen onStarted={onStarted} onOpen={onOpen} />, {
    'GET /api/chats': () => {
      lists += 1;
      return { body: chats };
    },
    ...routes,
  }, { timeoutMs });
  await screen.findByText('Start a chat');
  return { ...r, onStarted, onOpen, lists: () => lists };
}

const issueField = () => screen.getByLabelText('What do you need help with?');
const startButton = () => screen.getByRole('button', { name: 'Start chat' });

describe('ChatHomeScreen', () => {
  it('lists past chats with their status and ticket', async () => {
    const { onOpen } = await setup();
    expect(await screen.findByText('Export to CSV fails')).toBeOnTheScreen();
    expect(screen.getByText('Ticket TCK-77')).toBeOnTheScreen();
    expect(screen.getByText('Escalated')).toBeOnTheScreen();
    expect(screen.getByText('Resolved')).toBeOnTheScreen();
    await fireEvent.press(screen.getByTestId('chat-CHAT-b'));
    expect(onOpen).toHaveBeenCalledWith('CHAT-b');
  });

  it('says when there are no chats yet', async () => {
    await setup({}, []);
    expect(await screen.findByText('No chats yet')).toBeOnTheScreen();
  });

  it('asks for the issue before calling the server', async () => {
    const { calls } = await setup();
    await fireEvent.press(startButton());
    expect(screen.getByText('Tell us what you need help with.')).toBeOnTheScreen();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('blocks an issue over 500 characters', async () => {
    await setup();
    await fireEvent.changeText(issueField(), 'x'.repeat(501));
    expect(screen.getByText('501 / 500')).toBeOnTheScreen();
    expect(startButton()).toBeDisabled();
  });

  it('starts a chat with the picked category and hands the session on', async () => {
    const started = chatSession({ session_id: 'CHAT-new' });
    const { calls, onStarted } = await setup({ 'POST /api/chats': { body: started } });
    // Categories come from /api/meta, with the admin's labels.
    await fireEvent.press(await screen.findByRole('radio', { name: 'Billing & payments' }));
    await fireEvent.changeText(issueField(), '  How do I download an invoice? ');
    await fireEvent.press(startButton());
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith(started));
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({
      issue: 'How do I download an invoice?',
      category: 'BILLING',
    });
    expect(issueField()).toHaveDisplayValue('');
  });

  it('counts down a rate limit and keeps Start disabled until it ends', async () => {
    await setup({
      'POST /api/chats': { status: 429, body: { detail: 'Too many messages' }, headers: { 'Retry-After': '2' } },
    });
    await fireEvent.changeText(issueField(), 'Export fails');
    jest.useFakeTimers();
    try {
      await fireEvent.press(startButton());
      expect(await screen.findByText(/try again in 2 seconds/)).toBeOnTheScreen();
      expect(startButton()).toBeDisabled();
      for (let i = 0; i < 2; i++) {
        await act(async () => {
          jest.advanceTimersByTime(1000);
        });
      }
      expect(screen.getByText('You can try again now.')).toBeOnTheScreen();
      expect(startButton()).toBeEnabled();
    } finally {
      jest.useRealTimers();
    }
  });

  it('offers Try again when the help desk is busy', async () => {
    let posts = 0;
    const { onStarted } = await setup({
      'POST /api/chats': () => {
        posts += 1;
        return posts === 1 ? { status: 503, body: { detail: 'busy' } } : { body: chatSession() };
      },
    });
    await fireEvent.changeText(issueField(), 'Export fails');
    await fireEvent.press(startButton());
    await fireEvent.press(await screen.findByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
  });

  it('on a timeout, warns the chat may exist and reloads the list instead of retrying', async () => {
    const { impl, lists } = await setup({}, CHATS, 300);
    await screen.findByText('Export to CSV fails');
    hangOnce(impl);
    await fireEvent.changeText(issueField(), 'Export fails');
    await fireEvent.press(startButton());
    expect(await screen.findByText(/your chat may have started/)).toBeOnTheScreen();
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeOnTheScreen();
    await waitFor(() => expect(lists()).toBe(2));
  });
});
