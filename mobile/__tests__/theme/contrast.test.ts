import { palettes, type ColorScheme, type Palette } from '../../src/theme/tokens';

// WCAG 2 contrast: every text colour on every surface it's drawn on is at
// least 4.5:1, in both schemes; input borders and focus colours (non-text)
// at least 3:1.

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function textPairs(c: Palette): [string, string, string][] {
  const surfaces = { frame: c.frame, sheet: c.sheet, raised: c.raised };
  const pairs: [string, string, string][] = [];
  for (const fg of ['fg', 'mutedFg', 'primary', 'negative', 'positive', 'warning'] as const) {
    for (const [name, bg] of Object.entries(surfaces)) pairs.push([`${fg} on ${name}`, c[fg], bg]);
  }
  pairs.push(['primaryFg on primary', c.primaryFg, c.primary]);
  pairs.push(['primaryFg on primaryPressed', c.primaryFg, c.primaryPressed]);
  for (const [k, v] of Object.entries(c.pill)) pairs.push([`pill ${k}`, v.fg, v.bg]);
  for (const [k, v] of Object.entries(c.status)) pairs.push([`status ${k}`, v.fg, v.bg]);
  // Your own chat bubbles and the selected choice chip.
  pairs.push(['fg on accent bubble', c.fg, c.pill.accent.bg]);
  pairs.push(['mutedFg on accent bubble', c.mutedFg, c.pill.accent.bg]);
  return pairs;
}

describe.each(['light', 'dark'] as ColorScheme[])('%s palette', (scheme) => {
  const c = palettes[scheme];

  it.each(textPairs(c))('%s is at least 4.5:1', (_name, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it('input borders stand out from the field at 3:1', () => {
    expect(contrast(c.input, c.sheet)).toBeGreaterThanOrEqual(3);
    expect(contrast(c.primary, c.sheet)).toBeGreaterThanOrEqual(3);
  });
});
