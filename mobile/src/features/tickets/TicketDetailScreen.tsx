import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Download, Paperclip } from 'lucide-react-native';
import { isApiError } from '../../api/errors';
import { REPLY_MAX, ticketsApi } from '../../api/tickets';
import type { Attachment, ChatTranscriptMessage, ThreadMessage, TicketDetail } from '../../api/types';
import { useApi } from '../../auth/SessionProvider';
import { charCount } from '../../lib/charCount';
import { errorMessage } from '../../lib/errorMessage';
import { useApiError } from '../../lib/useApiError';
import { absoluteTime, relativeTime } from '../../lib/time';
import { useTheme } from '../../theme/ThemeProvider';
import { radius, space, type as typeScale } from '../../theme/tokens';
import { Banner } from '../../ui/Banner';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { Markdown } from '../../ui/Markdown';
import { Chip, StatusChip, Tag } from '../../ui/StatusChip';
import { Text } from '../../ui/Text';
import { AttachmentPicker } from '../attachments/AttachmentPicker';
import { NoViewerError, openAttachment } from '../attachments/openAttachment';
import { uploadParts } from '../attachments/pick';
import { formatBytes, type PendingFile } from '../attachments/rules';
import { useMeta } from '../meta/MetaProvider';
import { isRetryable } from './retryable';
import { threadItems } from './threadView';

type Props = {
  ticketId: string;
  /** Lets the route put the ticket # in the header once it's known. */
  onLoaded?: (detail: TicketDetail) => void;
};

