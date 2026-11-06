import { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { useSession } from '../../auth/SessionProvider';
import { useApiError } from '../../lib/useApiError';
import { space } from '../../theme/tokens';
import { Banner } from '../../ui/Banner';
import { Button } from '../../ui/Button';
import { Screen } from '../../ui/Screen';
import { Text } from '../../ui/Text';
import { TextField } from '../../ui/TextField';
import { Wordmark } from '../../ui/Wordmark';

// Same limits as backend/auth.py (MIN_PASSWORD_LENGTH, MAX_PASSWORD_BYTES).
export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_BYTES = 72;

export function utf8Length(s: string): number {
  let bytes = 0;
  for (const ch of s) {
    const code = ch.codePointAt(0)!;
    bytes += code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
  }
  return bytes;
}

type Props = {
  /** forced: first sign-in with a temporary password. */
  mode: 'forced' | 'voluntary';
  onDone?: () => void;
};

type Errors = { current?: string; next?: string; confirm?: string };

export function ChangePasswordScreen({ mode, onDone }: Props) {
  const { t } = useTranslation();
  const { changePassword, signOut } = useSession();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const apiError = useApiError();

  function validate(): Errors {
    const e: Errors = {};
    if (!current) e.current = t('password.currentRequired');
    if (next.length < MIN_PASSWORD_LENGTH) e.next = t('password.tooShort', { min: MIN_PASSWORD_LENGTH });
    else if (utf8Length(next) > MAX_PASSWORD_BYTES) e.next = t('password.tooLong');
    else if (next === current) e.next = t('password.sameAsCurrent');
    if (!e.next && confirm !== next) e.confirm = t('password.mismatch');
    return e;
  }

  async function submit() {
    const e = validate();
    setErrors(e);
    if (e.current || e.next || e.confirm) return;
    setBusy(true);
    apiError.clear();
    try {
      await changePassword(current, next);
      onDone?.();
    } catch (err) {
      apiError.show(err);
    } finally {
      setBusy(false);
    }
  }

  const forced = mode === 'forced';

  return (
    <Screen narrow={forced} edges={forced ? ['top', 'bottom'] : ['bottom']}>
      {forced ? <Wordmark /> : null}
      <View style={styles.heading}>
        <Text variant={forced ? 'display' : 'title'} accessibilityRole="header">
          {forced ? t('password.forcedTitle') : t('password.changeTitle')}
        </Text>
        {forced ? (
          <Text variant="body" tone="muted">
            {t('password.forcedSubtitle')}
          </Text>
        ) : null}
      </View>

      {apiError.message ? <Banner testID="password-error" tone={apiError.tone} message={apiError.message} /> : null}

      <View style={styles.form}>
        <TextField
          label={forced ? t('password.currentForced') : t('password.current')}
          value={current}
          onChangeText={(v) => {
            setCurrent(v);
            setErrors((e) => ({ ...e, current: undefined }));
          }}
          error={errors.current}
          password
          autoComplete="current-password"
          textContentType="password"
        />
        <TextField
          label={t('password.new')}
          value={next}
          onChangeText={(v) => {
            setNext(v);
            setErrors((e) => ({ ...e, next: undefined }));
          }}
          error={errors.next}
          hint={t('password.rules', { min: MIN_PASSWORD_LENGTH })}
          password
          autoComplete="new-password"
          textContentType="newPassword"
        />
        <TextField
          label={t('password.confirm')}
          value={confirm}
          onChangeText={(v) => {
            setConfirm(v);
            setErrors((e) => ({ ...e, confirm: undefined }));
          }}
          error={errors.confirm}
          password
          autoComplete="new-password"
          textContentType="newPassword"
          returnKeyType="done"
          onSubmitEditing={submit}
        />
        <Button
          label={busy ? t('password.saving') : t('password.save')}
          onPress={submit}
          busy={busy}
          disabled={apiError.coolingDown}
        />
        {forced ? <Button variant="ghost" label={t('password.signOutInstead')} onPress={signOut} /> : null}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  heading: { gap: space.xs, marginTop: space.sm },
  form: { gap: space.lg },
});
