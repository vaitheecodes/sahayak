import { Fragment, type ReactNode } from 'react';
import { Linking, StyleSheet, View, type TextStyle } from 'react-native';
import { useTheme } from '../theme/ThemeProvider';
import { fonts, space } from '../theme/tokens';
import { Text } from './Text';

// The small Markdown subset AI and staff replies use: paragraphs, line
// breaks, - / 1. lists, # headings, **bold**, `code` and [links](https://..).
// Anything else shows as plain text. Links open only for http(s).

type Block =
  | { kind: 'p'; lines: string[] }
  | { kind: 'h'; text: string }
  | { kind: 'ul' | 'ol'; items: string[] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;

export function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  let current = null as Block | null;
  const flush = () => {
    if (current) blocks.push(current);
    current = null;
  };
  for (const line of source.replace(/\r\n/g, '\n').split('\n')) {
    if (!line.trim()) {
      flush();
      continue;
    }
    const heading = HEADING.exec(line);
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (heading) {
      flush();
      blocks.push({ kind: 'h', text: heading[1] });
    } else if (bullet || numbered) {
      const kind = bullet ? 'ul' : 'ol';
      const text = (bullet ?? numbered)![1];
      if (current?.kind !== kind) {
        flush();
        current = { kind, items: [] };
      }
      (current as { items: string[] }).items.push(text);
    } else if (current && current.kind !== 'p' && /^\s{2,}/.test(line)) {
      // An indented continuation of the last list item.
      const items = (current as { items: string[] }).items;
      items[items.length - 1] += ` ${line.trim()}`;
    } else {
      if (current?.kind !== 'p') {
        flush();
        current = { kind: 'p', lines: [] };
      }
      (current as { lines: string[] }).lines.push(line);
    }
  }
  flush();
  return blocks;
}

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;

function Inline({ text }: { text: string }) {
  const { colors } = useTheme();
  const parts = text.split(INLINE).filter(Boolean);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return (
            <Text key={i} variant="bodyStrong">
              {part.slice(2, -2)}
            </Text>
          );
        }
        if (part.startsWith('`') && part.endsWith('`')) {
          return (
            <Text key={i} style={[styles.code, { backgroundColor: colors.raised }]}>
              {part.slice(1, -1)}
            </Text>
          );
        }
        const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
        if (link) {
          const url = link[2];
          const safe = /^https?:\/\//i.test(url);
          return (
            <Text
              key={i}
              tone={safe ? 'primary' : 'default'}
              style={safe ? styles.link : undefined}
              accessibilityRole={safe ? 'link' : undefined}
              onPress={safe ? () => Linking.openURL(url).catch(() => undefined) : undefined}
            >
              {link[1]}
            </Text>
          );
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

export function Markdown({ children, style }: { children: string; style?: TextStyle }) {
  const blocks = parseBlocks(children);
  const out: ReactNode[] = blocks.map((b, i) => {
    if (b.kind === 'h') {
      return (
        <Text key={i} variant="bodyStrong" style={style}>
          <Inline text={b.text} />
        </Text>
      );
    }
    if (b.kind === 'p') {
      return (
        <Text key={i} variant="body" style={style}>
          <Inline text={b.lines.join('\n')} />
        </Text>
      );
    }
    return (
      <View key={i} style={styles.list}>
        {b.items.map((item, j) => (
          <View key={j} style={styles.item}>
            <Text variant="body" tone="muted" style={styles.marker}>
              {b.kind === 'ul' ? '•' : `${j + 1}.`}
            </Text>
            <Text variant="body" style={[styles.itemText, style]}>
              <Inline text={item} />
            </Text>
          </View>
        ))}
      </View>
    );
  });
  return <View style={styles.wrap}>{out}</View>;
}

const styles = StyleSheet.create({
  wrap: { gap: space.sm },
  list: { gap: space.xs },
  item: { flexDirection: 'row', gap: space.sm },
  marker: { minWidth: 18 },
  itemText: { flex: 1 },
  code: { fontFamily: fonts.regular, fontSize: 14 },
  link: { textDecorationLine: 'underline' },
});
