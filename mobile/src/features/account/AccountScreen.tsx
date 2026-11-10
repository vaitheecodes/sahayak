import { StyleSheet, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { LogOut } from 'lucide-react-native';
import { useSession } from '../../auth/SessionProvider';
import { appVersion } from '../../config';
import { useTheme, type ThemePreference } from '../../theme/ThemeProvider';
import { fonts, radius, space } from '../../theme/tokens';
import { Button } from '../../ui/Button';
import { Screen } from '../../ui/Screen';
import { Row, Section } from '../../ui/Section';
import { Segmented } from '../../ui/Segmented';
import { Text } from '../../ui/Text';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? '?').concat(parts.length > 1 ? parts[parts.length - 1][0] : '').toUpperCase();
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

type Props = { onChangePassword: () => void };

export function AccountScreen({ onChangePassword }: Props) {
  const { t } = useTranslation();
  const { user, signOut, api } = useSession();
  const { colors, preference, setPreference } = useTheme();

  return (
    <Screen edges={[]}>
      <View style={[styles.profile, { backgroundColor: colors.sheet, borderColor: colors.border }]}>
        <View
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
          style={[styles.avatar, { backgroundColor: colors.pill.accent.bg }]}
        >
          <Text maxFontSizeMultiplier={1.3} style={[styles.avatarText, { color: colors.pill.accent.fg }]}>{initials(user?.name ?? '')}</Text>
        </View>
        <View style={styles.profileText}>
          <Text variant="title" numberOfLines={1}>
            {user?.name}
          </Text>
          <Text variant="body" tone="muted" numberOfLines={1}>
            {user?.email}
          </Text>
        </View>
      </View>

      <Section title={t('account.appearance')}>
        <Segmented<ThemePreference>
          accessibilityLabel={t('account.appearance')}
          value={preference}
          onChange={setPreference}
          options={[
            { value: 'system', label: t('account.themeSystem') },
            { value: 'light', label: t('account.themeLight') },
            { value: 'dark', label: t('account.themeDark') },
          ]}
        />
      </Section>

      <Section title={t('account.security')}>
        <Row first label={t('account.changePassword')} onPress={onChangePassword} />
      </Section>

      <Section title={t('account.about')}>
        <Row first label={t('account.language')} value={t('account.languageEnglish')} />
        <Row label={t('account.version')} value={appVersion} />
        <Row label={t('account.server')} value={hostOf(api.baseUrl)} />
      </Section>

      <Button
        variant="danger"
        label={t('account.signOut')}
        icon={<LogOut size={18} color={colors.negative} />}
        onPress={signOut}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  profile: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    padding: space.lg,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
  },
  avatar: { width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontFamily: fonts.semibold, fontSize: 17 },
  profileText: { flex: 1, gap: 2 },
});
