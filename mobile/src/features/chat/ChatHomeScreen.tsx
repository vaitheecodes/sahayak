import { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, TextInput, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { isApiError } from '../../api/errors';
import { ISSUE_MAX, chatsApi } from '../../api/chats';
import type { ChatSession, ChatSummary } from '../../api/types';
import { useApi } from '../../auth/SessionProvider';
import { charCount } from '../../lib/charCount';
import { fieldErrorMessage } from '../../lib/errorMessage';
import { useApiError } from '../../lib/useApiError';
import { relativeTime } from '../../lib/time';
import { useTheme } from '../../theme/ThemeProvider';
import { radius, space, type as typeScale } from '../../theme/tokens';
import { Banner } from '../../ui/Banner';
import { Button } from '../../ui/Button';
import { ChoiceChips } from '../../ui/ChoiceChips';
import { ChatStatusChip } from '../../ui/StatusChip';
import { Text } from '../../ui/Text';
import { useMeta } from '../meta/MetaProvider';
import { isRetryable } from '../tickets/retryable';

type Props = {
  /** A just-started chat, so the session screen renders without a refetch. */
  onStarted: (session: ChatSession) => void;
  onOpen: (sessionId: string) => void;
};

export function ChatHomeScreen({ onStarted, onOpen }: Props) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const api = useApi();
  const [chats, setChats] = useState<ChatSummary[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const listError = useApiError();
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      setChats(await chatsApi.list(api));
      listError.clear();
    } catch (e) {
      listError.show(e);
    } finally {
      inFlight.current = false;
    }
    // useApiError's functions are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  // Back from a chat: its status (resolved, escalated) may have changed.
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const header = (
    <View style={styles.header}>
      <StartChatForm onStarted={onStarted} onMaybeStarted={load} />
      <Text variant="label" tone="muted" accessibilityRole="header" style={styles.historyTitle}>
        {t('chat.history')}
      </Text>
      {listError.message ? (
        <Banner
          testID="chats-error"
          tone={listError.tone}
          message={listError.message}
          action={isRetryable(listError.error) ? { label: t('common.retry'), onPress: load } : undefined}
        />
      ) : null}
      {chats === null && !listError.message ? (
        <ActivityIndicator color={colors.primary} accessibilityLabel={t('common.loading')} />
      ) : null}
    </View>
  );

  const empty =
    chats && chats.length === 0 ? (
      <View style={[styles.empty, { borderColor: colors.border }]}>
        <Text variant="bodyStrong">{t('chat.emptyTitle')}</Text>
        <Text variant="body" tone="muted">
          {t('chat.emptyBody')}
        </Text>
      </View>
    ) : undefined;

  return (
    <FlatList
      style={{ backgroundColor: colors.frame }}
      contentContainerStyle={styles.content}
      data={chats ?? []}
      keyExtractor={(c) => c.session_id}
      ListHeaderComponent={header}
      ListEmptyComponent={empty}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="on-drag"
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.primary} colors={[colors.primary]} />
      }
      ItemSeparatorComponent={() => <View style={{ height: space.sm }} />}
      renderItem={({ item }) => <ChatRow chat={item} onPress={() => onOpen(item.session_id)} />}
    />
  );
}

