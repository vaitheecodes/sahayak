import { StyleSheet, View } from 'react-native';
import {
  Circle,
  CircleCheck,
  CircleSlash,
  Contrast,
  Hourglass,
  Lock,
  MessageCircle,
  UserRound,
  type LucideIcon,
} from 'lucide-react-native';
import type { ChatStatus, TicketStatus } from '../api/types';
import { useTheme } from '../theme/ThemeProvider';
import { fonts, radius, space, type Palette } from '../theme/tokens';
import { Text } from './Text';

// One status vocabulary, as on the web (frontend lib/statusMeta.js,
// ui/status.jsx): each status has one colour, one icon and one word, so
// colour never carries the meaning alone. Open = waiting on the support
// team, in progress = someone has it, pending = waiting on the customer,
// resolved = answered, closed = archived. ("New" is a staff-only word for
// an open ticket nobody has picked up; customers just see Open.)
const STATUS_ICON: Record<TicketStatus, LucideIcon> = {
  open: Circle,
  in_progress: Contrast,
  pending_customer: Hourglass,
  resolved: CircleCheck,
  closed: Lock,
};

type Colors = { bg: string; fg: string };

export function Chip({ label, colors: tone, icon: Icon }: { label: string; colors: Colors; icon: LucideIcon }) {
  return (
    <View style={[styles.chip, { backgroundColor: tone.bg }]}>
      <Icon size={14} strokeWidth={2} color={tone.fg} />
      <Text variant="caption" style={[styles.label, { color: tone.fg }]}>
        {label}
      </Text>
    </View>
  );
}

export function StatusChip({ status, label }: { status: TicketStatus; label: string }) {
  const { colors } = useTheme();
  return <Chip colors={colors.status[status] ?? colors.status.closed} icon={STATUS_ICON[status] ?? Circle} label={label} />;
}

// Chats have their own lifecycle (backend/chats.py) and use the web's
// chat chip tones (components/ui/StatusChip.jsx CHAT_STATUS): active and
// escalated both amber (waiting on someone), resolved green, ended grey;
// the icon tells active from escalated.
const CHAT: Record<ChatStatus, { tone: keyof Palette['pill']; icon: LucideIcon }> = {
  active: { tone: 'warning', icon: MessageCircle },
  escalated: { tone: 'warning', icon: UserRound },
  resolved: { tone: 'positive', icon: CircleCheck },
  abandoned: { tone: 'neutral', icon: CircleSlash },
};

export function ChatStatusChip({ status, label }: { status: ChatStatus; label: string }) {
  const { colors } = useTheme();
  const meta = CHAT[status] ?? CHAT.abandoned;
  return <Chip colors={colors.pill[meta.tone]} icon={meta.icon} label={label} />;
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
    gap: 5,
    alignSelf: 'flex-start',
    borderRadius: radius.sm,
    paddingLeft: space.xs + 2,
    paddingRight: space.sm,
    paddingVertical: 3,
  },
  label: { fontFamily: fonts.medium },
  tag: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.sm,
    paddingHorizontal: 6,
    paddingVertical: 1,
  },
});
