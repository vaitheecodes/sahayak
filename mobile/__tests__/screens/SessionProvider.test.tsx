import { screen, waitFor } from '@testing-library/react-native';
import { Text } from 'react-native';
import { useSession } from '../../src/auth/SessionProvider';
import { fakeFetch } from '../../test/fakeFetch';
import { renderWithSession, storeToken, storedToken } from '../../test/render';

function Probe() {
  const { status, notice, user } = useSession();
  return <Text testID="probe">{`${status}|${notice ?? ''}|${user?.name ?? ''}`}</Text>;
}

const me = { user_id: 'C1', role: 'customer', name: 'Asha Rao', email: 'asha@example.com', must_change_password: false };

describe('SessionProvider', () => {
  it('starts signed out with no stored token', async () => {
    const { impl } = fakeFetch({});
    await renderWithSession(<Probe />, impl);
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('signedOut||'));
  });

  it('restores a stored customer session', async () => {
    await storeToken('tok');
    const { impl } = fakeFetch({ 'GET /api/auth/me': { body: me } });
    await renderWithSession(<Probe />, impl);
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('signedIn||Asha Rao'));
  });

  it('returns to sign-in when the stored token has expired', async () => {
    await storeToken('old');
    const { impl } = fakeFetch({ 'GET /api/auth/me': { status: 401, body: { detail: 'Invalid or expired token' } } });
    await renderWithSession(<Probe />, impl);
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('signedOut|expired|'));
    expect(storedToken()).toBeNull();
  });

  it('drops a staff token and says why', async () => {
    await storeToken('tok');
    const { impl } = fakeFetch({ 'GET /api/auth/me': { body: { ...me, role: 'technician' } } });
    await renderWithSession(<Probe />, impl);
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('signedOut|staff|'));
    expect(storedToken()).toBeNull();
  });

  it('keeps the token when the server cannot be reached', async () => {
    await storeToken('tok');
    const impl = (async () => {
      throw new TypeError('Network request failed');
    }) as unknown as typeof fetch;
    await renderWithSession(<Probe />, impl);
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('unreachable||'));
    expect(storedToken()).toBe('tok');
  });
});
