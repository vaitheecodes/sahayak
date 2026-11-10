import { useNetworkState } from 'expo-network';
import { useTranslation } from 'react-i18next';
import { StyleSheet, View } from 'react-native';
import { WifiOff } from 'lucide-react-native';
import { useTheme } from '../theme/ThemeProvider';
import { radius, space } from '../theme/tokens';
import { Text } from './Text';

/** True only when the phone says it has no network at all. "Internet
 *  reachable" isn't used: a help desk on the local network (or the dev
 *  server through adb reverse) works without the internet. */
export function useOffline(): boolean {
  return useNetworkState().isConnected === false;
}

/** A strip at the top of a screen while the phone is offline. */
export function OfflineBanner() {
  const offline = useOffline();
  const { t } = useTranslation();
  const { colors } = useTheme();
  if (!offline) return null;
  return (
    <View
      testID="offline-banner"
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      style={[styles.box, { backgroundColor: colors.pill.neutral.bg }]}
    >
      <WifiOff size={18} color={colors.pill.neutral.fg} />
      <Text variant="label" style={[styles.text, { color: colors.pill.neutral.fg }]}>
        {t('offline.banner')}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: space.sm + 2,
  },
  text: { flex: 1 },
});
