import { ActivityIndicator, Pressable, StyleSheet, View, type PressableProps } from 'react-native';
import type { ReactNode } from 'react';
import { useTheme } from '../theme/ThemeProvider';
import { radius, space } from '../theme/tokens';
import { Text } from './Text';

type Props = Omit<PressableProps, 'children'> & {
  label: string;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  busy?: boolean;
  icon?: ReactNode;
};

export function Button({ label, variant = 'primary', busy, disabled, icon, style, ...rest }: Props) {
  const { colors } = useTheme();
  const inactive = disabled || busy;

  const look = {
    primary: { bg: colors.primary, bgPressed: colors.primaryPressed, fg: colors.primaryFg, border: colors.primary },
    secondary: { bg: colors.sheet, bgPressed: colors.raised, fg: colors.fg, border: colors.border },
    danger: { bg: colors.sheet, bgPressed: colors.raised, fg: colors.negative, border: colors.border },
    ghost: { bg: 'transparent', bgPressed: colors.raised, fg: colors.primary, border: 'transparent' },
  }[variant];

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!inactive, busy: !!busy }}
      disabled={inactive}
      style={(state) => [
        styles.base,
        {
          backgroundColor: state.pressed ? look.bgPressed : look.bg,
          borderColor: look.border,
          opacity: inactive && !busy ? 0.5 : 1,
        },
        typeof style === 'function' ? style(state) : style,
      ]}
      {...rest}
    >
      <View style={styles.row}>
        {busy ? <ActivityIndicator size="small" color={look.fg} /> : icon}
        <Text variant="bodyStrong" style={{ color: look.fg }}>
          {label}
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 48,
    borderRadius: radius.md,
    borderWidth: 1,
    paddingHorizontal: space.lg,
    justifyContent: 'center',
  },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: space.sm },
});