function StartChatForm({ onStarted, onMaybeStarted }: { onStarted: Props['onStarted']; onMaybeStarted: () => void }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const api = useApi();
  const meta = useMeta();
  const [issue, setIssue] = useState('');
  const [category, setCategory] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const apiError = useApiError();

  const count = charCount(issue);
  const tooLong = count > ISSUE_MAX;

  async function start() {
    if (!issue.trim()) {
      setFieldError(t('chat.issueRequired'));
      return;
    }
    if (tooLong) return;
    setStarting(true);
    apiError.clear();
    try {
      const session = await chatsApi.start(api, issue, category);
      setIssue('');
      setCategory(null);
      onStarted(session);
    } catch (e) {
      if (isApiError(e) && e.kind === 'validation') {
        const issueProblem = e.fieldErrors.find((f) => f.field === 'issue');
        if (issueProblem) setFieldError(fieldErrorMessage(t, issueProblem));
      }
      // The chat may exist even though no answer came back: show the list
      // rather than offering to start it again.
      if (isApiError(e) && e.kind === 'timeout') onMaybeStarted();
      apiError.show(e);
    } finally {
      setStarting(false);
    }
  }

  const timedOut = isApiError(apiError.error) && apiError.error.kind === 'timeout';
  const borderColor = fieldError || tooLong ? colors.negative : colors.input;

  return (
    <View style={[styles.card, { backgroundColor: colors.sheet, borderColor: colors.border }]}>
      <View style={styles.cardHead}>
        <Text variant="title" accessibilityRole="header">
          {t('chat.startTitle')}
        </Text>
        <Text variant="body" tone="muted">
          {t('chat.startSubtitle')}
        </Text>
      </View>

      {apiError.message ? (
        <Banner
          testID="start-chat-error"
          tone={timedOut ? 'warning' : apiError.tone}
          message={timedOut ? t('chat.startTimeout') : apiError.message}
          action={isRetryable(apiError.error) && !timedOut ? { label: t('common.retry'), onPress: start } : undefined}
        />
      ) : null}

      <View style={styles.group}>
        <Text variant="label" tone="muted">
          {t('chat.issue')}
        </Text>
        <TextInput
          accessibilityLabel={t('chat.issue')}
          placeholder={t('chat.issuePlaceholder')}
          placeholderTextColor={colors.mutedFg}
          selectionColor={colors.primary}
          multiline
          textAlignVertical="top"
          value={issue}
          editable={!starting}
          onChangeText={(v) => {
            setIssue(v);
            setFieldError(null);
          }}
          style={[styles.textarea, typeScale.body, { color: colors.fg, borderColor, backgroundColor: colors.sheet }]}
        />
        <View style={styles.foot}>
          <Text variant="caption" tone="negative" style={styles.flex}>
            {fieldError ?? (tooLong ? t('chat.tooLong', { max: ISSUE_MAX }) : '')}
          </Text>
          <Text variant="caption" tone={tooLong ? 'negative' : 'muted'}>
            {t('ticket.counter', { count, max: ISSUE_MAX })}
          </Text>
        </View>
      </View>

      {meta.categories.length > 0 ? (
        <View style={styles.group}>
          <Text variant="label" tone="muted">
            {t('chat.category')}
          </Text>
          <ChoiceChips
            accessibilityLabel={t('chat.category')}
            value={category}
            onChange={setCategory}
            disabled={starting}
            options={[
              { value: null, label: t('chat.categoryNone') },
              ...meta.categories.map((c) => ({ value: c, label: meta.categoryLabel(c) })),
            ]}
          />
        </View>
      ) : null}

      <Button
        label={starting ? t('chat.starting') : t('chat.start')}
        busy={starting}
        disabled={tooLong || apiError.coolingDown}
        onPress={start}
      />
      {starting ? (
        <Text variant="caption" tone="muted" accessibilityLiveRegion="polite">
          {t('chat.startingHint')}
        </Text>
      ) : null}
    </View>
  );
}

function ChatRow({ chat, onPress }: { chat: ChatSummary; onPress: () => void }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const when = relativeTime(t, chat.updated_at);
  const status = t(`chatStatus.${chat.status}`, { defaultValue: chat.status });
  const kind = chat.ticket_id ? t('chat.rowTicket', { id: chat.ticket_id }) : t('chat.rowChat');
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={[chat.issue, kind, status, t('chat.updated', { when })].join(', ')}
      testID={`chat-${chat.session_id}`}
      onPress={onPress}
      style={({ pressed }) => [styles.row, { backgroundColor: pressed ? colors.raised : colors.sheet, borderColor: colors.border }]}
    >
      <View style={styles.rowTop}>
        <Text variant="caption" tone="muted">
          {kind}
        </Text>
        <Text variant="caption" tone="muted" style={styles.time}>
          {when}
        </Text>
      </View>
      <Text variant="body" numberOfLines={2}>
        {chat.issue}
      </Text>
      <ChatStatusChip status={chat.status} label={status} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: space.lg, flexGrow: 1 },
  header: { gap: space.md, marginBottom: space.md },
  historyTitle: { marginTop: space.md, paddingHorizontal: space.xs, textTransform: 'uppercase', letterSpacing: 0.6 },
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.lg, padding: space.lg, gap: space.lg },
  cardHead: { gap: space.xs },
  group: { gap: space.xs + 2 },
  textarea: {
    minHeight: 96,
    maxHeight: 200,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingTop: space.md,
    paddingBottom: space.md,
  },
  foot: { flexDirection: 'row', gap: space.md },
  empty: {
    borderWidth: StyleSheet.hairlineWidth,
    borderStyle: 'dashed',
    borderRadius: radius.lg,
    padding: space.lg,
    gap: space.xs,
    alignItems: 'center',
  },
  row: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.lg, padding: space.lg, gap: space.sm },
  rowTop: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  time: { marginLeft: 'auto' },
});
