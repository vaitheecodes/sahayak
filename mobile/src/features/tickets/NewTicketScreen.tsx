import { useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { isApiError } from '../../api/errors';
import { DESCRIPTION_MAX, SUBJECT_MAX, ticketsApi } from '../../api/tickets';
import type { CreatedTicket, Priority } from '../../api/types';
import { useApi } from '../../auth/SessionProvider';
import { charCount } from '../../lib/charCount';
import { fieldErrorMessage } from '../../lib/errorMessage';
import { useApiError } from '../../lib/useApiError';
import { useTheme } from '../../theme/ThemeProvider';
import { radius, space, type as typeScale } from '../../theme/tokens';
import { Banner } from '../../ui/Banner';
import { Button } from '../../ui/Button';
import { ChoiceChips } from '../../ui/ChoiceChips';
import { Screen } from '../../ui/Screen';
import { Segmented } from '../../ui/Segmented';
import { Text } from '../../ui/Text';
import { TextField } from '../../ui/TextField';
import { AttachmentPicker } from '../attachments/AttachmentPicker';
import { uploadParts } from '../attachments/pick';
import type { PendingFile } from '../attachments/rules';
import { useMeta } from '../meta/MetaProvider';
import { isRetryable } from './retryable';

const PRIORITIES: Priority[] = ['low', 'medium', 'high', 'urgent'];

type Field = 'subject' | 'description' | 'category' | 'priority';
type Errors = Partial<Record<Field, string>>;

type Props = { onCreated: (ticket: CreatedTicket) => void };

export function NewTicketScreen({ onCreated }: Props) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const api = useApi();
  const meta = useMeta();
  const [subject, setSubject] = useState('');
  const [category, setCategory] = useState<string | null>(null);
  const [priority, setPriority] = useState<Priority>('medium');
  const [description, setDescription] = useState('');
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const [files, setFiles] = useState<PendingFile[]>([]);
  // Set once the ticket exists: from then on only the upload is retried, so
  // a failed upload never creates a second ticket.
  const [created, setCreated] = useState<CreatedTicket | null>(null);
  const apiError = useApiError();
  const uploadError = useApiError();

  const descCount = charCount(description);

  function validate(): Errors {
    const e: Errors = {};
    if (!subject.trim()) e.subject = t('newTicket.subjectRequired');
    else if (charCount(subject) > SUBJECT_MAX) e.subject = t('newTicket.tooLong', { max: SUBJECT_MAX });
    if (!description.trim()) e.description = t('newTicket.descriptionRequired');
    else if (descCount > DESCRIPTION_MAX) e.description = t('newTicket.tooLong', { max: DESCRIPTION_MAX });
    return e;
  }

  /** Files go up after the ticket exists, attached to its first message. */
  async function upload(ticket: CreatedTicket) {
    setSubmitting(true);
    uploadError.clear();
    try {
      await ticketsApi.uploadAttachments(api, ticket.ticket_id, ticket.message_id, await uploadParts(files));
      onCreated(ticket);
    } catch (err) {
      uploadError.show(err);
    } finally {
      setSubmitting(false);
    }
  }

  async function submit() {
    if (created) {
      await upload(created);
      return;
    }
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length) return;
    setSubmitting(true);
    apiError.clear();
    try {
      const ticket = await ticketsApi.create(api, { subject, description, priority, category });
      if (files.length === 0) {
        onCreated(ticket);
        return;
      }
      setCreated(ticket);
      setSubmitting(false);
      await upload(ticket);
    } catch (err) {
      // 422: put each problem under its own field as well as in the banner.
      if (isApiError(err) && err.kind === 'validation') {
        const fieldErrors: Errors = {};
        for (const f of err.fieldErrors) {
          if (['subject', 'description', 'category', 'priority'].includes(f.field)) {
            fieldErrors[f.field as Field] = fieldErrorMessage(t, f);
          }
        }
        setErrors(fieldErrors);
      }
      apiError.show(err);
      setSubmitting(false);
    }
  }

  const clearField = (f: Field) => setErrors((e) => ({ ...e, [f]: undefined }));
  const timedOut = isApiError(apiError.error) && apiError.error.kind === 'timeout';
  const uploadTimedOut = isApiError(uploadError.error) && uploadError.error.kind === 'timeout';
  // The ticket exists: its text can't change any more, only the files.
  const locked = submitting || created !== null;
  const descTooLong = descCount > DESCRIPTION_MAX;
  const descBorder = errors.description || descTooLong ? colors.negative : colors.input;

  return (
    <Screen edges={['bottom']}>
      <Text variant="body" tone="muted">
        {t('newTicket.subtitle')}
      </Text>

      {apiError.message ? (
        <Banner
          testID="new-ticket-error"
          tone={apiError.tone}
          message={timedOut ? t('newTicket.timeout') : apiError.message}
          action={isRetryable(apiError.error) && !timedOut ? { label: t('common.retry'), onPress: submit } : undefined}
        />
      ) : null}

      <TextField
        label={t('newTicket.subject')}
        value={subject}
        onChangeText={(v) => {
          setSubject(v);
          clearField('subject');
        }}
        error={errors.subject}
        maxLength={SUBJECT_MAX}
        returnKeyType="next"
        editable={!locked}
      />

      <View style={styles.group}>
        <Text variant="label" tone="muted">
          {t('newTicket.category')}
        </Text>
        <ChoiceChips
          accessibilityLabel={t('newTicket.category')}
          value={category}
          onChange={(c) => {
            setCategory(c);
            clearField('category');
          }}
          disabled={locked}
          options={[
            { value: null, label: t('newTicket.categoryNone') },
            ...meta.categories.map((c) => ({ value: c, label: meta.categoryLabel(c) })),
          ]}
        />
        {meta.failed && !meta.loaded ? (
          <Text variant="caption" tone="muted">
            {t('newTicket.categoriesFailed')}
          </Text>
        ) : null}
        {errors.category ? (
          <Text variant="caption" tone="negative">
            {errors.category}
          </Text>
        ) : null}
      </View>

      <View style={styles.group}>
        <Text variant="label" tone="muted">
          {t('newTicket.priority')}
        </Text>
        <Segmented
          style={styles.segmented}
          accessibilityLabel={t('newTicket.priority')}
          value={priority}
          onChange={(p) => !locked && setPriority(p)}
          options={PRIORITIES.map((p) => ({ value: p, label: t(`priority.${p}`) }))}
        />
      </View>

      <View style={styles.group}>
        <Text variant="label" tone="muted">
          {t('newTicket.description')}
        </Text>
        <TextInput
          accessibilityLabel={t('newTicket.description')}
          placeholder={t('newTicket.descriptionPlaceholder')}
          placeholderTextColor={colors.mutedFg}
          selectionColor={colors.primary}
          multiline
          textAlignVertical="top"
          value={description}
          editable={!locked}
          onChangeText={(v) => {
            setDescription(v);
            clearField('description');
          }}
          style={[styles.textarea, typeScale.body, { color: colors.fg, borderColor: descBorder, backgroundColor: colors.sheet }]}
        />
        <View style={styles.foot}>
          <Text variant="caption" tone="negative" style={styles.flex}>
            {errors.description ?? ''}
          </Text>
          <Text variant="caption" tone={descTooLong ? 'negative' : 'muted'}>
            {t('ticket.counter', { count: descCount, max: DESCRIPTION_MAX })}
          </Text>
        </View>
      </View>

      <AttachmentPicker files={files} onChange={setFiles} disabled={submitting} />

      {created && uploadError.message ? (
        <View style={styles.group}>
          <Banner
            testID="upload-error"
            tone={uploadTimedOut ? 'warning' : 'negative'}
            message={
              uploadTimedOut
                ? t('attachments.uploadTimeout')
                : t('attachments.ticketUploadFailed', { id: created.ticket_id, reason: uploadError.message })
            }
          />
          {!uploadTimedOut && !isRetryable(uploadError.error) ? (
            <Text variant="caption" tone="muted">
              {t('attachments.fixAndRetry')}
            </Text>
          ) : null}
        </View>
      ) : null}

      {created && uploadTimedOut ? null : (
        <Button
          label={
            submitting
              ? created
                ? t('attachments.uploading', { count: files.length })
                : t('newTicket.submitting')
              : created
                ? t('newTicket.retryUpload')
                : t('newTicket.submit')
          }
          busy={submitting}
          disabled={apiError.coolingDown || uploadError.coolingDown || (created !== null && files.length === 0)}
          onPress={submit}
        />
      )}
      {created && uploadError.message ? (
        <Button
          variant={uploadTimedOut ? 'primary' : 'ghost'}
          label={uploadTimedOut ? t('newTicket.openTicket') : t('newTicket.continueWithout')}
          disabled={submitting}
          onPress={() => onCreated(created)}
        />
      ) : null}
      {submitting && !created ? (
        <Text variant="caption" tone="muted" accessibilityLiveRegion="polite">
          {t('newTicket.submittingHint')}
        </Text>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  segmented: { margin: 0 },
  flex: { flex: 1 },
  group: { gap: space.xs + 2 },
  textarea: {
    minHeight: 160,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingTop: space.md,
    paddingBottom: space.md,
  },
  foot: { flexDirection: 'row', gap: space.md },
});
