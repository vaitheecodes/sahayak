import { Pressable, StyleSheet, View } from 'react-native';
import { useTheme } from '../theme/ThemeProvider';
import { radius, space } from '../theme/tokens';
import { Text } from './Text';

type Option<T> = { value: T; label: string };

type Props<T> = {
  accessibilityLabel: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
};

/** Single choice from a wrapping row of pills (e.g. a category). */
export function ChoiceChips<T extends string | null>({ accessibilityLabel, options, value, onChange, disabled }: Props<T>) {
  const { colors } = useTheme();
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={accessibilityLabel} style={styles.chips}>
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <Pressable
            key={o.value ?? '__none'}
            accessibilityRole="radio"
            accessibilityState={{ selected, disabled: !!disabled }}
            onPress={() => onChange(o.value)}
            disabled={disabled}
            style={[
              styles.chip,
              {
                borderColor: selected ? colors.primary : colors.border,
                backgroundColor: selected ? colors.pill.accent.bg : colors.sheet,
              },
            ]}
          >
            <Text variant="label" style={{ color: selected ? colors.pill.accent.fg : colors.fg }}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  chip: {
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingHorizontal: space.md,
    paddingVertical: space.sm - 2,
    minHeight: 44,
    justifyContent: 'center',
  },
});
