import { useState, type Ref } from 'react';
import { Pressable, StyleSheet, TextInput, View, type TextInputInstance, type TextInputProps } from 'react-native';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../theme/ThemeProvider';
import { radius, space, type as typeScale } from '../theme/tokens';
import { Text } from './Text';

type Props = TextInputProps & {
  label: string;
  error?: string | null;
  hint?: string;
  /** Adds a Show/Hide toggle and hides the text by default. */
  password?: boolean;
  ref?: Ref<TextInputInstance>;
};

export function TextField({ label, error, hint, password, style, ref, onFocus, onBlur, ...rest }: Props) {
  const { colors } = useTheme();
  const { t } = useTranslation();
  const [focused, setFocused] = useState(false);
  const [revealed, setRevealed] = useState(false);

  const borderColor = error ? colors.negative : focused ? colors.primary : colors.input;

  return (
    <View style={styles.wrap}>
      <Text variant="label" tone="muted">
        {label}
      </Text>
      <View style={[styles.box, { borderColor, backgroundColor: colors.sheet }, focused && styles.focused]}>
        <TextInput
          ref={ref}
          accessibilityLabel={label}
          placeholderTextColor={colors.mutedFg}
          selectionColor={colors.primary}
          secureTextEntry={password && !revealed}
          autoCapitalize={password ? 'none' : rest.autoCapitalize}
          autoCorrect={password ? false : rest.autoCorrect}
          {...rest}
          onFocus={(e) => {
            setFocused(true);
            onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            onBlur?.(e);
          }}
          style={[styles.input, typeScale.body, { color: colors.fg }, style]}
        />
        {password && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={revealed ? t('common.hide') : t('common.show')}
            onPress={() => setRevealed((r) => !r)}
            hitSlop={8}
            style={styles.toggle}
          >
            <Text variant="label" tone="primary">
              {revealed ? t('common.hide') : t('common.show')}
            </Text>
          </Pressable>
        )}
      </View>
      {error ? (
        <Text variant="caption" tone="negative" accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : hint ? (
        <Text variant="caption" tone="muted">
          {hint}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: space.xs + 2 },
  box: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: radius.md,
    minHeight: 48,
  },
  focused: { borderWidth: 1.5 },
  input: { flex: 1, paddingHorizontal: space.md, paddingVertical: space.md },
  toggle: { paddingHorizontal: space.md },
});
