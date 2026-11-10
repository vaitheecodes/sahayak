import type { ErrorBoundaryProps } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Pressable, StyleSheet, Text, View, useColorScheme } from 'react-native';
import { palettes, radius, space, type } from '../../theme/tokens';

/**
 * Shown instead of a screen that crashed while rendering (Expo Router's
 * ErrorBoundary). It can't rely on the app's providers, which may be what
 * failed, so it uses the system colour scheme and plain components. The
 * error itself is never shown to the customer.
 */
export function CrashScreen({ retry }: ErrorBoundaryProps) {
  const { t } = useTranslation();
  const colors = palettes[useColorScheme() === 'dark' ? 'dark' : 'light'];
  return (
    <View style={[styles.wrap, { backgroundColor: colors.frame }]}>
      <Text accessibilityRole="header" style={[type.title, styles.center, { color: colors.fg }]}>
        {t('crash.title')}
      </Text>
      <Text style={[type.body, styles.center, { color: colors.mutedFg }]}>{t('crash.body')}</Text>
      <Pressable
        accessibilityRole="button"
        onPress={retry}
        style={({ pressed }) => [styles.button, { backgroundColor: pressed ? colors.primaryPressed : colors.primary }]}
      >
        <Text style={[type.bodyStrong, { color: colors.primaryFg }]}>{t('common.retry')}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.md, padding: space.xl },
  center: { textAlign: 'center' },
  button: { minHeight: 48, borderRadius: radius.md, paddingHorizontal: space.xl, justifyContent: 'center' },
});
