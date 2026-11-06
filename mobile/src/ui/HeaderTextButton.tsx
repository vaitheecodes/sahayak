import type { ReactNode } from 'react';
import { Pressable, StyleSheet } from 'react-native';
import { space } from '../theme/tokens';
import { Text } from './Text';

type Props = { label: string; onPress: () => void; icon?: ReactNode; accessibilityLabel?: string };

/** A plain text action for a navigation header (New, Cancel). */
export function HeaderTextButton({ label, onPress, icon, accessibilityLabel }: Props) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      onPress={onPress}
      hitSlop={8}
      style={({ pressed }) => [styles.button, pressed && styles.pressed]}
    >
      {icon}
      <Text variant="bodyStrong" tone="primary">
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: { flexDirection: 'row', alignItems: 'center', gap: space.xs, paddingHorizontal: space.lg },
  pressed: { opacity: 0.6 },
});
