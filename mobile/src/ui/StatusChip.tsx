import { StyleSheet, View } from 'react-native';
import type { TicketStatus } from '../api/types';
import { useTheme } from '../theme/ThemeProvider';
import { fonts, radius, space, type Palette } from '../theme/tokens';
import { Text } from './Text';

// One status vocabulary, as on the web (frontend ui/StatusChip.jsx):
// open = waiting on the team, in progress = someone has it, pending =
// waiting on the customer, resolved = answered, closed = archived.
type Tone = keyof Palette['pill'];

const TONE: Record<TicketStatus, Tone> = {
  open: 'warning',
  in_progress: 'info',
  pending_customer: 'accent',
  resolved: 'positive',
  closed: 'neutral',
};

export function Chip({ label, tone = 'neutral' }: { label: string; tone?: Tone }) {
  const { colors } = useTheme();
  const pill = colors.pill[tone];
  return (
    <View style={[styles.chip, { backgroundColor: pill.bg }]}>
      <View style={[styles.dot, { backgroundColor: pill.fg }]} />
      <Text variant="caption" style={[styles.label, { color: pill.fg }]}>
        {label}
      </Text>
    </View>
  );
}

export function StatusChip({ status, label }: { status: TicketStatus; label: string }) {
  return <Chip tone={TONE[status] ?? 'neutral'} label={label} />;
}

/** Small outlined tag, e.g. "Chat" on a ticket escalated from a chat. */
export function Tag({ label }: { label: string }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.tag, { borderColor: colors.border }]}>
      <Text variant="caption" tone="muted">
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    alignSelf: 'flex-start',
    borderRadius: radius.pill,
    paddingHorizontal: space.sm + 2,
    paddingVertical: 3,
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
  label: { fontFamily: fonts.medium },
  tag: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.sm,
    paddingHorizontal: 6,
    paddingVertical: 1,
  },
});
