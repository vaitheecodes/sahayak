/**
 * Length as the server counts it (Python len: code points), so an emoji
 * is one character here too. The server checks the stripped text.
 */
export function charCount(text: string): number {
  return Array.from(text.trim()).length;
}
