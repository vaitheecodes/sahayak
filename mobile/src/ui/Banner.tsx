import { Pressable, StyleSheet, View } from 'react-native';
import { AlertCircle, Info, CheckCircle2, Clock } from 'lucide-react-native';
import { useTheme } from '../theme/ThemeProvider';
import { radius, space } from '../theme/tokens';
import { Text } from './Text';

type Tone = 'negative' | 'info' | 'positive' | 'warning';

type Props = {
  tone?: Tone;
  message: string;
  testID?: string;
  /** e.g. Try again after a network error. */
  action?: { label: string; onPress: () => void };
};

export function Banner({ tone = 'negative', message, testID, action }: Props) {
  const { colors } = useTheme();
  const pill = {
    negative: colors.pill.negative,
    info: colors.pill.info,
    positive: colors.pill.positive,
    warning: colors.pill.warning,
  }[tone];
  const Icon = { negative: AlertCircle, info: Info, positive: CheckCircle2, warning: Clock }[tone];
  return (
    <View
      testID={testID}
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      style={[styles.box, { backgroundColor: pill.bg }]}
    >
      <Icon size={18} color={pill.fg} style={styles.icon} />
      <View style={styles.text}>
        <Text variant="body" style={{ color: pill.fg }}>
          {message}
        </Text>
        {action ? (
          <Pressable accessibilityRole="button" onPress={action.onPress} hitSlop={8} style={styles.action}>
            <Text variant="bodyStrong" style={{ color: pill.fg, textDecorationLine: 'underline' }}>
              {action.label}
            </Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    flexDirection: 'row',
    gap: space.sm,
    borderRadius: radius.md,
    paddingVertical: space.md,
    paddingHorizontal: space.md,
  },
  icon: { marginTop: 2 },
  text: { flex: 1, gap: space.sm },
  // 44pt tall to tap, without pushing the text around.
  action: { alignSelf: 'flex-start', minHeight: 44, justifyContent: 'center', marginVertical: -space.sm },
});
