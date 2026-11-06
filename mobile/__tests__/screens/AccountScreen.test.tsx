import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import { Text } from 'react-native';
import { useSession } from '../../src/auth/SessionProvider';
import { AccountScreen } from '../../src/features/account/AccountScreen';
import { useTheme } from '../../src/theme/ThemeProvider';
import { fakeFetch } from '../../test/fakeFetch';
import { renderWithSession, storeToken, storedToken } from '../../test/render';

const me = { user_id: 'C1', role: 'customer', name: 'Asha Rao', email: 'asha@example.com', must_change_password: false };

function Probe() {
  const { status } = useSession();
  const { scheme } = useTheme();
  return <Text testID="probe">{`${status}|${scheme}`}</Text>;
}

async function setup() {
  await storeToken('tok');
  const { impl } = fakeFetch({ 'GET /api/auth/me': { body: me } });
  const onChangePassword = jest.fn();
  await renderWithSession(
    <>
      <AccountScreen onChangePassword={onChangePassword} />
      <Probe />
    </>,
    impl,
  );
  await screen.findByText('Asha Rao');
  return { onChangePassword };
}

describe('AccountScreen', () => {
  it('shows who is signed in and the server host', async () => {
    await setup();
    expect(screen.getByText('asha@example.com')).toBeOnTheScreen();
    expect(screen.getByText('AR')).toBeOnTheScreen();
    expect(screen.getByText('api.test')).toBeOnTheScreen();
  });

  it('opens change password', async () => {
    const { onChangePassword } = await setup();
    await fireEvent.press(screen.getByRole('button', { name: 'Change password' }));
    expect(onChangePassword).toHaveBeenCalled();
  });

  it('switches to dark mode and remembers it', async () => {
    await setup();
    await fireEvent.press(screen.getByRole('radio', { name: 'Dark' }));
    expect(screen.getByTestId('probe')).toHaveTextContent(/\|dark$/);
    const secure = jest.requireMock('expo-secure-store') as { __store: Map<string, string> };
    expect(secure.__store.get('pref.theme')).toBe('dark');
  });

  it('signs out and clears the stored token', async () => {
    await setup();
    expect(storedToken()).toBe('tok');
    await fireEvent.press(screen.getByRole('button', { name: 'Sign out' }));
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent(/^signedOut\|/));
    expect(storedToken()).toBeNull();
  });
});
