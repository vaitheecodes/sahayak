import { Text as RNText, type TextProps } from 'react-native';
import { useTheme } from '../theme/ThemeProvider';
import { type as typeScale, type TypeVariant } from '../theme/tokens';

type Props = TextProps & {
  variant?: TypeVariant;
  tone?: 'default' | 'muted' | 'primary' | 'negative' | 'positive';
};

export function Text({ variant = 'body', tone = 'default', style, ...rest }: Props) {
  const { colors } = useTheme();
  const color = {
    default: colors.fg,
    muted: colors.mutedFg,
    primary: colors.primary,
    negative: colors.negative,
    positive: colors.positive,
  }[tone];
  return <RNText {...rest} style={[typeScale[variant], { color }, style]} />;
}
