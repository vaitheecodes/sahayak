import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';
import { Text } from 'react-native';
import { useSession } from '../../src/auth/SessionProvider';
import { SignInScreen } from '../../src/features/auth/SignInScreen';
import { fakeFetch } from '../../test/fakeFetch';
import { renderWithSession, storedToken } from '../../test/render';

function Status() {
  const { status, user } = useSession();
  return <Text testID="status">{`${status}|${user?.must_change_password ?? ''}`}</Text>;
}

async function fillAndSubmit(email = 'asha@example.com', password = 'secret-pass') {
  await fireEvent.changeText(screen.getByLabelText('Email'), email);
  await fireEvent.changeText(screen.getByLabelText('Password'), password);
  await fireEvent.press(screen.getByRole('button', { name: 'Sign in' }));
}

const login = (role: string, mustChange = false) => ({
  body: { user_id: 'U1', role, name: 'Asha Rao', must_change_password: mustChange, token: 'tok-new' },
});

describe('SignInScreen', () => {
  it('asks for missing details without calling the server', async () => {
    const { impl, calls } = fakeFetch({});
    await renderWithSession(<SignInScreen />, impl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Sign in' }));
    expect(screen.getByText('Enter your email address.')).toBeOnTheScreen();
    expect(screen.getByText('Enter your password.')).toBeOnTheScreen();
    expect(calls).toHaveLength(0);
  });

  it('clears a field message once that field is edited', async () => {
    const { impl } = fakeFetch({});
    await renderWithSession(<SignInScreen />, impl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Sign in' }));
    await fireEvent.changeText(screen.getByLabelText('Email'), 'a');
    expect(screen.queryByText('Enter your email address.')).not.toBeOnTheScreen();
    expect(screen.getByText('Enter your password.')).toBeOnTheScreen();
  });

  it('signs a customer in and stores the token securely', async () => {
    const { impl, calls } = fakeFetch({ 'POST /api/auth/login': login('customer') });
    await renderWithSession(
      <>
        <SignInScreen />
        <Status />
      </>,
      impl,
    );
    await fillAndSubmit(' asha@example.com ');
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('signedIn|false'));
    expect(calls[0].body).toEqual({ email: 'asha@example.com', password: 'secret-pass' });
    expect(storedToken()).toBe('tok-new');
  });

  it('flags a temporary password so the forced change screen shows', async () => {
    const { impl } = fakeFetch({ 'POST /api/auth/login': login('customer', true) });
    await renderWithSession(
      <>
        <SignInScreen />
        <Status />
      </>,
      impl,
    );
    await fillAndSubmit();
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('signedIn|true'));
  });

  it('turns staff accounts away and keeps no token', async () => {
    const { impl } = fakeFetch({ 'POST /api/auth/login': login('manager') });
    await renderWithSession(<SignInScreen />, impl);
    await fillAndSubmit();
    expect(await screen.findByText(/This app is for customers/)).toBeOnTheScreen();
    expect(storedToken()).toBeNull();
  });

  it('explains wrong credentials', async () => {
    const { impl } = fakeFetch({
      'POST /api/auth/login': { status: 401, body: { detail: 'Invalid email or password' } },
    });
    await renderWithSession(<SignInScreen />, impl);
    await fillAndSubmit();
    expect(await screen.findByText(/email and password don't match/)).toBeOnTheScreen();
  });

  it('shows a deactivated account message from the server', async () => {
    const { impl } = fakeFetch({
      'POST /api/auth/login': { status: 403, body: { detail: 'This account has been deactivated' } },
    });
    await renderWithSession(<SignInScreen />, impl);
    await fillAndSubmit();
    expect(await screen.findByText('This account has been deactivated')).toBeOnTheScreen();
  });

  it('counts down a rate limit and blocks the button until it ends', async () => {
    jest.useFakeTimers();
    try {
      const { impl } = fakeFetch({
        'POST /api/auth/login': {
          status: 429,
          body: { detail: 'Too many sign-in attempts' },
          headers: { 'Retry-After': '3' },
        },
      });
      await renderWithSession(<SignInScreen />, impl);
      await fillAndSubmit();
      expect(await screen.findByText(/try again in 3 seconds/)).toBeOnTheScreen();
      expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled();

      await act(async () => {
        jest.advanceTimersByTime(1000);
      });
      expect(screen.getByText(/try again in 2 seconds/)).toBeOnTheScreen();

      // One tick per second, each scheduled after the previous render.
      for (let i = 0; i < 2; i++) {
        await act(async () => {
          jest.advanceTimersByTime(1000);
        });
      }
      expect(screen.getByText('You can try again now.')).toBeOnTheScreen();
      expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled();
    } finally {
      jest.useRealTimers();
    }
  });

  it('says when the server cannot be reached', async () => {
    const impl = (async (url: string) => {
      if (url.endsWith('/api/auth/login')) throw new TypeError('Network request failed');
      throw new Error('unexpected');
    }) as unknown as typeof fetch;
    await renderWithSession(<SignInScreen />, impl);
    await fillAndSubmit();
    expect(await screen.findByText(/Can't reach the help desk/)).toBeOnTheScreen();
  });
});
