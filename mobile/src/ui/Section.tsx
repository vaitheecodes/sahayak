import type { ReactNode } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { ChevronRight } from 'lucide-react-native';
import { useTheme } from '../theme/ThemeProvider';
import { radius, space } from '../theme/tokens';
import { Text } from './Text';

/** A titled group of rows on a card, like a settings list. */
export function Section({ title, children }: { title?: string; children: ReactNode }) {
  const { colors } = useTheme();
  return (
    <View style={styles.section}>
      {title ? (
        <Text variant="label" tone="muted" style={styles.title} accessibilityRole="header">
          {title}
        </Text>
      ) : null}
      <View style={[styles.card, { backgroundColor: colors.sheet, borderColor: colors.border }]}>{children}</View>
    </View>
  );
}

type RowProps = {
  label: string;
  value?: string;
  onPress?: () => void;
  first?: boolean;
  right?: ReactNode;
};

export function Row({ label, value, onPress, first, right }: RowProps) {
  const { colors } = useTheme();
  const content = (
    <View style={[styles.row, !first && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border }]}>
      <Text variant="body" style={value ? styles.rowLabel : styles.rowLabelFill}>
        {label}
      </Text>
      {value ? (
        <Text variant="body" tone="muted" numberOfLines={1} style={styles.rowValue}>
          {value}
        </Text>
      ) : null}
      {right}
      {onPress ? <ChevronRight size={18} color={colors.mutedFg} /> : null}
    </View>
  );
  if (!onPress) return content;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => pressed && { backgroundColor: colors.raised }}
    >
      {content}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  section: { gap: space.sm },
  title: { paddingHorizontal: space.xs, textTransform: 'uppercase', letterSpacing: 0.6 },
  card: { borderRadius: radius.lg, borderWidth: StyleSheet.hairlineWidth, overflow: 'hidden' },
  row: {
    minHeight: 52,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
  },
  rowLabel: { flexShrink: 0 },
  rowLabelFill: { flex: 1 },
  rowValue: { flex: 1, textAlign: 'right' },
});
