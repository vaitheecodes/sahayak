import { useRef, useState } from 'react';
import { StyleSheet, View, type TextInputInstance } from 'react-native';
import { useTranslation } from 'react-i18next';
import { StaffAccountError, useSession, type SignedOutNotice } from '../../auth/SessionProvider';
import { useApiError } from '../../lib/useApiError';
import { space } from '../../theme/tokens';
import { Banner } from '../../ui/Banner';
import { Button } from '../../ui/Button';
import { Screen } from '../../ui/Screen';
import { Text } from '../../ui/Text';
import { TextField } from '../../ui/TextField';
import { Wordmark } from '../../ui/Wordmark';

const NOTICE_KEY: Record<Exclude<SignedOutNotice, null>, string> = {
  expired: 'auth.sessionExpired',
  staff: 'auth.staffAccount',
  signedOut: 'auth.signedOut',
};

export function SignInScreen() {
  const { t } = useTranslation();
  const { signIn, notice, lastEmail } = useSession();
  const [email, setEmail] = useState(lastEmail);
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [staff, setStaff] = useState(false);
  const [busy, setBusy] = useState(false);
  const apiError = useApiError();
  const passwordRef = useRef<TextInputInstance>(null);

  async function submit() {
    const errors: typeof fieldErrors = {};
    if (!email.trim()) errors.email = t('auth.emailRequired');
    if (!password) errors.password = t('auth.passwordRequired');
    setFieldErrors(errors);
    if (errors.email || errors.password) return;

    setBusy(true);
    setStaff(false);
    apiError.clear();
    try {
      await signIn(email, password);
    } catch (e) {
      if (e instanceof StaffAccountError) setStaff(true);
      else apiError.show(e);
    } finally {
      setBusy(false);
    }
  }

  const shownNotice = staff ? 'staff' : !apiError.message ? notice : null;

  return (
    <Screen narrow>
      <Wordmark />
      <View style={styles.heading}>
        <Text variant="display" accessibilityRole="header">
          {t('auth.signInTitle')}
        </Text>
        <Text variant="body" tone="muted">
          {t('auth.signInSubtitle')}
        </Text>
      </View>

      {shownNotice ? (
        <Banner
          testID="signin-notice"
          tone={shownNotice === 'signedOut' ? 'info' : 'warning'}
          message={t(NOTICE_KEY[shownNotice])}
        />
      ) : null}
      {apiError.message ? <Banner testID="signin-error" tone={apiError.tone} message={apiError.message} /> : null}

      <View style={styles.form}>
        <TextField
          label={t('auth.email')}
          value={email}
          onChangeText={(v) => {
            setEmail(v);
            setFieldErrors((e) => ({ ...e, email: undefined }));
          }}
          error={fieldErrors.email}
          keyboardType="email-address"
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="email"
          textContentType="username"
          returnKeyType="next"
          onSubmitEditing={() => passwordRef.current?.focus()}
          maxLength={254}
        />
        <TextField
          ref={passwordRef}
          label={t('auth.password')}
          value={password}
          onChangeText={(v) => {
            setPassword(v);
            setFieldErrors((e) => ({ ...e, password: undefined }));
          }}
          error={fieldErrors.password}
          password
          autoComplete="current-password"
          textContentType="password"
          returnKeyType="go"
          onSubmitEditing={submit}
        />
        <Button
          label={busy ? t('auth.signingIn') : t('auth.signIn')}
          onPress={submit}
          busy={busy}
          disabled={apiError.coolingDown}
        />
      </View>

      <View style={styles.footer}>
        <Text variant="caption" tone="muted">
          {t('auth.noAccount')}
        </Text>
        <Text variant="caption" tone="muted">
          {t('auth.forgotPassword')}
        </Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  heading: { gap: space.xs, marginTop: space.lg },
  form: { gap: space.lg },
  footer: { gap: space.xs, marginTop: 'auto', paddingTop: space.xl },
});
