import { useState } from 'react';
import { Linking, Pressable, StyleSheet, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { Camera, FileText, ImageIcon, Paperclip, X } from 'lucide-react-native';
import { useTheme } from '../../theme/ThemeProvider';
import { radius, space } from '../../theme/tokens';
import { Text } from '../../ui/Text';
import { pickDocuments, pickPhotos, takePhoto, type PickOutcome } from './pick';
import { addFiles, extensionOf, formatBytes, MAX_BYTES, MAX_FILES, type PendingFile, type Rejection } from './rules';

type Props = {
  files: PendingFile[];
  onChange: (files: PendingFile[]) => void;
  disabled?: boolean;
};

/** Camera / Photos / Files buttons and the list of chosen files, each with a
 *  remove button. Files that break the server's rules are refused here with
 *  a reason; the rest are uploaded by the screen after it sends its message. */
export function AttachmentPicker({ files, onChange, disabled }: Props) {
  const { t } = useTranslation();
  const { colors } = useTheme();
  const [rejected, setRejected] = useState<Rejection[]>([]);
  const [problem, setProblem] = useState<'denied' | 'failed' | null>(null);
  const [picking, setPicking] = useState(false);

  const full = files.length >= MAX_FILES;
  const inactive = disabled || full || picking;

  async function pick(source: () => Promise<PickOutcome>) {
    setPicking(true);
    setProblem(null);
    setRejected([]);
    try {
      const outcome = await source();
      if (outcome.kind === 'denied') setProblem('denied');
      if (outcome.kind === 'picked') {
        const next = addFiles(files, outcome.files);
        setRejected(next.rejected);
        if (next.files.length !== files.length) onChange(next.files);
      }
    } catch {
      setProblem('failed');
    } finally {
      setPicking(false);
    }
  }

  function remove(key: string) {
    setRejected([]);
    onChange(files.filter((f) => f.key !== key));
  }

  const maxMb = MAX_BYTES / (1024 * 1024);

  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <Text variant="label" tone="muted">
          {t('attachments.title')}
        </Text>
        <Text variant="caption" tone="muted">
          {t('attachments.count', { count: files.length, max: MAX_FILES })}
        </Text>
      </View>
      <View style={styles.sources}>
        <SourceButton icon={Camera} label={t('attachments.camera')} disabled={inactive} onPress={() => pick(takePhoto)} />
        <SourceButton
          icon={ImageIcon}
          label={t('attachments.photos')}
          disabled={inactive}
          onPress={() => pick(() => pickPhotos(MAX_FILES - files.length))}
        />
        <SourceButton icon={Paperclip} label={t('attachments.files')} disabled={inactive} onPress={() => pick(pickDocuments)} />
      </View>
      <Text variant="caption" tone="muted">
        {full ? t('attachments.full', { max: MAX_FILES }) : t('attachments.rules', { max: MAX_FILES, mb: maxMb })}
      </Text>

      {files.length > 0 ? (
        <View style={styles.list}>
          {files.map((f) => (
            <View
              key={f.key}
              testID={`pending-${f.name}`}
              style={[styles.file, { borderColor: colors.border, backgroundColor: colors.raised }]}
            >
              {['png', 'jpg', 'jpeg'].includes(extensionOf(f.name)) ? (
                <ImageIcon size={16} color={colors.mutedFg} />
              ) : (
                <FileText size={16} color={colors.mutedFg} />
              )}
              <Text variant="label" numberOfLines={1} style={styles.name}>
                {f.name}
              </Text>
              {f.size !== null ? (
                <Text variant="caption" tone="muted">
                  {formatBytes(f.size)}
                </Text>
              ) : null}
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={t('attachments.remove', { name: f.name })}
                disabled={disabled}
                onPress={() => remove(f.key)}
                hitSlop={10}
              >
                <X size={18} color={colors.mutedFg} />
              </Pressable>
            </View>
          ))}
        </View>
      ) : null}

      {rejected.map((r) => (
        <Text key={`${r.name}-${r.reason}`} variant="caption" tone="negative" testID="attachment-rejected">
          {t(`attachments.reject.${r.reason}`, { name: r.name, max: MAX_FILES, mb: maxMb })}
        </Text>
      ))}
      {problem === 'denied' ? (
        <View style={styles.denied}>
          <Text variant="caption" tone="negative">
            {t('attachments.cameraDenied')}
          </Text>
          <Pressable accessibilityRole="button" onPress={() => Linking.openSettings()} hitSlop={8}>
            <Text variant="caption" tone="primary" style={styles.link}>
              {t('attachments.openSettings')}
            </Text>
          </Pressable>
        </View>
      ) : null}
      {problem === 'failed' ? (
        <Text variant="caption" tone="negative">
          {t('attachments.pickFailed')}
        </Text>
      ) : null}
    </View>
  );
}

function SourceButton({
  icon: Icon,
  label,
  disabled,
  onPress,
}: {
  icon: typeof Camera;
  label: string;
  disabled?: boolean;
  onPress: () => void;
}) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.source,
        { borderColor: colors.border, backgroundColor: pressed ? colors.raised : colors.sheet, opacity: disabled ? 0.5 : 1 },
      ]}
    >
      <Icon size={18} color={colors.fg} />
      <Text variant="label">{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: space.sm },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  sources: { flexDirection: 'row', gap: space.sm },
  source: {
    flex: 1,
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.xs + 2,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: space.sm,
  },
  list: { gap: space.xs + 2 },
  file: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    minHeight: 44,
  },
  name: { flex: 1 },
  denied: { gap: 2 },
  link: { textDecorationLine: 'underline' },
});
