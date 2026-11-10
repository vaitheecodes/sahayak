import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, TextInput, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Inbox, Search, X } from 'lucide-react-native';
import { ticketsApi } from '../../api/tickets';
import type { TicketSummary } from '../../api/types';
import { useApi } from '../../auth/SessionProvider';
import { useApiError } from '../../lib/useApiError';
import { relativeTime } from '../../lib/time';
import { useTheme } from '../../theme/ThemeProvider';
import { radius, space, type as typeScale } from '../../theme/tokens';
import { Banner } from '../../ui/Banner';
import { OfflineBanner, useOffline } from '../../ui/OfflineBanner';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { Segmented } from '../../ui/Segmented';
import { StatusChip, Tag } from '../../ui/StatusChip';
import { Text } from '../../ui/Text';
import { useMeta } from '../meta/MetaProvider';
import { filterTickets, TICKET_FILTERS, type TicketFilter } from './filters';
import { isRetryable } from './retryable';

type Props = {
  onOpen: (ticketId: string) => void;
  onNew: () => void;
};

export function TicketListScreen({ onOpen, onNew }: Props) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const api = useApi();
  const meta = useMeta();
  const [tickets, setTickets] = useState<TicketSummary[] | null>(null);
  const [filter, setFilter] = useState<TicketFilter>('all');
  const [query, setQuery] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const apiError = useApiError();
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      setTickets(await ticketsApi.mine(api));
      apiError.clear();
    } catch (e) {
      apiError.show(e);
    } finally {
      inFlight.current = false;
    }
    // apiError's functions are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  // Reload whenever the tab comes back into view: after reading a ticket
  // (clears its unread dot), replying, reopening or raising a new one.
  // Back online after a failed load: try again without waiting for a pull.
  const offline = useOffline();
  const failed = !!apiError.error;
  useEffect(() => {
    // The request is async: state is only set after it answers.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!offline && failed) load();
    // Only the offline -> online change should trigger this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offline]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([load(), meta.failed ? meta.reload() : undefined]);
    setRefreshing(false);
  }, [load, meta]);

  const visible = useMemo(() => filterTickets(tickets ?? [], filter, query), [tickets, filter, query]);

  if (tickets === null && !apiError.message) {
    return (
      <View style={[styles.center, { backgroundColor: colors.frame }]}>
        <ActivityIndicator color={colors.primary} accessibilityLabel={t('common.loading')} />
      </View>
    );
  }

  const header = (
    <View style={styles.header}>
      <OfflineBanner />
      {apiError.message ? (
        <Banner
          testID="tickets-error"
          tone={apiError.tone}
          message={apiError.message}
          action={isRetryable(apiError.error) ? { label: t('common.retry'), onPress: load } : undefined}
        />
      ) : null}
      {tickets && tickets.length > 0 ? (
        <>
          <Segmented
            style={styles.segmented}
            accessibilityLabel={t('tickets.filterLabel')}
            value={filter}
            onChange={setFilter}
            options={TICKET_FILTERS.map((f) => ({ value: f, label: t(`tickets.${f}`) }))}
          />
          <View style={[styles.search, { backgroundColor: colors.sheet, borderColor: colors.input }]}>
            <Search size={18} color={colors.mutedFg} />
            <TextInput
              accessibilityLabel={t('tickets.search')}
              placeholder={t('tickets.search')}
              placeholderTextColor={colors.mutedFg}
              selectionColor={colors.primary}
              value={query}
              onChangeText={setQuery}
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="search"
              style={[styles.searchInput, typeScale.body, { color: colors.fg }]}
            />
            {query ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={t('tickets.clearSearch')}
                onPress={() => setQuery('')}
                style={styles.clear}
              >
                <X size={18} color={colors.mutedFg} />
              </Pressable>
            ) : null}
          </View>
        </>
      ) : null}
    </View>
  );

  const empty =
    tickets === null ? undefined : tickets.length === 0 ? (
      <EmptyState
        icon={<Inbox size={32} color={colors.mutedFg} />}
        title={t('tickets.emptyTitle')}
        body={t('tickets.emptyBody')}
        action={<Button label={t('newTicket.title')} onPress={onNew} />}
      />
    ) : (
      <EmptyState
        title={t('tickets.noMatchTitle')}
        body={t('tickets.noMatchBody')}
        action={query ? <Button variant="secondary" label={t('tickets.clearSearch')} onPress={() => setQuery('')} /> : null}
      />
    );

  return (
    <FlatList
      style={{ backgroundColor: colors.frame }}
      contentContainerStyle={styles.content}
      data={visible}
      keyExtractor={(item) => item.ticket_id}
      ListHeaderComponent={header}
      ListEmptyComponent={empty}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="on-drag"
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.primary} colors={[colors.primary]} />
      }
      ItemSeparatorComponent={() => <View style={{ height: space.sm }} />}
      renderItem={({ item }) => (
        <TicketRow ticket={item} statusLabel={meta.statusLabel(item.status)} onPress={() => onOpen(item.ticket_id)} />
      )}
    />
  );
}

function TicketRow({ ticket, statusLabel, onPress }: { ticket: TicketSummary; statusLabel: string; onPress: () => void }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const when = relativeTime(t, ticket.last_updated);
  const a11y = [
    ticket.unread ? t('tickets.newReply') : null,
    ticket.subject,
    ticket.ticket_id,
    statusLabel,
    t('tickets.updated', { when }),
  ]
    .filter(Boolean)
    .join(', ');
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={a11y}
      testID={`ticket-${ticket.ticket_id}`}
      onPress={onPress}
      style={({ pressed }) => [
        styles.row,
        { backgroundColor: pressed ? colors.raised : colors.sheet, borderColor: colors.border },
      ]}
    >
      <View style={styles.rowTop}>
        {ticket.unread ? <View testID="unread-dot" style={[styles.dot, { backgroundColor: colors.primary }]} /> : null}
        <Text variant="caption" tone="muted">
          {ticket.ticket_id}
        </Text>
        {ticket.ticket_type === 'chat' ? <Tag label={t('tickets.chatBadge')} /> : null}
        <Text variant="caption" tone="muted" style={styles.time}>
          {when}
        </Text>
      </View>
      <Text variant={ticket.unread ? 'bodyStrong' : 'body'} numberOfLines={2}>
        {ticket.subject}
      </Text>
      <StatusChip status={ticket.status} label={statusLabel} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  segmented: { margin: 0 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { padding: space.lg, paddingTop: space.sm, flexGrow: 1 },
  header: { gap: space.md, marginBottom: space.md },
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    minHeight: 44,
  },
  searchInput: { flex: 1, paddingVertical: space.sm },
  row: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.lg,
    padding: space.lg,
    gap: space.sm,
  },
  rowTop: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  dot: { width: 8, height: 8, borderRadius: 4 },
  clear: { minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  time: { marginLeft: 'auto' },
});