export function TicketDetailScreen({ ticketId, onLoaded }: Props) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const api = useApi();
  const meta = useMeta();
  const insets = useSafeAreaInsets();
  const [detail, setDetail] = useState<TicketDetail | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [reopening, setReopening] = useState(false);
  const loadError = useApiError();
  const actionError = useApiError();

  const load = useCallback(async () => {
    try {
      const d = await ticketsApi.detail(api, ticketId);
      setDetail(d);
      onLoaded?.(d);
      loadError.clear();
    } catch (e) {
      loadError.show(e);
    }
    // useApiError's functions are stable; onLoaded only sets a title.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, ticketId]);

  useEffect(() => {
    // The request is async: state is only set after it answers.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  async function reopen() {
    setReopening(true);
    actionError.clear();
    try {
      await ticketsApi.reopen(api, ticketId);
      await load();
    } catch (e) {
      actionError.show(e);
    } finally {
      setReopening(false);
    }
  }

  if (!detail) {
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
          <EmptyState title={t('ticket.notFound')} body={loadError.message} />
        ) : (
          <View style={styles.pad}>
            <Banner
              testID="ticket-load-error"
              tone={loadError.tone}
              message={loadError.message}
              action={isRetryable(loadError.error) ? { label: t('common.retry'), onPress: load } : undefined}
            />
          </View>
        )}
      </View>
    );
  }

  const { ticket, messages, chat } = detail;
  const items = threadItems(messages, expanded);

  return (
    <KeyboardAvoidingView
      style={[styles.flex, { backgroundColor: colors.frame }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 100 : 0}
    >
      <ScrollView
        // Keeps Send clear of the gesture bar on edge-to-edge Android.
        contentContainerStyle={[styles.content, { paddingBottom: space.xxl + insets.bottom }]}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.primary} colors={[colors.primary]} />
        }
      >
        <View style={styles.headerBlock}>
          <View style={styles.metaRow}>
            <Text variant="caption" tone="muted">
              {ticket.ticket_id}
            </Text>
            <StatusChip status={ticket.status} label={meta.statusLabel(ticket.status)} />
            {ticket.ticket_type === 'chat' ? <Tag label={t('tickets.chatBadge')} /> : null}
          </View>
          <Text variant="title" accessibilityRole="header">
            {ticket.subject}
          </Text>
          <View style={styles.facts}>
            <Fact label={t('ticket.category')} value={meta.categoryLabel(ticket.category)} />
            <Fact label={t('ticket.priority')} value={ticket.priority ? t(`priority.${ticket.priority}`) : '—'} />
            <Fact label={t('ticket.created')} value={absoluteTime(ticket.created_at)} />
          </View>
        </View>

        {loadError.message ? (
          <Banner
            tone={loadError.tone}
            message={loadError.message}
            action={isRetryable(loadError.error) ? { label: t('common.retry'), onPress: load } : undefined}
          />
        ) : null}

        {detail.incident_notice ? <Banner testID="incident-notice" tone="info" message={detail.incident_notice} /> : null}

        {chat && chat.transcript.length > 0 ? <ChatTranscript messages={chat.transcript} /> : null}

        <View style={styles.thread}>
          {items.map((item) =>
            item.kind === 'hidden' ? (
              <Pressable
                key={item.key}
                accessibilityRole="button"
                onPress={() => setExpanded(true)}
                style={[styles.expand, { borderColor: colors.border }]}
              >
                <Text variant="label" tone="primary">
                  {t('ticket.showEarlier', { count: item.count })}
                </Text>
              </Pressable>
            ) : (
              <MessageCard key={item.message.message_id} message={item.message} ticketId={ticket.ticket_id} />
            ),
          )}
        </View>

        {actionError.message ? (
          <Banner testID="ticket-action-error" tone={actionError.tone} message={actionError.message} />
        ) : null}

        {ticket.status === 'resolved' ? (
          <View style={[styles.card, { backgroundColor: colors.sheet, borderColor: colors.border }]}>
            <Text variant="body">{t('ticket.reopenPrompt')}</Text>
            <Button
              variant="secondary"
              label={reopening ? t('ticket.reopening') : t('ticket.reopen')}
              busy={reopening}
              onPress={reopen}
            />
          </View>
        ) : null}

        {ticket.status === 'closed' ? (
          <Text variant="body" tone="muted" style={styles.closedNote}>
            {t('ticket.closedNote')}
          </Text>
        ) : (
          <ReplyComposer ticketId={ticket.ticket_id} disabled={reopening} onSent={load} />
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.fact}>
      <Text variant="caption" tone="muted">
        {label}
      </Text>
      <Text variant="label">{value}</Text>
    </View>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

function MessageCard({ message, ticketId }: { message: ThreadMessage; ticketId: string }) {
  const { t } = useTranslation();
  const { colors } = useTheme();

  if (message.sender === 'system') {
    return (
      <View style={styles.system} accessibilityRole="text">
        <View style={[styles.rule, { backgroundColor: colors.border }]} />
        <Text variant="caption" tone="muted" style={styles.systemText}>
          {message.message} · {relativeTime(t, message.created_at)}
        </Text>
        <View style={[styles.rule, { backgroundColor: colors.border }]} />
      </View>
    );
  }

  const accent = {
    customer: colors.border,
    ai: colors.primary,
    staff: colors.info,
  }[message.sender];
  const isAi = message.sender === 'ai';
  const when = relativeTime(t, message.created_at);

  return (
    <View
      testID={`message-${message.message_id}`}
      accessibilityLabel={`${message.sender_name}, ${when}`}
      style={[styles.card, styles.email, { backgroundColor: colors.sheet, borderColor: colors.border, borderLeftColor: accent }]}
    >
      <View style={styles.emailHead}>
        <View style={[styles.avatar, { backgroundColor: isAi ? colors.pill.accent.bg : colors.raised }]}>
          <Text variant="caption" style={{ color: isAi ? colors.pill.accent.fg : colors.mutedFg }}>
            {isAi ? 'AI' : initials(message.sender_name)}
          </Text>
        </View>
        <View style={styles.flex}>
          <View style={styles.fromLine}>
            <Text variant="bodyStrong" numberOfLines={1} style={styles.shrink}>
              {message.sender_name}
            </Text>
            {message.sender !== 'customer' ? <Tag label={message.sender_role} /> : null}
          </View>
          {message.to ? (
            <Text variant="caption" tone="muted" numberOfLines={1}>
              {t('ticket.to', { name: message.to })}
            </Text>
          ) : null}
        </View>
        <Text variant="caption" tone="muted">
          {when}
        </Text>
      </View>

      {message.incident_update && message.subject ? (
        <View style={styles.fromLine}>
          <Chip tone="info" label={t('ticket.serviceUpdate')} />
          <Text variant="label" style={styles.shrink}>
            {message.subject}
          </Text>
        </View>
      ) : null}

      {message.sender === 'customer' ? (
        <Text variant="body" selectable>
          {message.message}
        </Text>
      ) : (
        <Markdown>{message.message}</Markdown>
      )}

      {message.attachments.length > 0 ? (
        <View style={styles.attachments} accessibilityLabel={t('ticket.attachments')}>
          {message.attachments.map((a) => (
            <AttachmentChip key={a.attachment_id} ticketId={ticketId} attachment={a} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

/** Downloads the file with the session's token and opens it in another app. */
function AttachmentChip({ ticketId, attachment }: { ticketId: string; attachment: Attachment }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const api = useApi();
  const [opening, setOpening] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function open() {
    setOpening(true);
    setProblem(null);
    try {
      await openAttachment(api, ticketId, attachment);
    } catch (e) {
      setProblem(
        e instanceof NoViewerError
          ? t('attachments.noViewer', { name: attachment.filename })
          : t('attachments.downloadFailed', { name: attachment.filename, reason: errorMessage(t, e) }),
      );
    } finally {
      setOpening(false);
    }
  }

  return (
    <View style={styles.chipWrap}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t('ticket.openAttachment', { name: attachment.filename })}
        accessibilityState={{ busy: opening }}
        disabled={opening}
        onPress={open}
        testID={`attachment-${attachment.attachment_id}`}
        style={({ pressed }) => [
          styles.file,
          { borderColor: colors.border, backgroundColor: pressed ? colors.sheet : colors.raised },
        ]}
      >
        {opening ? <ActivityIndicator size="small" color={colors.primary} /> : <Paperclip size={14} color={colors.mutedFg} />}
        <Text variant="caption" numberOfLines={1} style={styles.shrink}>
          {attachment.filename}
        </Text>
        <Text variant="caption" tone="muted">
          {opening ? t('ticket.opening') : formatBytes(attachment.size_bytes)}
        </Text>
        <Download size={14} color={colors.mutedFg} />
      </Pressable>
      {problem ? (
        <Text variant="caption" tone="negative" testID="attachment-error">
          {problem}
        </Text>
      ) : null}
    </View>
  );
}

/** The chat that led to this ticket, collapsed by default. */
function ChatTranscript({ messages }: { messages: ChatTranscriptMessage[] }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <View style={[styles.card, { backgroundColor: colors.sheet, borderColor: colors.border }]}>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        onPress={() => setOpen((o) => !o)}
        style={styles.transcriptHead}
      >
        <Icon size={18} color={colors.mutedFg} />
        <Text variant="bodyStrong">{t('ticket.chatTranscript')}</Text>
        <Text variant="caption" tone="muted" style={styles.shrink}>
          ({t('ticket.chatTranscriptCount', { count: messages.length })})
        </Text>
      </Pressable>
      {open ? (
        <View style={styles.bubbles}>
          {messages.map((m) => {
            const mine = m.role === 'customer';
            return (
              <View
                key={m.message_id}
                style={[
                  styles.bubble,
                  mine
                    ? { alignSelf: 'flex-end', backgroundColor: colors.pill.accent.bg }
                    : { alignSelf: 'flex-start', backgroundColor: colors.raised },
                ]}
              >
                <Text variant="caption" tone="muted">
                  {mine ? t('ticket.you') : t('ticket.bot')}
                </Text>
                {mine ? <Text variant="body">{m.content}</Text> : <Markdown>{m.content}</Markdown>}
              </View>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

function ReplyComposer({ ticketId, disabled, onSent }: { ticketId: string; disabled: boolean; onSent: () => Promise<void> }) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const api = useApi();
  const [text, setText] = useState('');
  const [files, setFiles] = useState<PendingFile[]>([]);
  // The sent reply whose files still have to go up: a retry uploads again,
  // it never sends the reply twice.
  const [pendingMessageId, setPendingMessageId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const error = useApiError();
  const uploadError = useApiError();

  const length = text.trim().length;
  const count = charCount(text);
  const tooLong = count > REPLY_MAX;

  async function upload(messageId: string) {
    uploadError.clear();
    try {
      await ticketsApi.uploadAttachments(api, ticketId, messageId, await uploadParts(files));
      setFiles([]);
      setPendingMessageId(null);
    } catch (e) {
      uploadError.show(e);
    }
  }

  async function send() {
    if (pendingMessageId) {
      setSending(true);
      await upload(pendingMessageId);
      await onSent();
      setSending(false);
      return;
    }
    if (!length || tooLong) return;
    setSending(true);
    setNotice(null);
    error.clear();
    try {
      const res = await ticketsApi.reply(api, ticketId, text);
      setText('');
      // The reply is saved even when the AI couldn't answer it.
      if (res.ai_error) setNotice(res.ai_error);
      if (files.length > 0) {
        setPendingMessageId(res.message_id);
        await upload(res.message_id);
      }
      await onSent();
    } catch (e) {
      error.show(e);
    } finally {
      setSending(false);
    }
  }

  function discardFiles() {
    setFiles([]);
    setPendingMessageId(null);
    uploadError.clear();
  }

  const uploadTimedOut = isApiError(uploadError.error) && uploadError.error.kind === 'timeout';
  const nearLimit = count > REPLY_MAX * 0.9;
  const canSend = pendingMessageId
    ? files.length > 0 && !uploadTimedOut
    : length > 0 && !tooLong && !error.coolingDown;
  return (
    <View style={[styles.card, { backgroundColor: colors.sheet, borderColor: colors.border }]}>
      <Text variant="label" tone="muted">
        {t('ticket.reply')}
      </Text>
      <TextInput
        accessibilityLabel={t('ticket.reply')}
        placeholder={t('ticket.replyPlaceholder')}
        placeholderTextColor={colors.mutedFg}
        selectionColor={colors.primary}
        multiline
        value={text}
        onChangeText={(v) => {
          setText(v);
          if (error.message && !error.coolingDown) error.clear();
        }}
        editable={!disabled && !sending && !pendingMessageId}
        textAlignVertical="top"
        style={[
          styles.textarea,
          typeScale.body,
          { color: colors.fg, borderColor: tooLong ? colors.negative : colors.input },
        ]}
      />
      <AttachmentPicker files={files} onChange={setFiles} disabled={disabled || sending} />
      <View style={styles.composerFoot}>
        <Text variant="caption" tone={tooLong ? 'negative' : 'muted'} style={nearLimit && !tooLong ? { color: colors.warning } : undefined}>
          {t('ticket.counter', { count, max: REPLY_MAX })}
        </Text>
        <Button
          label={
            sending
              ? pendingMessageId
                ? t('attachments.uploading', { count: files.length })
                : t('ticket.sending')
              : pendingMessageId
                ? t('ticket.retryUpload')
                : t('ticket.send')
          }
          busy={sending}
          disabled={disabled || !canSend}
          onPress={send}
          style={styles.send}
        />
      </View>
      {sending && !pendingMessageId ? (
        <Text variant="caption" tone="muted" accessibilityLiveRegion="polite">
          {t('ticket.sendingHint')}
        </Text>
      ) : null}
      {tooLong ? (
        <Text variant="caption" tone="negative">
          {t('ticket.replyTooLong', { max: REPLY_MAX })}
        </Text>
      ) : null}
      {notice ? <Banner testID="reply-notice" tone="warning" message={notice} /> : null}
      {error.message ? (
        <Banner
          testID="reply-error"
          tone={error.tone}
          message={error.message}
          action={isRetryable(error.error) ? { label: t('common.retry'), onPress: send } : undefined}
        />
      ) : null}
      {pendingMessageId && uploadError.message ? (
        <View style={styles.uploadProblem}>
          <Banner
            testID="upload-error"
            tone={uploadTimedOut ? 'warning' : 'negative'}
            message={
              uploadTimedOut ? t('attachments.uploadTimeout') : t('attachments.replyUploadFailed', { reason: uploadError.message })
            }
          />
          {!uploadTimedOut && !isRetryable(uploadError.error) ? (
            <Text variant="caption" tone="muted">
              {t('attachments.fixAndRetry')}
            </Text>
          ) : null}
          <Button variant="ghost" label={t('ticket.discardFiles')} disabled={sending} onPress={discardFiles} />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  shrink: { flexShrink: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  pad: { padding: space.lg },
  content: { padding: space.lg, gap: space.lg, paddingBottom: space.xxl },
  headerBlock: { gap: space.sm },
  metaRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: space.sm },
  facts: { flexDirection: 'row', flexWrap: 'wrap', gap: space.xl, marginTop: space.xs },
  fact: { gap: 2 },
  thread: { gap: space.md },
  card: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.lg,
    padding: space.lg,
    gap: space.md,
  },
  email: { borderLeftWidth: 3 },
  emailHead: { flexDirection: 'row', alignItems: 'flex-start', gap: space.md },
  avatar: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  fromLine: { flexDirection: 'row', alignItems: 'center', gap: space.sm, flexWrap: 'wrap' },
  system: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  systemText: { flexShrink: 1, textAlign: 'center' },
  rule: { flex: 1, height: StyleSheet.hairlineWidth },
  expand: {
    alignItems: 'center',
    paddingVertical: space.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderStyle: 'dashed',
    borderRadius: radius.md,
  },
  attachments: { gap: space.xs },
  chipWrap: { gap: 2 },
  file: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.xs + 2,
    alignSelf: 'flex-start',
    maxWidth: '100%',
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.sm,
    paddingHorizontal: space.sm,
    paddingVertical: space.xs,
  },
  transcriptHead: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  bubbles: { gap: space.sm },
  bubble: { maxWidth: '88%', borderRadius: radius.md, padding: space.md, gap: 2 },
  textarea: {
    minHeight: 110,
    maxHeight: 240,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingTop: space.md,
    paddingBottom: space.md,
  },
  composerFoot: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space.md },
  send: { minWidth: 110 },
  closedNote: { textAlign: 'center' },
  uploadProblem: { gap: space.xs },
});
