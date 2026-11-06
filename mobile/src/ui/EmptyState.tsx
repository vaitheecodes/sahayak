import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';
import { space } from '../theme/tokens';
import { Text } from './Text';

type Props = { icon?: ReactNode; title: string; body?: string; action?: ReactNode };

export function EmptyState({ icon, title, body, action }: Props) {
  return (
    <View style={styles.wrap}>
      {icon}
      <Text variant="title" style={styles.center} accessibilityRole="header">
        {title}
      </Text>
      {body ? (
        <Text variant="body" tone="muted" style={styles.center}>
          {body}
        </Text>
      ) : null}
      {action}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.md, padding: space.xl },
  center: { textAlign: 'center' },
});
