import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView, type Edge } from 'react-native-safe-area-context';
import { useTheme } from '../theme/ThemeProvider';
import { space } from '../theme/tokens';
import { OfflineBanner } from './OfflineBanner';

type Props = {
  children: ReactNode;
  /** Scrollable form/content screen (default) or a fixed layout. */
  scroll?: boolean;
  edges?: Edge[];
  /** Narrow centred column for sign-in style screens. */
  narrow?: boolean;
};

export function Screen({ children, scroll = true, edges = ['top', 'bottom'], narrow }: Props) {
  const { colors } = useTheme();
  const inner = (
    <View style={[styles.inner, narrow && styles.narrow]}>
      <OfflineBanner />
      {children}
    </View>
  );
  return (
    <SafeAreaView edges={edges} style={[styles.flex, { backgroundColor: colors.frame }]}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        {scroll ? (
          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            {inner}
          </ScrollView>
        ) : (
          inner
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  scroll: { flexGrow: 1 },
  inner: { flex: 1, padding: space.lg, gap: space.lg },
  narrow: { width: '100%', maxWidth: 440, alignSelf: 'center', paddingTop: space.xxl },
});
