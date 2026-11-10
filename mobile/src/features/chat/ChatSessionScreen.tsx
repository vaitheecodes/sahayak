import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTranslation } from 'react-i18next';
import { SendHorizontal } from 'lucide-react-native';
import { isApiError } from '../../api/errors';
import { CHAT_MESSAGE_MAX, ESCALATE_SUBJECT_MAX, chatsApi } from '../../api/chats';
import type { ChatSession, ChatTranscriptMessage } from '../../api/types';
import { useApi } from '../../auth/SessionProvider';
import { charCount } from '../../lib/charCount';
import { useApiError } from '../../lib/useApiError';
import { useKeyboardVisible } from '../../lib/useKeyboardVisible';
import { relativeTime } from '../../lib/time';
import { useTheme } from '../../theme/ThemeProvider';
import { radius, space, type as typeScale } from '../../theme/tokens';
import { Banner } from '../../ui/Banner';
import { OfflineBanner } from '../../ui/OfflineBanner';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { Markdown } from '../../ui/Markdown';
import { ChatStatusChip } from '../../ui/StatusChip';
import { Text } from '../../ui/Text';
import { TextField } from '../../ui/TextField';
import { isRetryable } from '../tickets/retryable';

// The customer's AI chat (backend/chats.py, web ChatSession.jsx). Every
// call returns the whole session, so the screen re-renders from it. AI
// replies are plain text: follow-up and clarify questions come from the
// server as written, with no fixed choices to show as buttons.

type Busy = null | 'send' | 'resolve' | 'escalate';
type Notice = { message: string; offerTicket: boolean };

type Props = {
  sessionId: string;
  /** A just-started session, so it renders without a refetch. */
  initial?: ChatSession | null;
  /** Height of the navigation header, for the keyboard offset on iOS. */
  keyboardOffset?: number;
  onOpenTicket: (ticketId: string) => void;
  onNewChat: () => void;
};

type Row = ChatTranscriptMessage & { pending?: boolean };

