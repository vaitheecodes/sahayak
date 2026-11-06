import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import { ChangePasswordScreen, utf8Length } from '../../src/features/auth/ChangePasswordScreen';
import { fakeFetch } from '../../test/fakeFetch';
import { renderWithSession, storeToken } from '../../test/render';

const me = { user_id: 'C1', role: 'customer', name: 'Asha', email: 'a@example.com', must_change_password: true };

async function fill(current: string, next: string, confirm: string) {
  await fireEvent.changeText(screen.getByLabelText('Temporary password'), current);
  await fireEvent.changeText(screen.getByLabelText('New password'), next);
  await fireEvent.changeText(screen.getByLabelText('Confirm new password'), confirm);
  await fireEvent.press(screen.getByRole('button', { name: 'Save password' }));
}

async function setup(routes: Parameters<typeof fakeFetch>[0] = {}) {
  await storeToken('tok');
  const fetch = fakeFetch({ 'GET /api/auth/me': { body: me }, ...routes });
  const onDone = jest.fn();
  await renderWithSession(<ChangePasswordScreen mode="forced" onDone={onDone} />, fetch.impl);
  await screen.findByLabelText('Temporary password');
  return { ...fetch, onDone };
}

describe('ChangePasswordScreen', () => {
  it('checks length and matching before calling the server', async () => {
    const { calls } = await setup();
    await fill('temp-pass', 'short', 'short');
    expect(screen.getByText('Use at least 8 characters.')).toBeOnTheScreen();

    await fill('temp-pass', 'long-enough-1', 'long-enough-2');
    expect(screen.getByText("The two new passwords don't match.")).toBeOnTheScreen();

    await fill('same-password', 'same-password', 'same-password');
    expect(screen.getByText('Choose a password different from the current one.')).toBeOnTheScreen();

    expect(calls.filter((c) => c.path === '/api/auth/change-password')).toHaveLength(0);
  });

  it('refuses passwords over the 72-byte bcrypt limit', async () => {
    await setup();
    const long = 'த'.repeat(25); // 25 characters, 75 bytes
    expect(utf8Length(long)).toBe(75);
    await fill('temp-pass', long, long);
    expect(screen.getByText('That password is too long. Use fewer characters.')).toBeOnTheScreen();
  });

  it('saves the new password', async () => {
    const { calls, onDone } = await setup({ 'POST /api/auth/change-password': { body: { ok: true } } });
    await fill('temp-pass', 'my-own-pass', 'my-own-pass');
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const call = calls.find((c) => c.path === '/api/auth/change-password')!;
    expect(call.body).toEqual({ current_password: 'temp-pass', new_password: 'my-own-pass' });
    expect(call.headers.Authorization).toBe('Bearer tok');
  });

  it("shows the server's reason when it refuses", async () => {
    const { onDone } = await setup({
      'POST /api/auth/change-password': { status: 400, body: { detail: 'Current password is incorrect' } },
    });
    await fill('wrong-temp', 'my-own-pass', 'my-own-pass');
    expect(await screen.findByText('Current password is incorrect')).toBeOnTheScreen();
    expect(onDone).not.toHaveBeenCalled();
  });
});
