import { useTranslation } from 'react-i18next';
import { CloudOff, Settings2 } from 'lucide-react-native';
import { useSession } from '../../auth/SessionProvider';
import { useTheme } from '../../theme/ThemeProvider';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { Screen } from '../../ui/Screen';

/** Have a saved session, but the server couldn't be reached to check it. */
export function OfflineScreen() {
  const { t } = useTranslation();
  const { retry, signOut } = useSession();
  const { colors } = useTheme();
  return (
    <Screen scroll={false}>
      <EmptyState
        icon={<CloudOff size={32} color={colors.mutedFg} />}
        title={t('offline.title')}
        body={t('offline.body')}
        action={
          <>
            <Button label={t('common.retry')} onPress={retry} />
            <Button variant="ghost" label={t('account.signOut')} onPress={signOut} />
          </>
        }
      />
    </Screen>
  );
}

/** The build has no usable API URL (see app.config.ts). */
export function ConfigErrorScreen() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  return (
    <Screen scroll={false}>
      <EmptyState
        icon={<Settings2 size={32} color={colors.mutedFg} />}
        title={t('offline.configTitle')}
        body={t('offline.configBody')}
      />
    </Screen>
  );
}
