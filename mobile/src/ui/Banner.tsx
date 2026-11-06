import { StyleSheet, View } from 'react-native';
import { AlertCircle, Info, CheckCircle2, Clock } from 'lucide-react-native';
import { useTheme } from '../theme/ThemeProvider';
import { radius, space } from '../theme/tokens';
import { Text } from './Text';

type Tone = 'negative' | 'info' | 'positive' | 'warning';

type Props = { tone?: Tone; message: string; testID?: string };

export function Banner({ tone = 'negative', message, testID }: Props) {
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
      <Text variant="body" style={[styles.text, { color: pill.fg }]}>
        {message}
      </Text>
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
  text: { flex: 1 },
});
