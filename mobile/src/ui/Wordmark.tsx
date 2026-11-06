import { StyleSheet, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../theme/ThemeProvider';
import { fonts, radius, space } from '../theme/tokens';
import { Text } from './Text';

/** The product mark: a solid tile with the initial, then name and tagline. */
export function Wordmark() {
  const { colors } = useTheme();
  const { t } = useTranslation();
  return (
    <View style={styles.row} accessible accessibilityLabel={`${t('app.name')}, ${t('app.tagline')}`}>
      <View style={[styles.tile, { backgroundColor: colors.primary }]}>
        <Text style={[styles.initial, { color: colors.primaryFg }]}>S</Text>
      </View>
      <View>
        <Text variant="title">{t('app.name')}</Text>
        <Text variant="caption" tone="muted">
          {t('app.tagline')}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  tile: { width: 40, height: 40, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  initial: { fontSize: 22, lineHeight: 28, fontFamily: fonts.semibold },
});