export function ChatSessionScreen({ sessionId, initial, keyboardOffset = 0, onOpenTicket, onNewChat }: Props) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const api = useApi();
  const insets = useSafeAreaInsets();
  const keyboardUp = useKeyboardVisible();
  const [session, setSession] = useState<ChatSession | null>(initial ?? null);
  const [input, setInput] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [notice, setNotice] = useState<Notice | null>(
    initial?.ai_error ? { message: initial.ai_error, offerTicket: true } : null,
  );
  const [confirming, setConfirming] = useState(false);
  const loadError = useApiError();
  const error = useApiError();
  const busyRef = useRef(false);

  const load = useCallback(async (): Promise<ChatSession | null> => {
    try {
      const s = await chatsApi.get(api, sessionId);
      setSession(s);
      loadError.clear();
      return s;
    } catch (e) {
      loadError.show(e);
      return null;
    }
    // useApiError's functions are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, sessionId]);

  useEffect(() => {
    if (initial) return;
    // The request is async: state is only set after it answers.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [initial, load]);

  function show(next: ChatSession) {
    setSession(next);
    // The customer's message is saved even when the AI couldn't answer it.
    setNotice(next.ai_error ? { message: next.ai_error, offerTicket: next.status === 'active' } : null);
  }

  /** One request at a time. A timeout is never retried: the server may have
   *  done it, so reload and say so. */
  async function run(kind: Exclude<Busy, null>, call: () => Promise<ChatSession>): Promise<'ok' | 'timeout' | 'failed'> {
    if (busyRef.current) return 'failed';
    busyRef.current = true;
    setBusy(kind);
    error.clear();
    setNotice(null);
    try {
      show(await call());
      return 'ok';
    } catch (e) {
      if (isApiError(e) && e.kind === 'timeout') {
        setNotice({ message: kind === 'send' ? t('chat.timeout') : t('chat.actionTimeout'), offerTicket: false });
        await load();
        return 'timeout';
      }
      error.show(e);
      // 400: the chat stopped being active meanwhile (e.g. escalated).
      if (isApiError(e) && e.kind === 'bad_request') await load();
      return 'failed';
    } finally {
      busyRef.current = false;
      setBusy(null);
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || charCount(text) > CHAT_MESSAGE_MAX || !session) return;
    setInput('');
    setPending(text);
    const outcome = await run('send', () => chatsApi.send(api, session.session_id, text));
    setPending(null);
    // Give the text back to edit or retry, unless it may have been sent.
    if (outcome === 'failed') setInput(text);
  }

  async function escalate(subject: string) {
    if (!session) return;
    const outcome = await run('escalate', () => chatsApi.escalate(api, session.session_id, subject));
    if (outcome !== 'failed') setConfirming(false);
  }

  const rows = useMemo<Row[]>(() => {
    const list: Row[] = session ? [...session.messages] : [];
    if (pending) list.push({ message_id: 'pending', role: 'customer', content: pending, created_at: '', pending: true });
    // The list is inverted so it opens on, and follows, the newest message.
    return list.reverse();
  }, [session, pending]);

  if (!session) {
    if (!loadError.message) {
      return (
        <View style={[styles.center, { backgroundColor: colors.frame }]}>
          <ActivityIndicator color={colors.primary} accessibilityLabel={t('common.loading')} />
        </View>
      );
    }
    const gone = isApiError(loadError.error) && ['not_found', 'forbidden'].includes(loadError.error.kind);
    return (
      <View style={[styles.flex, { backgroundColor: colors.frame }]}>
        {gone ? (
          <EmptyState title={t('chat.notFound')} body={loadError.message} />
        ) : (
          <View style={styles.pad}>
            <OfflineBanner />
            <Banner
              testID="chat-load-error"
              tone={loadError.tone}
              message={loadError.message}
              action={isRetryable(loadError.error) ? { label: t('common.retry'), onPress: load } : undefined}
            />
          </View>
        )}
      </View>
    );
  }

  const active = session.status === 'active';
  const hasAnswer = session.messages.some((m) => m.role === 'ai');
  const count = charCount(input);
  const tooLong = count > CHAT_MESSAGE_MAX;
  const canSend = active && !busy && !!input.trim() && !tooLong && !error.coolingDown;
  const bottomPad = keyboardUp ? space.sm : insets.bottom + space.sm;

  return (
    <KeyboardAvoidingView
      style={[styles.flex, { backgroundColor: colors.frame }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? keyboardOffset : 0}
    >
      <View style={[styles.bar, { backgroundColor: colors.sheet, borderBottomColor: colors.border }]}>
        <OfflineBanner />
        <View style={styles.barTop}>
          <ChatStatusChip status={session.status} label={t(`chatStatus.${session.status}`, { defaultValue: session.status })} />
          <Text variant="body" numberOfLines={1} style={styles.flex}>
            {session.issue}
          </Text>
        </View>
        {active && !confirming ? (
          <View style={styles.actions}>
            <Button
              variant="secondary"
              label={busy === 'resolve' ? t('chat.solving') : t('chat.solved')}
              busy={busy === 'resolve'}
              disabled={!hasAnswer || busy !== null}
              accessibilityHint={hasAnswer ? undefined : t('chat.solvedNeedsAnswer')}
              onPress={() => run('resolve', () => chatsApi.resolve(api, session.session_id))}
              style={styles.action}
            />
            <Button
              variant="secondary"
              label={t('chat.raiseTicket')}
              disabled={busy !== null}
              onPress={() => setConfirming(true)}
              style={styles.action}
            />
          </View>
        ) : null}
      </View>

      <FlatList
        inverted
        style={styles.flex}
        contentContainerStyle={styles.log}
        data={rows}
        keyExtractor={(m) => m.message_id}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
        accessibilityLabel={t('chat.title')}
        // Inverted: the header sits under the newest message.
        ListHeaderComponent={busy === 'send' ? <TypingIndicator /> : undefined}
        ItemSeparatorComponent={() => <View style={{ height: space.sm }} />}
        renderItem={({ item }) => <Bubble message={item} />}
      />

      <View style={[styles.bottom, { paddingBottom: bottomPad, backgroundColor: colors.sheet, borderTopColor: colors.border }]}>
        {notice ? (
          <Banner
            testID="chat-notice"
            tone="warning"
            message={notice.message}
            action={
              notice.offerTicket && active && !confirming
                ? { label: t('chat.raiseTicketInstead'), onPress: () => setConfirming(true) }
                : undefined
            }
          />
        ) : null}
        {error.message ? (
          <Banner
            testID="chat-error"
            tone={error.tone}
            message={error.message}
            action={isRetryable(error.error) && input.trim() ? { label: t('common.retry'), onPress: send } : undefined}
          />
        ) : null}

        {active && confirming ? (
          <RaiseTicketConfirm
            issue={session.issue}
            busy={busy === 'escalate'}
            onCancel={() => setConfirming(false)}
            onConfirm={escalate}
          />
        ) : null}

        {active && !confirming ? (
          <View style={styles.composerWrap}>
            <View style={styles.composer}>
              <TextInput
                accessibilityLabel={t('chat.messageLabel')}
                placeholder={hasAnswer ? t('chat.placeholderFollowUp') : t('chat.placeholderFirst')}
                placeholderTextColor={colors.mutedFg}
                selectionColor={colors.primary}
                multiline
                value={input}
                onChangeText={(v) => {
                  setInput(v);
                  if (error.message && !error.coolingDown) error.clear();
                }}
                style={[
                  styles.input,
                  typeScale.body,
                  { color: colors.fg, backgroundColor: colors.frame, borderColor: tooLong ? colors.negative : colors.input },
                ]}
              />
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={t('chat.send')}
                accessibilityState={{ disabled: !canSend, busy: busy === 'send' }}
                disabled={!canSend}
                onPress={send}
                hitSlop={6}
                style={({ pressed }) => [
                  styles.sendButton,
                  { backgroundColor: canSend ? (pressed ? colors.primaryPressed : colors.primary) : colors.raised },
                ]}
              >
                <SendHorizontal size={20} color={canSend ? colors.primaryFg : colors.mutedFg} />
              </Pressable>
            </View>
            {count > 0 ? (
              <Text
                variant="caption"
                tone={tooLong ? 'negative' : 'muted'}
                style={[styles.counter, count > CHAT_MESSAGE_MAX * 0.9 && !tooLong ? { color: colors.warning } : null]}
              >
                {tooLong ? `${t('chat.tooLong', { max: CHAT_MESSAGE_MAX })} ` : ''}
                {t('ticket.counter', { count, max: CHAT_MESSAGE_MAX })}
              </Text>
            ) : null}
          </View>
        ) : null}

        {session.status === 'resolved' ? (
          <View style={styles.closed}>
            <Text variant="body" tone="muted" style={styles.centerText}>
              {t('chat.resolvedNote')}
            </Text>
            <Button variant="secondary" label={t('chat.newChat')} onPress={onNewChat} />
          </View>
        ) : null}
        {session.status === 'escalated' && session.ticket_id ? (
          <View style={styles.closed}>
            <Text variant="body" tone="muted" style={styles.centerText}>
              {t('chat.escalatedNote', { id: session.ticket_id })}
            </Text>
            <Button label={t('chat.openTicket')} onPress={() => onOpenTicket(session.ticket_id!)} />
          </View>
        ) : null}
      </View>
    </KeyboardAvoidingView>
  );
}

function Bubble({ message }: { message: Row }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const mine = message.role === 'customer';
  const who = mine ? t('chat.you') : t('chat.bot');
  const when = message.pending ? t('chat.sendingMessage') : relativeTime(t, message.created_at);
  return (
    <View
      testID={`chat-message-${message.message_id}`}
      style={[
        styles.bubble,
        mine
          ? { alignSelf: 'flex-end', backgroundColor: colors.pill.accent.bg }
          : { alignSelf: 'flex-start', backgroundColor: colors.sheet, borderColor: colors.border, borderWidth: StyleSheet.hairlineWidth },
        message.pending && styles.pending,
      ]}
    >
      <Text variant="caption" tone="muted">
        {who} · {when}
      </Text>
      {mine ? (
        <Text variant="body" selectable>
          {message.content}
        </Text>
      ) : (
        <Markdown>{message.content}</Markdown>
      )}
    </View>
  );
}

function TypingIndicator() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const [pulse] = useState(() => new Animated.Value(0.3));
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 500, useNativeDriver: true, isInteraction: false }),
        Animated.timing(pulse, { toValue: 0.3, duration: 500, useNativeDriver: true, isInteraction: false }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);
  return (
    <View
      testID="typing-indicator"
      accessibilityRole="text"
      accessibilityLiveRegion="polite"
      accessibilityLabel={t('chat.typing')}
      style={[styles.bubble, styles.typing, { backgroundColor: colors.sheet, borderColor: colors.border }]}
    >
      <Animated.View style={[styles.dots, { opacity: pulse }]}>
        {[0, 1, 2].map((i) => (
          <View key={i} style={[styles.dot, { backgroundColor: colors.mutedFg }]} />
        ))}
      </Animated.View>
      <Text variant="caption" tone="muted">
        {t('chat.typing')}
      </Text>
    </View>
  );
}

function RaiseTicketConfirm({
  issue,
  busy,
  onCancel,
  onConfirm,
}: {
  issue: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (subject: string) => void;
}) {
  const { t } = useTranslation();
  // An empty subject is fine: the server then uses the chat's issue.
  const [subject, setSubject] = useState(() => Array.from(issue).slice(0, ESCALATE_SUBJECT_MAX).join(''));
  return (
    <View style={styles.confirm} testID="raise-ticket-confirm">
      <Text variant="body">{t('chat.confirmText')}</Text>
      <TextField
        label={t('chat.subject')}
        value={subject}
        onChangeText={setSubject}
        maxLength={ESCALATE_SUBJECT_MAX}
        editable={!busy}
        returnKeyType="done"
      />
      <View style={styles.actions}>
        <Button variant="secondary" label={t('common.cancel')} onPress={onCancel} disabled={busy} style={styles.action} />
        <Button
          label={busy ? t('chat.creatingTicket') : t('chat.createTicket')}
          busy={busy}
          onPress={() => onConfirm(subject)}
          style={styles.action}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  centerText: { textAlign: 'center' },
  pad: { padding: space.lg, gap: space.md },
  bar: {
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    gap: space.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  barTop: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  actions: { flexDirection: 'row', gap: space.sm },
  action: { flex: 1 },
  log: { padding: space.lg, flexGrow: 1 },
  bubble: { maxWidth: '86%', borderRadius: radius.lg, paddingHorizontal: space.md, paddingVertical: space.sm + 2, gap: 2 },
  pending: { opacity: 0.6 },
  typing: { alignSelf: 'flex-start', borderWidth: StyleSheet.hairlineWidth, flexDirection: 'row', alignItems: 'center', gap: space.sm, marginTop: space.sm },
  dots: { flexDirection: 'row', gap: 4 },
  dot: { width: 6, height: 6, borderRadius: 3 },
  bottom: {
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: space.md,
    paddingTop: space.sm,
    gap: space.sm,
  },
  composerWrap: { gap: 2 },
  composer: { flexDirection: 'row', alignItems: 'flex-end', gap: space.sm },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 140,
    borderWidth: 1,
    borderRadius: radius.lg,
    paddingHorizontal: space.md,
    paddingTop: Platform.OS === 'ios' ? space.md - 2 : space.sm,
    paddingBottom: Platform.OS === 'ios' ? space.md - 2 : space.sm,
  },
  sendButton: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  counter: { textAlign: 'right', paddingRight: 52 },
  closed: { gap: space.sm, paddingVertical: space.sm },
  confirm: { gap: space.md, paddingVertical: space.xs },
});
