// Colour tokens shared with the web app (frontend/src/styles/theme.css)
// so the two read as one product. Colour goes on data, status and the
// one primary action; everything else is neutral. Text tokens are
// >= 4.5:1 on their surfaces in both schemes.

export type ColorScheme = 'light' | 'dark';

export type Palette = {
  frame: string; // app background behind cards
  sheet: string; // cards, inputs
  raised: string; // subtle fill (pressed rows, chips)
  border: string;
  rule: string; // hairlines inside cards
  input: string; // input borders
  fg: string;
  mutedFg: string;
  primary: string;
  primaryPressed: string;
  primaryFg: string;
  positive: string;
  negative: string;
  warning: string;
  info: string;
  pill: Record<'neutral' | 'positive' | 'negative' | 'warning' | 'info' | 'accent', { bg: string; fg: string }>;
  /** Ticket status chips, the web's --status-<key>-fg / -bg. */
  status: Record<StatusKey, { bg: string; fg: string }>;
  scrim: string;
};

export type StatusKey = 'open' | 'in_progress' | 'pending_customer' | 'resolved' | 'closed';

export const palettes: Record<ColorScheme, Palette> = {
  light: {
    frame: '#f1f4f6',
    sheet: '#ffffff',
    raised: '#f5f7f9',
    border: '#e3e7ea',
    rule: '#edf0f2',
    input: '#8a919a',
    fg: '#131416',
    mutedFg: '#575c62',
    primary: '#17687b',
    primaryPressed: '#12586a',
    primaryFg: '#ffffff',
    positive: '#1b7348',
    negative: '#c0262b',
    warning: '#8a3d0c',
    info: '#2563a8',
    pill: {
      neutral: { bg: '#e9edf0', fg: '#33383d' },
      positive: { bg: '#dcf5e6', fg: '#0d3d24' },
      negative: { bg: '#fde8e7', fg: '#7f1d1f' },
      warning: { bg: '#fdf1dc', fg: '#7a3a0a' },
      info: { bg: '#e4eef9', fg: '#163f6e' },
      accent: { bg: '#dcf0f4', fg: '#0f4652' },
    },
    status: {
      open: { bg: '#e6edfb', fg: '#1e4fb8' },
      in_progress: { bg: '#ddf2ef', fg: '#0b6b66' },
      pending_customer: { bg: '#efe8fb', fg: '#6a3fb5' },
      resolved: { bg: '#e1f1e6', fg: '#1d6b3d' },
      closed: { bg: '#e7eaef', fg: '#3d4a5c' },
    },
    scrim: 'rgba(19,20,22,0.4)',
  },
  dark: {
    frame: '#0e1114',
    sheet: '#14181c',
    raised: '#1a1f24',
    border: '#262d33',
    rule: '#1e2429',
    input: '#5f6872',
    fg: '#e7eaee',
    mutedFg: '#9ba4ae',
    primary: '#5cbcd1',
    primaryPressed: '#7fcbdc',
    primaryFg: '#071a1f',
    positive: '#4cc38a',
    negative: '#f2777a',
    warning: '#e9a55a',
    info: '#7fb0ec',
    pill: {
      neutral: { bg: '#232a31', fg: '#c9d0d7' },
      positive: { bg: '#12321f', fg: '#8be0b2' },
      negative: { bg: '#3a1717', fg: '#f7a9aa' },
      warning: { bg: '#3a2810', fg: '#f3c58c' },
      info: { bg: '#14263d', fg: '#a9cbf3' },
      accent: { bg: '#0f2e35', fg: '#8fd6e6' },
    },
    status: {
      open: { bg: '#1f2a3d', fg: '#a9c3f2' },
      in_progress: { bg: '#16302d', fg: '#7fd6cc' },
      pending_customer: { bg: '#2a2340', fg: '#c6aef5' },
      resolved: { bg: '#1c2e22', fg: '#8fd3a5' },
      closed: { bg: '#252a31', fg: '#b5c0d0' },
    },
    scrim: 'rgba(0,0,0,0.6)',
  },
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radius = { sm: 6, md: 10, lg: 14, pill: 999 } as const;

export const fonts = {
  regular: 'IBMPlexSans_400Regular',
  medium: 'IBMPlexSans_500Medium',
  semibold: 'IBMPlexSans_600SemiBold',
} as const;

// Sizes follow the web scale, nudged up for phone reading distance.
export const type = {
  caption: { fontSize: 12, lineHeight: 16, fontFamily: fonts.regular },
  label: { fontSize: 13, lineHeight: 18, fontFamily: fonts.medium },
  body: { fontSize: 15, lineHeight: 22, fontFamily: fonts.regular },
  bodyStrong: { fontSize: 15, lineHeight: 22, fontFamily: fonts.medium },
  title: { fontSize: 18, lineHeight: 24, fontFamily: fonts.semibold },
  display: { fontSize: 26, lineHeight: 32, fontFamily: fonts.semibold },
} as const;

export type TypeVariant = keyof typeof type;
